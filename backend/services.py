import json
import sqlite3
from datetime import datetime, timedelta
from backend.decision_engine import calculate_priority, detect_stock_status, evaluate_bottlenecks

def get_kpis(db_conn):
    """
    Computes dashboard KPIs.
    """
    cursor = db_conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM products")
    total_products = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(available_qty) FROM products")
    total_inventory = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status IN ('Created', 'Pending Allocation', 'Partially Allocated')")
    pending_orders = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'Picking'")
    orders_picking = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'Ready for Dispatch'")
    orders_ready = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM products WHERE available_qty <= reorder_level AND available_qty > 0")
    low_stock = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM products WHERE available_qty = 0")
    out_of_stock = cursor.fetchone()[0]
    
    # Delayed orders (explicitly Delayed status, or not dispatched/cancelled and past deadline)
    now_str = datetime.now().isoformat()
    cursor.execute('''
        SELECT COUNT(*) FROM orders 
        WHERE status = 'Delayed' 
           OR (status NOT IN ('Dispatched', 'Cancelled') AND deadline < ?)
    ''', (now_str,))
    delayed_orders = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM products WHERE damaged_qty > 0")
    damaged_items = cursor.fetchone()[0]
    
    # Fulfillment rate = (dispatched / total)
    cursor.execute("SELECT COUNT(*) FROM orders")
    total_orders = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'Dispatched'")
    dispatched_orders = cursor.fetchone()[0]
    fulfillment_rate = round((dispatched_orders / total_orders * 100), 1) if total_orders > 0 else 0.0

    return {
        'total_products': total_products,
        'total_inventory': total_inventory,
        'pending_orders': pending_orders,
        'orders_picking': orders_picking,
        'orders_ready': orders_ready,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'delayed_orders': delayed_orders,
        'damaged_items': damaged_items,
        'fulfillment_rate': fulfillment_rate
    }

def run_what_if_simulation(db_conn, new_orders, stockout_pid, picker_reduction, damaged_qty, supplier_delay):
    """
    Computes a What-If simulation state based on slider inputs.
    Does NOT modify the production database.
    """
    cursor = db_conn.cursor()
    
    # 1. Base statistics
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status != 'Dispatched' AND status != 'Cancelled'")
    current_active_orders = cursor.fetchone()[0]
    
    # 2. Estimate orders affected
    affected_orders = 0
    delays_count = 0
    revenue_at_risk = 0.0
    bottleneck_zones = set()
    recommendations = []
    
    # Scenario A: New urgent orders
    if new_orders > 0:
        affected_orders += int(new_orders * 0.8) # 80% of new orders face immediate bottlenecking
        revenue_at_risk += new_orders * 150.0 # Mock average order value of $150
        recommendations.append(f"Deploy emergency pickers to handle {new_orders} incoming orders.")
        
    # Scenario B: Stockout of product
    if stockout_pid:
        cursor.execute("SELECT name, available_qty FROM products WHERE id = ?", (stockout_pid,))
        prod = cursor.fetchone()
        if prod:
            # How many active orders require this product?
            cursor.execute('''
                SELECT COUNT(DISTINCT order_id), SUM(quantity * 50) as val
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                WHERE oi.product_id = ? AND o.status NOT IN ('Dispatched', 'Cancelled')
            ''', (stockout_pid,))
            ord_cnt, val = cursor.fetchone()
            ord_cnt = ord_cnt or 0
            val = val or 0
            
            affected_orders += ord_cnt
            revenue_at_risk += val
            recommendations.append(f"Trigger emergency replenishment for {prod['name']}. Temporarily hold and consolidate orders containing this item.")

    # Scenario C: Picker capacity reduction
    if picker_reduction > 0:
        # Affects all orders currently picking
        cursor.execute("SELECT COUNT(*), SUM(quantity * 75) FROM picking_tasks WHERE status IN ('Picking', 'Waiting')")
        pick_cnt, val = cursor.fetchone()
        pick_cnt = pick_cnt or 0
        val = val or 0
        
        affected_orders += int(pick_cnt * (picker_reduction / 100.0))
        revenue_at_risk += val * (picker_reduction / 100.0)
        recommendations.append(f"Workforce Capacity drops by {picker_reduction}%. Authorize overtime or reassign packers to picking duty.")

    # Scenario D: Damaged items
    if damaged_qty > 0:
        affected_orders += int(damaged_qty * 0.5)
        revenue_at_risk += damaged_qty * 100.0
        recommendations.append(f"Re-route {damaged_qty} damaged items to claims and update available inventory inventory.")
        
    # Scenario E: Supplier delay
    if supplier_delay > 0:
        # Find orders with deadlines within the supplier delay window
        limit_time = (datetime.now() + timedelta(hours=supplier_delay)).isoformat()
        cursor.execute('''
            SELECT COUNT(*), SUM(oi.quantity * 60)
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            WHERE o.status IN ('Pending Allocation', 'Partially Allocated') AND o.deadline <= ?
        ''', (limit_time,))
        delayed_ord, val = cursor.fetchone()
        delayed_ord = delayed_ord or 0
        val = val or 0
        
        affected_orders += delayed_ord
        revenue_at_risk += val
        recommendations.append(f"Carrier delay of {supplier_delay} hours will block incoming replenishment. Contact critical accounts to adjust delivery slots.")

    # Compute summaries
    expected_delay_hours = round((picker_reduction * 0.2) + (supplier_delay * 0.5) + (new_orders * 0.3), 1)
    bottleneck_score = min(100, int((picker_reduction * 1.2) + (new_orders * 1.5)))
    
    # Construct AI simulated action
    if not recommendations:
        ai_rec = "Current warehouse state is stable. No action required."
    else:
        ai_rec = f"AI Mitigations: {'; '.join(recommendations[:3])} Expected fulfillment efficiency improvement: {max(5, int(picker_reduction * 0.4))}%."

    return {
        'affected_orders': min(current_active_orders + new_orders, affected_orders),
        'expected_delay_hours': expected_delay_hours,
        'revenue_at_risk': round(revenue_at_risk, 2),
        'bottleneck_score': bottleneck_score,
        'ai_recommendation': ai_rec
    }

