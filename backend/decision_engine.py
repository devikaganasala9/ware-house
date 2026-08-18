import json
from datetime import datetime

def calculate_priority(deadline_str, customer_name, order_date_str, delay_risk_factor=False):
    """
    Calculates order priority score and level.
    Returns: (priority_score, priority_level, reasons_list)
    """
    now = datetime.now()
    
    # 1. Parse dates and calculate age & deadline hours
    try:
        deadline = datetime.fromisoformat(deadline_str)
        deadline_hours = (deadline - now).total_seconds() / 3600.0
    except Exception:
        deadline_hours = 24.0 # default to 24 hours if parsing fails
        
    try:
        order_date = datetime.fromisoformat(order_date_str)
        order_age_hours = (now - order_date).total_seconds() / 3600.0
    except Exception:
        order_age_hours = 0.0

    reasons = []
    
    # -- A. Deadline Urgency (Max 40 points) --
    deadline_points = 0
    if deadline_hours <= 0:
        deadline_points = 40
        reasons.append(f"Order is past delivery deadline by {-deadline_hours:.1f} hours (+40)")
    elif deadline_hours <= 2:
        deadline_points = 40
        reasons.append(f"Extremely urgent delivery deadline in {deadline_hours:.1f} hours (+40)")
    elif deadline_hours <= 6:
        deadline_points = 35
        reasons.append(f"Urgent delivery deadline in {deadline_hours:.1f} hours (+35)")
    elif deadline_hours <= 12:
        deadline_points = 25
        reasons.append(f"Delivery deadline is in {deadline_hours:.1f} hours (+25)")
    elif deadline_hours <= 24:
        deadline_points = 15
        reasons.append(f"Delivery deadline within 24 hours (+15)")
    elif deadline_hours <= 48:
        deadline_points = 5
        reasons.append(f"Delivery deadline within 48 hours (+5)")
    else:
        deadline_points = 0
        reasons.append("Delivery deadline is relaxed (>48 hours) (+0)")

    # -- B. Customer Importance (Max 25 points) --
    # Map customer importance based on simple mock mapping or VIP flags
    customer_points = 10 # Regular default
    cust_lower = customer_name.lower()
    
    if any(vip in cust_lower for vip in ['corp', 'solutions', 'enterprises', 'partners']):
        customer_points = 25
        reasons.append(f"High-priority corporate account: {customer_name} (+25)")
    elif any(reg in cust_lower for reg in ['global', 'retailers', 'supply']):
        customer_points = 15
        reasons.append(f"Regular business account: {customer_name} (+15)")
    else:
        customer_points = 5
        reasons.append(f"Standard consumer account: {customer_name} (+5)")

    # -- C. Delay Risk (Max 20 points) --
    delay_points = 0
    if delay_risk_factor:
        delay_points = 20
        reasons.append("Fulfillment delay risk detected (e.g. picker delayed or zone bottleneck) (+20)")
    else:
        reasons.append("No active zone bottlenecks affecting order items (+0)")

    # -- D. Order Age (Max 15 points) --
    age_points = 0
    if order_age_hours > 48:
        age_points = 15
        reasons.append(f"Order has been pending for over 48 hours ({order_age_hours:.1f} hrs) (+15)")
    elif order_age_hours > 24:
        age_points = 10
        reasons.append(f"Order has been pending for over 24 hours ({order_age_hours:.1f} hrs) (+10)")
    elif order_age_hours > 6:
        age_points = 5
        reasons.append(f"Order has been pending for over 6 hours ({order_age_hours:.1f} hrs) (+5)")
    else:
        age_points = 0
        reasons.append(f"Order is recently created ({order_age_hours:.1f} hrs) (+0)")

    # Sum score and determine level
    priority_score = min(deadline_points + customer_points + delay_points + age_points, 100)
    
    if priority_score >= 70:
        priority_level = 'Critical'
    elif priority_score >= 50:
        priority_level = 'High'
    elif priority_score >= 30:
        priority_level = 'Medium'
    else:
        priority_level = 'Low'
        
    return priority_score, priority_level, reasons

