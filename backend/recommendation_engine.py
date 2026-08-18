import json
import sqlite3
from datetime import datetime
from backend.decision_engine import detect_stock_status, evaluate_bottlenecks

def get_reconciliation_time():
    return datetime.now().isoformat()

def generate_all_recommendations(db_conn):
    """
    Scans products, orders, zones, and exceptions, 
    and inserts new recommendations if they do not already exist.
    """
    cursor = db_conn.cursor()
    now = datetime.now()

    # --- A. SCAN INVENTORY FOR REORDERS ---
    cursor.execute('''
        SELECT id, name, available_qty, reorder_level, reorder_qty, status
        FROM products
        WHERE available_qty <= reorder_level
    ''')
    low_stock_items = cursor.fetchall()
    
    for item in low_stock_items:
        pid = item['id']
        name = item['name']
        avail = item['available_qty']
        level = item['reorder_level']
        qty = item['reorder_qty']
        status = item['status']
        
        rec_id = f"REC-REORDER-{pid}"
        
        # Check if already exists in pending
        cursor.execute("SELECT 1 FROM recommendations WHERE id = ? AND status = 'Pending'", (rec_id,))
        if cursor.fetchone():
            continue
            
        priority = 'Critical' if avail == 0 else 'High'
        title = f"Reorder: {name} ({pid})"
        desc = f"Generate replenishment order for {qty} units of {name}."
        reason = f"Stock level ({avail}) is at or below the reorder threshold of {level}."
        impact = f"Restores inventory health to normal levels and avoids fulfillment bottlenecks."
        payload = json.dumps({"action": "reorder_product", "product_id": pid, "quantity": qty})
        
        cursor.execute('''
            INSERT OR REPLACE INTO recommendations (id, title, description, type, ref_id, reason, impact, priority, status, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        ''', (rec_id, title, desc, 'Reorder', pid, reason, impact, priority, payload))

    # --- B. SCAN FOR URGENT STOCK REALLOCATIONS ---
    # Find orders that are Critical or High and are 'Pending Allocation' or 'Partially Allocated'
    cursor.execute('''
        SELECT o.id, o.customer, o.deadline, o.priority_level, oi.product_id, p.name as product_name,
               (oi.quantity - oi.allocated_qty) as needed_qty
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE o.status IN ('Pending Allocation', 'Partially Allocated')
          AND oi.allocated_qty < oi.quantity
          AND o.priority_level IN ('Critical', 'High')
    ''')
    urgent_shortages = cursor.fetchall()

    for shortage in urgent_shortages:
        to_order_id = shortage['id']
        pid = shortage['product_id']
        pname = shortage['product_name']
        needed = shortage['needed_qty']
        to_priority = shortage['priority_level']
        
        # Find if any lower priority (Medium, Low) order has allocated stock of this product
        cursor.execute('''
            SELECT o.id, o.priority_level, oi.allocated_qty, o.deadline
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            WHERE oi.product_id = ?
              AND oi.allocated_qty > 0
              AND o.status IN ('Allocated', 'Picking') -- stock is reserved but not yet dispatched
              AND o.priority_level IN ('Medium', 'Low')
            ORDER BY o.priority_score ASC -- steal from lowest priority first
        ''', (pid,))
        competing_orders = cursor.fetchall()
        
        if competing_orders:
            from_order = competing_orders[0]
            from_order_id = from_order['id']
            allocated_to_steal = from_order['allocated_qty']
            from_priority = from_order['priority_level']
            
            qty_to_steal = min(needed, allocated_to_steal)
            rec_id = f"REC-ALLOC-{to_order_id}-{from_order_id}-{pid}"
            
            # Check if pending recommendation exists
            cursor.execute("SELECT 1 FROM recommendations WHERE id = ? AND status = 'Pending'", (rec_id,))
            if cursor.fetchone():
                continue
                
            title = f"Stock Reallocation: {pname} to {to_order_id}"
            desc = f"Reallocate {qty_to_steal} units of {pname} from Order {from_order_id} to Critical Order {to_order_id}."
            
            # Calculate deadline urgency
            try:
                deadline = datetime.fromisoformat(shortage['deadline'])
                hours = (deadline - now).total_seconds() / 3600.0
                deadline_str = f"{hours:.1f} hours"
            except Exception:
                deadline_str = "few hours"
                
            reason = f"Order {to_order_id} has '{to_priority}' priority with deadline in {deadline_str}. " \
                     f"Order {from_order_id} has lower priority ('{from_priority}') and currently holds {allocated_to_steal} allocated units."
            impact = f"Fully resolves stock shortage for Order {to_order_id}, allowing picking to start. " \
                     f"Fulfillment for Order {from_order_id} will be temporarily delayed."
            payload = json.dumps({
                "action": "reallocate_stock",
                "from_order": from_order_id,
                "to_order": to_order_id,
                "product_id": pid,
                "quantity": qty_to_steal
            })
            
            cursor.execute('''
                INSERT OR REPLACE INTO recommendations (id, title, description, type, ref_id, reason, impact, priority, status, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
            ''', (rec_id, title, desc, 'Allocation', to_order_id, reason, impact, 'Critical', payload))

    # --- C. WORKER REASSIGNMENTS FOR BOTTLENECK ZONES ---
    bottlenecks = evaluate_bottlenecks(db_conn)
    for b in bottlenecks:
        if b['category'] == 'Picking Zone' and b['severity'] in ['Critical', 'Warning']:
            zone = b['target']
            backlog = b['metrics']['backlog_count']
            
            # Find an Idle picker in another zone
            cursor.execute('''
                SELECT id, name, zone
                FROM pickers
                WHERE status = 'Idle' AND zone != ?
                LIMIT 1
            ''', (zone,))
            idle_picker = cursor.fetchone()
            
            if idle_picker:
                picker_id = idle_picker['id']
                picker_name = idle_picker['name']
                curr_zone = idle_picker['zone']
                
                rec_id = f"REC-MOVE-{picker_id}-{zone.replace(' ', '')}"
                
                cursor.execute("SELECT 1 FROM recommendations WHERE id = ? AND status = 'Pending'", (rec_id,))
                if cursor.fetchone():
                    continue
                    
                title = f"Reassign Picker {picker_name} to {zone}"
                desc = f"Move Picker {picker_name} from {curr_zone} to overloaded {zone}."
                reason = f"{zone} is heavily backlogged with {backlog} picking tasks. Picker {picker_name} is currently idle in {curr_zone}."
                impact = f"Provides immediate picking reinforcement in {zone}, reducing average picking delay."
                payload = json.dumps({
                    "action": "reassign_worker",
                    "picker_id": picker_id,
                    "new_zone": zone
                })
                
                cursor.execute('''
                    INSERT OR REPLACE INTO recommendations (id, title, description, type, ref_id, reason, impact, priority, status, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
                ''', (rec_id, title, desc, 'Worker Reassignment', picker_id, reason, impact, 'High', payload))

    # --- D. EXCEPTION RESOLUTIONS ---
    # Find Open exceptions
    cursor.execute("SELECT id, type, ref_id, severity, description FROM exceptions WHERE status = 'Open'")
    open_exceptions = cursor.fetchall()
    
    for ex in open_exceptions:
        ex_id = ex['id']
        extype = ex['type']
        ref = ex['ref_id']
        sev = ex['severity']
        
        rec_id = f"REC-RESOLVE-{ex_id}"
        
        cursor.execute("SELECT 1 FROM recommendations WHERE id = ? AND status = 'Pending'", (rec_id,))
        if cursor.fetchone():
            continue
            
        title = f"Resolve Exception {ex_id}: {extype}"
        status_action = "resolve_exception"
        
        if extype == 'Quality Check Failure':
            desc = f"Re-route Order {ref} back to Packing station for corrections."
            reason = f"Quality Check failed due to packed product count mismatch."
            impact = f"Corrects order items and allows order to pass quality check for final dispatch."
            payload = json.dumps({"action": "resolve_qc_exception", "exception_id": ex_id, "order_id": ref})
        elif extype == 'Damaged Item':
            desc = f"Write off damaged stock for {ref} and adjust inventory levels."
            reason = f"Physical damage reported in zone shelf. Items cannot be sold."
            impact = f"Corrects available system inventory count, and triggers reorder if stock falls below reorder point."
            payload = json.dumps({"action": "resolve_damaged_exception", "exception_id": ex_id, "product_id": ref})
        else:
            desc = f"Investigate and close exception {ex_id} manually."
            reason = f"Exception logged for action."
            impact = f"Clears exception dashboard and updates workflow status."
            payload = json.dumps({"action": "resolve_generic_exception", "exception_id": ex_id})

        cursor.execute('''
            INSERT OR REPLACE INTO recommendations (id, title, description, type, ref_id, reason, impact, priority, status, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        ''', (rec_id, title, desc, 'Exception Resolution', ex_id, reason, impact, sev, payload))

    db_conn.commit()


