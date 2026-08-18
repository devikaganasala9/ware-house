
import os
import sqlite3
import json
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from database.db_manager import get_db_connection, init_db, seed_db, DB_PATH
from backend.decision_engine import calculate_priority, detect_stock_status, evaluate_bottlenecks
from backend.recommendation_engine import generate_all_recommendations, execute_recommendation
from backend.services import get_kpis, run_what_if_simulation, get_optimized_picking_path, execute_live_demo_scenario

app = Flask(__name__, template_folder='frontend/templates', static_folder='static')
app.secret_key = 'smart_warehouse_ai_secret_key'

# Initialize database if it does not exist (useful for ephemeral environments like Render)
if not os.path.exists(DB_PATH):
    try:
        init_db()
        seed_db()
    except Exception as e:
        app.logger.error(f"Failed to auto-initialize database: {e}")

# --- Middleware/Context Processors ---
@app.context_processor
def inject_globals():
    """
    Injects user role, active recommendations count, and alert counts into all templates.
    """
    user_role = session.get('user_role', 'Warehouse Manager')
    
    # Simple alert counts
    critical_alerts = 0
    warning_alerts = 0
    info_alerts = 0
    recommendations_count = 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Count recommendations
        cursor.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'Pending'")
        recommendations_count = cursor.fetchone()[0]
        
        # 2. Count active exceptions by severity
        cursor.execute("SELECT severity, COUNT(*) FROM exceptions WHERE status != 'Resolved' GROUP BY severity")
        for row in cursor.fetchall():
            sev = row[0]
            cnt = row[1]
            if sev == 'Critical':
                critical_alerts += cnt
            elif sev == 'High':
                warning_alerts += cnt
            elif sev in ['Medium', 'Low']:
                info_alerts += cnt
                
        # 3. Check for low/out-of-stock count alerts
        cursor.execute("SELECT status, COUNT(*) FROM products GROUP BY status")
        for row in cursor.fetchall():
            stat = row[0]
            cnt = row[1]
            if stat == 'Out of Stock':
                critical_alerts += cnt
            elif stat == 'Low Stock':
                warning_alerts += cnt
                
        conn.close()
    except Exception:
        pass
        
    return {
        'current_role': user_role,
        'rec_count': recommendations_count,
        'alert_counts': {
            'critical': critical_alerts,
            'warning': warning_alerts,
            'info': info_alerts,
            'total': critical_alerts + warning_alerts + info_alerts
        }
    }

# --- Login / Role switching ---
@app.route('/set-role', methods=['POST'])
def set_role():
    role = request.form.get('role', 'Warehouse Manager')
    session['user_role'] = role
    return redirect(request.referrer or url_for('dashboard'))

# --- Dashboard Route ---
@app.route('/')
def dashboard():
    conn = get_db_connection()
    
    # Ensure fresh recommendations are generated on every dashboard load
    generate_all_recommendations(conn)
    
    kpis = get_kpis(conn)
    
    cursor = conn.cursor()
    # 1. Priority Orders
    cursor.execute('''
        SELECT id, customer, deadline, priority_level, status 
        FROM orders 
        WHERE status NOT IN ('Dispatched', 'Cancelled')
        ORDER BY priority_score DESC, deadline ASC 
        LIMIT 5
    ''')
    priority_orders = [dict(row) for row in cursor.fetchall()]
    
    # 2. Active Exceptions
    cursor.execute('''
        SELECT id, type, ref_id, severity, detected_time, status 
        FROM exceptions 
        WHERE status != 'Resolved'
        ORDER BY detected_time DESC 
        LIMIT 5
    ''')
    active_exceptions = [dict(row) for row in cursor.fetchall()]
    
    # 3. Bottlenecks
    bottlenecks = evaluate_bottlenecks(conn)[:3]
    
    # 4. Pending Recommendations
    cursor.execute('''
        SELECT id, title, description, priority, type 
        FROM recommendations 
        WHERE status = 'Pending' 
        ORDER BY priority = 'Critical' DESC, priority = 'High' DESC 
        LIMIT 3
    ''')
    pending_recs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('dashboard.html', 
                           kpis=kpis, 
                           priority_orders=priority_orders, 
                           active_exceptions=active_exceptions,
                           bottlenecks=bottlenecks,
                           pending_recs=pending_recs)