def detect_stock_status(available_qty, reorder_level, damaged_qty=0):
    """
    Determine stock status classification.
    """
    if damaged_qty > 0 and available_qty <= 0:
        return 'Damaged'
    if available_qty == 0:
        return 'Out of Stock'
    if available_qty <= reorder_level:
        return 'Low Stock'
    if available_qty > 100: # Simple rule for overstock
        return 'Overstocked'
    return 'Healthy'

def evaluate_bottlenecks(db_conn):
    """
    Scans picking tasks, packing tasks, and zones to find active bottlenecks.
    Returns: A list of dicts describing each bottleneck.
    """
    cursor = db_conn.cursor()
    bottlenecks = []

    # 1. Check Zones based on active picking tasks
    # Select count of active/pending tasks and delayed tasks grouped by zone
    cursor.execute('''
        SELECT zone, 
               COUNT(*) as total_tasks,
               SUM(CASE WHEN status = 'Picking' THEN 1 ELSE 0 END) as picking_tasks,
               SUM(CASE WHEN status = 'Waiting' THEN 1 ELSE 0 END) as waiting_tasks,
               SUM(CASE WHEN status = 'Delayed' THEN 1 ELSE 0 END) as delayed_tasks
        FROM picking_tasks
        WHERE status != 'Completed'
        GROUP BY zone
    ''')
    zone_stats = cursor.fetchall()
    
    for row in zone_stats:
        zone = row['zone']
        total = row['total_tasks']
        delayed = row['delayed_tasks'] or 0
        waiting = row['waiting_tasks'] or 0
        
        # Determine bottleneck severity and description
        if total > 4 or delayed > 0:
            severity = 'Critical' if (delayed > 1 or total > 6) else 'Warning'
            
            # Count pickers in this zone
            cursor.execute("SELECT COUNT(*) FROM pickers WHERE zone = ?", (zone,))
            picker_count = cursor.fetchone()[0]
            
            reasons = []
            if delayed > 0:
                reasons.append(f"{delayed} active picking task(s) flagged as DELAYED")
            if total > 4:
                reasons.append(f"Queue size is {total} pending tasks (High Volume)")
            if picker_count <= 1:
                reasons.append(f"Under-staffed: Only {picker_count} picker assigned to this zone")

            desc = f"{zone} is experiencing a picking slowdown. {', '.join(reasons)}."
            rec = f"Assign an additional picker to {zone} immediately to expedite fulfillment."
            
            bottlenecks.append({
                'category': 'Picking Zone',
                'target': zone,
                'severity': severity,
                'description': desc,
                'recommendation': rec,
                'metrics': {
                    'backlog_count': total,
                    'delayed_count': delayed,
                    'active_pickers': picker_count
                }
            })

    # 2. Check Packing Queue bottleneck
    cursor.execute('''
        SELECT COUNT(*) as total_packing,
               SUM(CASE WHEN status = 'Waiting' THEN 1 ELSE 0 END) as waiting_packing,
               SUM(CASE WHEN status = 'Packing' THEN 1 ELSE 0 END) as active_packing
        FROM packing_tasks
        WHERE status != 'Completed'
    ''')
    pack_stats = cursor.fetchone()
    if pack_stats and pack_stats['total_packing'] > 5:
        waiting = pack_stats['waiting_packing'] or 0
        desc = f"Packing department queue is backlog-congested. {waiting} orders are waiting for pack stations."
        rec = "Reassign an operator or warehouse picker to packing station to assist with packaging and taping."
        bottlenecks.append({
            'category': 'Packing Queue',
            'target': 'Packing Department',
            'severity': 'Warning',
            'description': desc,
            'recommendation': rec,
            'metrics': {
                'backlog_count': pack_stats['total_packing'],
                'waiting_count': waiting
            }
        })
        
    return bottlenecks