def execute_recommendation(db_conn, rec_id, user_role="Warehouse Manager"):
    """
    Executes a recommendation based on its ID and payload.
    Modifies database states and adds an audit log.
    Returns: (success, message)
    """
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM recommendations WHERE id = ?", (rec_id,))
    rec = cursor.fetchone()
    
    if not rec:
        return False, "Recommendation not found."
    if rec['status'] != 'Pending':
        return False, f"Recommendation is already {rec['status']}."
        
    payload = json.loads(rec['payload'])
    action = payload.get('action')
    now_str = datetime.now().isoformat()
    
    try:
        if action == 'reorder_product':
            pid = payload['product_id']
            qty = payload['quantity']
            
            # Fetch product details
            cursor.execute("SELECT name, available_qty FROM products WHERE id = ?", (pid,))
            prod = cursor.fetchone()
            if not prod:
                return False, f"Product {pid} not found."
                
            prev_qty = prod['available_qty']
            new_qty = prev_qty + qty
            
            # Update product quantity and reset status
            cursor.execute('''
                UPDATE products 
                SET available_qty = ?, status = 'Healthy'
                WHERE id = ?
            ''', (new_qty, pid))
            
            # Insert audit log
            details = f"Reordered {qty} units of {prod['name']} ({pid}). Stock increased from {prev_qty} to {new_qty}."
            reason = "Accepted smart reorder recommendation."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Stock Reorder', ?, ?)
            ''', (now_str, user_role, details, reason))
            
        elif action == 'reallocate_stock':
            from_order_id = payload['from_order']
            to_order_id = payload['to_order']
            pid = payload['product_id']
            qty = payload['quantity']
            
            # Verify allocations
            cursor.execute('''
                SELECT allocated_qty FROM order_items 
                WHERE order_id = ? AND product_id = ?
            ''', (from_order_id, pid))
            from_item = cursor.fetchone()
            
            cursor.execute('''
                SELECT quantity, allocated_qty FROM order_items 
                WHERE order_id = ? AND product_id = ?
            ''', (to_order_id, pid))
            to_item = cursor.fetchone()
            
            if not from_item or not to_item:
                return False, "Order items not found."
                
            if from_item['allocated_qty'] < qty:
                return False, f"Order {from_order_id} only has {from_item['allocated_qty']} units allocated. Cannot allocate {qty}."
                
            # Perform reallocations
            new_from_alloc = from_item['allocated_qty'] - qty
            new_to_alloc = to_item['allocated_qty'] + qty
            
            cursor.execute('''
                UPDATE order_items 
                SET allocated_qty = ?
                WHERE order_id = ? AND product_id = ?
            ''', (new_from_alloc, from_order_id, pid))
            
            cursor.execute('''
                UPDATE order_items 
                SET allocated_qty = ?
                WHERE order_id = ? AND product_id = ?
            ''', (new_to_alloc, to_order_id, pid))
            
            # Update order statuses
            # Check if from_order is now partially allocated
            cursor.execute("SELECT SUM(quantity), SUM(allocated_qty) FROM order_items WHERE order_id = ?", (from_order_id,))
            f_qty, f_alloc = cursor.fetchone()
            from_status = 'Pending Allocation' if f_alloc == 0 else ('Partially Allocated' if f_alloc < f_qty else 'Allocated')
            cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (from_status, from_order_id))
            
            # Check if to_order is now fully allocated
            cursor.execute("SELECT SUM(quantity), SUM(allocated_qty) FROM order_items WHERE order_id = ?", (to_order_id,))
            t_qty, t_alloc = cursor.fetchone()
            to_status = 'Allocated' if t_alloc >= t_qty else 'Partially Allocated'
            cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (to_status, to_order_id))
            
            # Recalculate reserved stock
            cursor.execute('''
                UPDATE products 
                SET reserved_qty = (
                    SELECT SUM(oi.allocated_qty) 
                    FROM order_items oi
                    JOIN orders o ON oi.order_id = o.id
                    WHERE oi.product_id = products.id AND o.status NOT IN ('Dispatched', 'Cancelled')
                )
                WHERE id = ?
            ''', (pid,))
            
            # Close exception EX103 if this resolves the O101 shortage
            if to_order_id == 'O101' and to_status == 'Allocated':
                cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = 'Stock reallocated from order O102.' WHERE id = 'EX103'")

            details = f"Reallocated {qty} units of P101 from Order {from_order_id} to {to_order_id}."
            reason = "Accepted stock reallocation recommendation for urgent fulfillment."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Stock Reallocation', ?, ?)
            ''', (now_str, user_role, details, reason))
            
        elif action == 'reassign_worker':
            picker_id = payload['picker_id']
            new_zone = payload['new_zone']
            
            cursor.execute("SELECT name, zone FROM pickers WHERE id = ?", (picker_id,))
            picker = cursor.fetchone()
            if not picker:
                return False, f"Picker {picker_id} not found."
                
            prev_zone = picker['zone']
            cursor.execute("UPDATE pickers SET zone = ?, status = 'Idle' WHERE id = ?", (new_zone, picker_id))
            
            details = f"Reassigned picker {picker['name']} ({picker_id}) from {prev_zone} to {new_zone}."
            reason = f"Accepted workload balancing recommendation."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Worker Reassignment', ?, ?)
            ''', (now_str, user_role, details, reason))
            
        elif action == 'resolve_qc_exception':
            ex_id = payload['exception_id']
            order_id = payload['order_id']
            
            cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = 'Re-routed to packing for correction' WHERE id = ?", (ex_id,))
            cursor.execute("UPDATE orders SET status = 'Picking' WHERE id = ?", (order_id,)) # send back to picking/packing
            
            details = f"Resolved Quality failure exception {ex_id} for Order {order_id}. Status set back to picking."
            reason = "Accepted QC exception resolution recommendation."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Exception Resolution', ?, ?)
            ''', (now_str, user_role, details, reason))
            
        elif action == 'resolve_damaged_exception':
            ex_id = payload['exception_id']
            pid = payload['product_id']
            
            # Fetch damaged qty
            cursor.execute("SELECT damaged_qty, available_qty FROM products WHERE id = ?", (pid,))
            prod = cursor.fetchone()
            d_qty = prod['damaged_qty'] if prod else 0
            
            # Reduce damaged qty and available qty
            cursor.execute('''
                UPDATE products 
                SET available_qty = MAX(0, available_qty - ?), damaged_qty = 0
                WHERE id = ?
            ''', (d_qty, pid))
            
            # Recalculate status
            cursor.execute("SELECT available_qty, reorder_level FROM products WHERE id = ?", (pid,))
            p_avail, p_reorder = cursor.fetchone()
            status = 'Out of Stock' if p_avail == 0 else ('Low Stock' if p_avail <= p_reorder else 'Healthy')
            cursor.execute("UPDATE products SET status = ? WHERE id = ?", (status, pid))

            cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = 'Damaged items written off system.' WHERE id = ?", (ex_id,))
            
            details = f"Resolved Exception {ex_id} for Product {pid}. Written off {d_qty} damaged units."
            reason = "Accepted damaged stock write-off recommendation."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Exception Resolution', ?, ?)
            ''', (now_str, user_role, details, reason))
            
        else:
            # Generic resolve
            ex_id = payload.get('exception_id')
            cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = 'Manually closed by Manager.' WHERE id = ?", (ex_id,))
            details = f"Manually resolved exception {ex_id}."
            reason = "Accepted generic exception resolution recommendation."
            cursor.execute('''
                INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
                VALUES (?, ?, 'Exception Resolution', ?, ?)
            ''', (now_str, user_role, details, reason))

        # Mark recommendation as Accepted
        cursor.execute("UPDATE recommendations SET status = 'Accepted' WHERE id = ?", (rec_id,))
        db_conn.commit()
        return True, "Recommendation executed successfully."
        
    except Exception as e:
        db_conn.rollback()
        return False, f"Execution failed: {str(e)}"