# --- Inventory Route ---
@app.route('/inventory')
def inventory():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Search and Filters
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    sort_by = request.args.get('sort_by', 'id').strip()
    
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    
    if q:
        query += " AND (name LIKE ? OR sku LIKE ? OR id LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if category:
        query += " AND category = ?"
        params.append(category)
    if status:
        query += " AND status = ?"
        params.append(status)
        
    # Prevent SQL injections and ensure correct sorting keys
    valid_sorts = ['id', 'name', 'available_qty', 'reorder_level', 'status']
    if sort_by not in valid_sorts:
        sort_by = 'id'
    query += f" ORDER BY {sort_by} ASC"
    
    cursor.execute(query, params)
    products = [dict(row) for row in cursor.fetchall()]
    
    # Categories for filters
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = [r[0] for r in cursor.fetchall()]
    
    conn.close()
    return render_template('inventory.html', products=products, categories=categories, q=q, selected_cat=category, selected_status=status, sort_by=sort_by)

@app.route('/api/inventory/adjust', methods=['POST'])
def adjust_inventory():
    pid = request.form.get('product_id')
    qty = int(request.form.get('quantity', 0))
    reason = request.form.get('reason', 'Manual Adjustment')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT available_qty, reorder_level, name FROM products WHERE id = ?", (pid,))
    prod = cursor.fetchone()
    
    if not prod:
        conn.close()
        return jsonify({'success': False, 'message': 'Product not found'}), 404
        
    prev_qty = prod['available_qty']
    new_qty = max(0, prev_qty + qty) # Never allow negative stock
    
    # Recalculate status
    status = detect_stock_status(new_qty, prod['reorder_level'])
    
    cursor.execute("UPDATE products SET available_qty = ?, status = ? WHERE id = ?", (new_qty, status, pid))
    
    # Audit log
    now = datetime.now().isoformat()
    details = f"Adjusted available stock of {prod['name']} ({pid}). Previous: {prev_qty}, New: {new_qty}."
    cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'Stock Adjustment', ?, ?)", 
                   (now, role, details, reason))
                   
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Inventory adjusted successfully', 'new_qty': new_qty, 'status': status})

@app.route('/api/inventory/damage', methods=['POST'])
def record_damage():
    pid = request.form.get('product_id')
    qty = int(request.form.get('quantity', 0))
    reason = request.form.get('reason', 'Damaged Box')
    role = session.get('user_role', 'Warehouse Manager')
    
    if qty <= 0:
        return jsonify({'success': False, 'message': 'Invalid damaged quantity'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT available_qty, damaged_qty, name FROM products WHERE id = ?", (pid,))
    prod = cursor.fetchone()
    
    if not prod:
        conn.close()
        return jsonify({'success': False, 'message': 'Product not found'}), 404
        
    prev_avail = prod['available_qty']
    prev_damage = prod['damaged_qty']
    
    if prev_avail < qty:
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot flag more damaged stock than currently available'}), 400
        
    new_avail = prev_avail - qty
    new_damage = prev_damage + qty
    
    cursor.execute("UPDATE products SET available_qty = ?, damaged_qty = ?, status = 'Damaged' WHERE id = ?", (new_avail, new_damage, pid))
    
    # Automatically log exception
    now = datetime.now().isoformat()
    ex_id = f"EX-DMG-{now.replace(':', '').replace('-', '').replace('.', '')[-6:]}"
    desc = f"Physical damage reported for {prod['name']} ({pid}). {qty} units moved to damaged buffer."
    rec = f"Accept write-off recommendation to adjust system stock levels and inspect supplier shipment."
    cursor.execute("INSERT INTO exceptions (id, type, ref_id, severity, detected_time, description, recommendation, status) VALUES (?, 'Damaged Item', ?, 'Medium', ?, ?, ?, 'Open')",
                   (ex_id, pid, now, desc, rec))
                   
    # Audit log
    details = f"Moved {qty} units of {prod['name']} ({pid}) to damaged buffer. Available: {new_avail}, Damaged: {new_damage}."
    cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'Stock Damage Log', ?, ?)", 
                   (now, role, details, reason))
                   
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Damaged inventory recorded. Exception raised.'})