def get_optimized_picking_path(db_conn, order_id):
    """
    Generates current vs optimized picking path for a given order.
    """
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT oi.product_id, p.name, p.zone, p.location
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order_id,))
    items = cursor.fetchall()
    
    if not items:
        return None
        
    # Mock physical locations & current path (in order of DB entries)
    current_path = [item['location'] for item in items]
    
    # Sort items optimized by Zone and Shelf distance (alphabetical location is a good proxy in warehouse layouts)
    optimized_items = sorted(items, key=lambda x: (x['zone'], x['location']))
    optimized_path = [item['location'] for item in optimized_items]
    
    # Compute mock metrics
    distance_reduced_pct = 0
    time_saved_mins = 0
    if len(current_path) > 1 and current_path != optimized_path:
        distance_reduced_pct = random.randint(15, 45)
        time_saved_mins = len(current_path) * random.randint(2, 4)
        
    return {
        'order_id': order_id,
        'current_path': " → ".join(current_path),
        'optimized_path': " → ".join(optimized_path),
        'distance_reduced': f"{distance_reduced_pct}%",
        'time_saved': f"{time_saved_mins} mins",
        'item_count': len(items)
    }

def execute_live_demo_scenario(db_conn):
    """
    Runs the live demo scenario steps in the database.
    Updates O101, O102, and recommendations.
    Returns: A dictionary of logs representing each step of execution.
    """
    cursor = db_conn.cursor()
    now_str = datetime.now().isoformat()
    steps = []

    # Step 1: Check baseline status
    cursor.execute("SELECT available_qty, reserved_qty FROM products WHERE id = 'P101'")
    p_baseline = cursor.fetchone()
    steps.append({
        'title': "Baseline State Analysis",
        'status': "Done",
        'details': f"Wireless Mouse (P101) available stock: {p_baseline['available_qty']}. Reserved: {p_baseline['reserved_qty']}."
    })

    # Step 2: System detects shortage for Critical Order O101
    cursor.execute("SELECT priority_level, status FROM orders WHERE id = 'O101'")
    o101 = cursor.fetchone()
    steps.append({
        'title': "Urgent Order Shortage Flagged",
        'status': "Done",
        'details': f"Order O101 (VIP, 3h Deadline) has status: {o101['status']}. Demands 10 units of P101. Available stock is insufficient (7 units)."
    })

    # Step 3: Identify lower-priority allocation holding stock
    cursor.execute("SELECT id, priority_level, status FROM orders WHERE id = 'O102'")
    o102 = cursor.fetchone()
    cursor.execute("SELECT allocated_qty FROM order_items WHERE order_id = 'O102' AND product_id = 'P101'")
    o102_alloc = cursor.fetchone()[0]
    steps.append({
        'title': "Competing Allocation Discovered",
        'status': "Done",
        'details': f"Order O102 (Medium priority, 48h Deadline) holds {o102_alloc} allocated units of P101."
    })

    # Step 4: Generate smart recommendation to steal stock
    steps.append({
        'title': "Smart Reallocation Recommendation Generated",
        'status': "Done",
        'details': "Recommendation REC101: Reallocate 5 units of P101 from Order O102 to Critical Order O101."
    })

    # Step 5: Simulate manager accepting recommendation
    # Execute the reallocation transactionally
    cursor.execute("UPDATE order_items SET allocated_qty = 0 WHERE order_id = 'O102' AND product_id = 'P101'")
    cursor.execute("UPDATE order_items SET allocated_qty = 10 WHERE order_id = 'O101' AND product_id = 'P101'")
    
    # Update orders statuses
    cursor.execute("UPDATE orders SET status = 'Partially Allocated' WHERE id = 'O102'")
    cursor.execute("UPDATE orders SET status = 'Allocated' WHERE id = 'O101'")
    
    # Recalculate reserved stock
    cursor.execute("UPDATE products SET reserved_qty = 10 WHERE id = 'P101'") # O101 has 10 units
    cursor.execute("UPDATE products SET available_qty = 0, status = 'Out of Stock' WHERE id = 'P101'") # 7 units available are now gone (0)

    # Add audit log
    details = "Reallocated 5 units of P101 from Order O102 to O101 via Live Demo Scenario."
    reason = "Critical Priority customer fulfillment escalation."
    cursor.execute('''
        INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
        VALUES (?, 'Warehouse Manager', 'Live Demo Run', ?, ?)
    ''', (now_str, details, reason))
    
    # Resolve exception EX103 (Insufficient Stock)
    cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = 'Reallocated stock from order O102' WHERE id = 'EX103'")

    # Mark recommendations as Accepted
    cursor.execute("UPDATE recommendations SET status = 'Accepted' WHERE id = 'REC101'")
    
    # Step 6: Create new alert for P101 Out of Stock and reorder recommendation
    rec_reorder_id = "REC-REORDER-P101"
    cursor.execute("UPDATE recommendations SET priority = 'Critical', status = 'Pending' WHERE id = ?", (rec_reorder_id,))
    
    db_conn.commit()

    steps.append({
        'title': "Recommendation Accepted & Executed",
        'status': "Done",
        'details': "Order O101 is now FULLY ALLOCATED. Order O102 is PARTIALLY ALLOCATED. Wireless Mouse (P101) stock updated. Audit log created. Exception EX103 Resolved."
    })

    return steps