# --- Orders Routes ---
@app.route('/orders')
def orders():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    priority = request.args.get('priority', '').strip()
    
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    
    if q:
        query += " AND (id LIKE ? OR customer LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority_level = ?"
        params.append(priority)
        
    query += " ORDER BY deadline ASC"
    cursor.execute(query, params)
    orders_list = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('orders.html', orders=orders_list, q=q, selected_status=status, selected_priority=priority)

@app.route('/orders/<order_id>')
def order_detail(order_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Main order info
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        return "Order not found", 404
        
    # Calculate fresh priority scorecard details
    score, level, reasons = calculate_priority(order['deadline'], order['customer'], order['order_date'])
    
    # 2. Items
    cursor.execute('''
        SELECT oi.*, p.name, p.sku, p.location, p.available_qty, p.status as stock_status
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
    ''', (order_id,))
    items = [dict(row) for row in cursor.fetchall()]
    
    # 3. Exceptions related to this order
    cursor.execute("SELECT * FROM exceptions WHERE ref_id = ? OR ref_id IN (SELECT product_id FROM order_items WHERE order_id = ?)", (order_id, order_id))
    exceptions_list = [dict(row) for row in cursor.fetchall()]
    
    # 4. Picking tasks
    cursor.execute("SELECT * FROM picking_tasks WHERE order_id = ?", (order_id,))
    picking = cursor.fetchone()
    
    # 5. Packing tasks
    cursor.execute("SELECT * FROM packing_tasks WHERE order_id = ?", (order_id,))
    packing = cursor.fetchone()
    
    # 6. Recommendations
    cursor.execute("SELECT * FROM recommendations WHERE ref_id = ? AND status = 'Pending'", (order_id,))
    recommendations_list = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('order_detail.html', 
                           order=dict(order), 
                           items=items, 
                           exceptions=exceptions_list,
                           picking=dict(picking) if picking else None,
                           packing=dict(packing) if packing else None,
                           reasons=reasons,
                           recommendations=recommendations_list)

# --- Picking Route ---
@app.route('/picking')
def picking():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Active picking tasks
    cursor.execute('''
        SELECT pt.*, p.name as picker_name
        FROM picking_tasks pt
        LEFT JOIN pickers p ON pt.picker_id = p.id
        ORDER BY pt.status = 'Delayed' DESC, pt.status = 'Picking' DESC
    ''')
    tasks = [dict(row) for row in cursor.fetchall()]
    
    # Pickers
    cursor.execute("SELECT * FROM pickers")
    pickers = [dict(row) for row in cursor.fetchall()]
    
    # Overloaded zones / Bottlenecks
    bottlenecks = evaluate_bottlenecks(conn)
    
    # Picking path comparison preview (just use O103 as default preview example)
    opt_path = get_optimized_picking_path(conn, 'O103')
    
    conn.close()
    return render_template('picking.html', tasks=tasks, pickers=pickers, bottlenecks=bottlenecks, opt_path=opt_path)

# --- Packing Route ---
@app.route('/packing')
def packing():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT pt.*, o.customer, o.priority_level 
        FROM packing_tasks pt
        JOIN orders o ON pt.order_id = o.id
        ORDER BY o.priority_score DESC
    ''')
    tasks = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('packing.html', tasks=tasks)

@app.route('/api/packing/qc', methods=['POST'])
def submit_qc():
    order_id = request.form.get('order_id')
    status = request.form.get('status') # Pass, Fail
    notes = request.form.get('notes', 'Inspection checklist verified.')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM packing_tasks WHERE order_id = ?", (order_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Packing task not found'}), 404
        
    cursor.execute("UPDATE packing_tasks SET quality_check_status = ?, status = 'Completed' WHERE order_id = ?", (status, order_id))
    
    now = datetime.now().isoformat()
    if status == 'Pass':
        cursor.execute("UPDATE orders SET status = 'Ready for Dispatch' WHERE id = ?", (order_id,))
        details = f"Quality check PASSED for Order {order_id}."
        cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'QC Inspection', ?, 'Pass')", 
                       (now, role, details))
    else:
        cursor.execute("UPDATE orders SET status = 'Quality Check' WHERE id = ?", (order_id,))
        
        # Trigger exception automatically
        ex_id = f"EX-QC-{now.replace(':', '').replace('-', '').replace('.', '')[-6:]}"
        desc = f"Order {order_id} failed packing checklist: {notes}"
        rec = f"Accept routing recommendation to return Order {order_id} to Packing area for corrections."
        cursor.execute("INSERT INTO exceptions (id, type, ref_id, severity, detected_time, description, recommendation, status) VALUES (?, 'Quality Check Failure', ?, 'High', ?, ?, ?, 'Open')",
                       (ex_id, order_id, now, desc, rec))
                       
        details = f"Quality check FAILED for Order {order_id}."
        cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'QC Inspection', ?, ?)", 
                       (now, role, details, notes))
                       
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'QC status saved as {status}.'})

# --- Exceptions Route ---
@app.route('/exceptions')
def exceptions():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    severity = request.args.get('severity', '').strip()
    
    query = "SELECT * FROM exceptions WHERE 1=1"
    params = []
    
    if q:
        query += " AND (id LIKE ? OR ref_id LIKE ? OR description LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if status:
        query += " AND status = ?"
        params.append(status)
    if severity:
        query += " AND severity = ?"
        params.append(severity)
        
    query += " ORDER BY detected_time DESC"
    cursor.execute(query, params)
    exceptions_list = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('exceptions.html', exceptions=exceptions_list, q=q, selected_status=status, selected_severity=severity)

@app.route('/api/exceptions/resolve', methods=['POST'])
def resolve_exception():
    ex_id = request.form.get('exception_id')
    notes = request.form.get('notes', 'Resolved manually.')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM exceptions WHERE id = ?", (ex_id,))
    ex = cursor.fetchone()
    if not ex:
        conn.close()
        return jsonify({'success': False, 'message': 'Exception not found'}), 404
        
    cursor.execute("UPDATE exceptions SET status = 'Resolved', resolution_notes = ? WHERE id = ?", (notes, ex_id))
    
    # Create audit log
    now = datetime.now().isoformat()
    details = f"Exception {ex_id} marked as Resolved."
    cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'Exception Resolution', ?, ?)", 
                   (now, role, details, notes))
                   
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Exception {ex_id} resolved successfully.'})

# --- Dispatch Route ---
@app.route('/dispatch')
def dispatch():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Orders ready for dispatch
    cursor.execute("SELECT * FROM orders WHERE status = 'Ready for Dispatch'")
    ready_orders = [dict(row) for row in cursor.fetchall()]
    
    # Orders dispatched
    cursor.execute("SELECT * FROM orders WHERE status = 'Dispatched' ORDER BY deadline DESC LIMIT 10")
    dispatched_orders = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('dispatch.html', ready_orders=ready_orders, dispatched_orders=dispatched_orders)

@app.route('/api/dispatch', methods=['POST'])
def ship_order():
    order_id = request.form.get('order_id')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        return jsonify({'success': False, 'message': 'Order not found'}), 404
        
    if order['status'] != 'Ready for Dispatch':
        conn.close()
        return jsonify({'success': False, 'message': 'Order is not in Ready for Dispatch status'}), 400
        
    cursor.execute("UPDATE orders SET status = 'Dispatched' WHERE id = ?", (order_id,))
    
    # Update quantities
    cursor.execute("SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,))
    items = cursor.fetchall()
    
    for item in items:
        pid = item['product_id']
        qty = item['quantity']
        
        # Deduct reserved qty
        cursor.execute("UPDATE products SET reserved_qty = MAX(0, reserved_qty - ?) WHERE id = ?", (qty, pid))
        
    # Audit log
    now = datetime.now().isoformat()
    details = f"Shipped and dispatched Order {order_id}. Handed over to courier."
    cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'Order Dispatch', ?, 'Ready carrier pickup')", 
                   (now, role, details))
                   
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Order {order_id} successfully dispatched.'})

# --- Recommendations Route ---
@app.route('/recommendations')
def recommendations():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Scan/generate fresh
    generate_all_recommendations(conn)
    
    cursor.execute("SELECT * FROM recommendations WHERE status = 'Pending' ORDER BY priority = 'Critical' DESC, priority = 'High' DESC")
    pending = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM recommendations WHERE status != 'Pending' ORDER BY id DESC LIMIT 10")
    history = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('recommendations.html', pending=pending, history=history)

@app.route('/api/recommendations/accept', methods=['POST'])
def accept_rec():
    rec_id = request.form.get('recommendation_id')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    success, message = execute_recommendation(conn, rec_id, role)
    conn.close()
    
    return jsonify({'success': success, 'message': message})

@app.route('/api/recommendations/reject', methods=['POST'])
def reject_rec():
    rec_id = request.form.get('recommendation_id')
    role = session.get('user_role', 'Warehouse Manager')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE recommendations SET status = 'Rejected' WHERE id = ?", (rec_id,))
    
    # Audit log
    now = datetime.now().isoformat()
    details = f"Recommendation {rec_id} was rejected by {role}."
    cursor.execute("INSERT INTO audit_logs (timestamp, user_role, action, details, reason) VALUES (?, ?, 'Recommendation Rejection', ?, 'Manual reject')", 
                   (now, role, details))
                   
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Recommendation rejected.'})

# --- Simulator Route ---
@app.route('/simulator')
def simulator():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, available_qty FROM products WHERE status != 'Out of Stock'")
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('simulator.html', products=products)

@app.route('/api/simulator/run', methods=['POST'])
def run_simulation():
    new_orders = int(request.form.get('new_orders', 0))
    stockout_pid = request.form.get('stockout_product', '')
    picker_reduction = int(request.form.get('picker_reduction', 0))
    damaged_qty = int(request.form.get('damaged_qty', 0))
    supplier_delay = int(request.form.get('supplier_delay', 0))
    
    conn = get_db_connection()
    results = run_what_if_simulation(conn, new_orders, stockout_pid, picker_reduction, damaged_qty, supplier_delay)
    conn.close()
    
    return jsonify(results)

# --- Analytics Route ---
@app.route('/analytics')
def analytics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch data points for Chart.js
    # Category stock levels
    cursor.execute("SELECT category, SUM(available_qty) FROM products GROUP BY category")
    cat_stock = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Exception categories count
    cursor.execute("SELECT type, COUNT(*) FROM exceptions GROUP BY type")
    ex_breakdown = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Order Status counts
    cursor.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
    ord_stats = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Historical dispatch rate: get last 7 days count
    # Since we are mock database, we will provide a standard response
    days = [(datetime.now() - timedelta(days=i)).strftime('%m/%d') for i in range(6, -1, -1)]
    dispatches = [random.randint(15, 25) for _ in range(7)]
    
    conn.close()
    return render_template('analytics.html', 
                           cat_stock_labels=list(cat_stock.keys()),
                           cat_stock_values=list(cat_stock.values()),
                           ex_breakdown_labels=list(ex_breakdown.keys()),
                           ex_breakdown_values=list(ex_breakdown.values()),
                           ord_stats_labels=list(ord_stats.keys()),
                           ord_stats_values=list(ord_stats.values()),
                           days=days,
                           dispatches=dispatches)

# --- Audit Logs Route ---
@app.route('/audit-logs')
def audit_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC")
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('audit_logs.html', logs=logs)

# --- Live Demo Route ---
@app.route('/api/demo/run', methods=['POST'])
def trigger_demo():
    conn = get_db_connection()
    steps = execute_live_demo_scenario(conn)
    conn.close()
    return jsonify({'success': True, 'steps': steps})

# --- Reset Database API ---
@app.route('/api/reset-db', methods=['POST'])
def reset_database():
    try:
        init_db()
        seed_db()
        return jsonify({'success': True, 'message': 'Database re-seeded successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
