import os
import sqlite3
import random
from datetime import datetime, timedelta

if os.environ.get('VERCEL') or 'VERCEL' in os.environ:
    DB_PATH = '/tmp/warehouse.db'
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), 'warehouse.db')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Drop existing tables to ensure clean rebuild
    tables = [
        'audit_logs', 'recommendations', 'exceptions', 'packing_tasks', 
        'picking_tasks', 'pickers', 'order_items', 'orders', 'products'
    ]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")

    # Create Products table
    cursor.execute('''
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL,
            zone TEXT NOT NULL,
            location TEXT NOT NULL,
            available_qty INTEGER NOT NULL DEFAULT 0,
            reserved_qty INTEGER NOT NULL DEFAULT 0,
            damaged_qty INTEGER NOT NULL DEFAULT 0,
            reorder_level INTEGER NOT NULL DEFAULT 10,
            reorder_qty INTEGER NOT NULL DEFAULT 50,
            supplier TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Healthy'
        )
    ''')

    # Create Orders table
    cursor.execute('''
        CREATE TABLE orders (
            id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            order_date TEXT NOT NULL,
            deadline TEXT NOT NULL,
            priority_score INTEGER NOT NULL DEFAULT 0,
            priority_level TEXT NOT NULL DEFAULT 'Low',
            status TEXT NOT NULL DEFAULT 'Created',
            risk_level TEXT NOT NULL DEFAULT 'Low',
            payment_status TEXT NOT NULL DEFAULT 'Pending'
        )
    ''')

    # Create Order Items table
    cursor.execute('''
        CREATE TABLE order_items (
            order_id TEXT,
            product_id TEXT,
            quantity INTEGER NOT NULL,
            allocated_qty INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (order_id, product_id),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # Create Pickers table
    cursor.execute('''
        CREATE TABLE pickers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            zone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Idle',
            active_order_id TEXT,
            FOREIGN KEY (active_order_id) REFERENCES orders(id)
        )
    ''')

    # Create Picking Tasks table
    cursor.execute('''
        CREATE TABLE picking_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            picker_id TEXT,
            order_id TEXT,
            zone TEXT NOT NULL,
            items_summary TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Waiting',
            start_time TEXT,
            est_completion TEXT,
            act_completion TEXT,
            FOREIGN KEY (picker_id) REFERENCES pickers(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')

    # Create Packing Tasks table
    cursor.execute('''
        CREATE TABLE packing_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            items_summary TEXT NOT NULL,
            package_type TEXT NOT NULL DEFAULT 'Standard Box',
            status TEXT NOT NULL DEFAULT 'Waiting',
            assigned_worker TEXT,
            packing_time INTEGER, -- minutes
            quality_check_status TEXT NOT NULL DEFAULT 'Pending',
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    ''')

    # Create Exceptions table
    cursor.execute('''
        CREATE TABLE exceptions (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            ref_id TEXT NOT NULL, -- order_id or product_id
            severity TEXT NOT NULL,
            detected_time TEXT NOT NULL,
            description TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            resolution_notes TEXT
        )
    ''')

    # Create Recommendations table
    cursor.execute('''
        CREATE TABLE recommendations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            type TEXT NOT NULL, -- Reorder, Allocation, Worker Reassignment, Exception Resolution, Bottleneck Mitigation
            ref_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            impact TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            payload TEXT -- JSON string for automatic execution actions
        )
    ''')

    # Create Audit Logs table
    cursor.execute('''
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_role TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            reason TEXT NOT NULL
        )
    ''''')

    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.now()

    # --- 1. SEED PRODUCTS (50 products across categories and 10 zones A-J) ---
    categories = ['Electronics', 'Accessories', 'Apparel', 'Home Goods', 'Office Supplies']
    suppliers = ['Global Tech Inc', 'Prime Logistics', 'Starlight Wholesale', 'Apex Goods Co', 'Nova Distributors']
    zones = ['Zone A', 'Zone B', 'Zone C', 'Zone D', 'Zone E', 'Zone F', 'Zone G', 'Zone H', 'Zone I', 'Zone J']

    products_data = []
    # Seed 50 products
    for i in range(1, 51):
        pid = f"P{100+i}"
        cat = categories[i % len(categories)]
        supplier = suppliers[i % len(suppliers)]
        zone = zones[i % len(zones)]
        loc = f"{zone[5:]}-{random.randint(1, 15)}-{random.choice(['A', 'B', 'C', 'D'])}"
        
        # Base product configurations
        name = f"Warehouse Item {pid}"
        if cat == 'Electronics':
            names = ['Wireless Mouse', 'Mechanical Keyboard', '1080p Monitor', 'USB-C Docking Station', 'Bluetooth Headset', 'Smart Watch', 'Dual Charger', 'Wireless Earbuds', 'External SSD', 'HD Webcam']
            name = names[i % len(names)]
        elif cat == 'Accessories':
            names = ['Leather Wallet', 'Travel Backpack', 'Polarized Sunglasses', 'Laptop Sleeve', 'Phone Stand', 'Cable Organizer', 'Key Organizer', 'Water Bottle', 'Umbrella', 'Gym Bag']
            name = names[i % len(names)]
        elif cat == 'Apparel':
            names = ['Cotton T-Shirt', 'Denim Jacket', 'Athletic Socks', 'Running Shoes', 'Winter Beanie', 'Fleece Hoodie', 'Casual Belt', 'Leather Gloves', 'Sports Shorts', 'Rain Coat']
            name = names[i % len(names)]
        elif cat == 'Home Goods':
            names = ['LED Desk Lamp', 'Ceramic Mug', 'Scented Candle', 'Throw Pillow', 'Desk Mat', 'Wall Clock', 'Storage Organizer', 'Humidifier', 'Smart Bulb', 'Vacuum Flask']
            name = names[i % len(names)]
        elif cat == 'Office Supplies':
            names = ['Gel Pen Pack', 'Notebook Set', 'Sticky Notes Bundle', 'Dry Erase Board', 'Paper Shredder', 'Ergonomic Stapler', 'Desk Organizer Shelf', 'Filing Folders', 'Heavy Duty Scissors', 'Calculator']
            name = names[i % len(names)]

        sku = f"SKU-{cat[:3].upper()}-{1000+i}"
        
        # Quantities
        avail = random.randint(15, 80)
        reserved = 0
        damaged = 0
        reorder_level = random.choice([8, 10, 15])
        reorder_qty = random.choice([30, 40, 50])
        status = 'Healthy'

        # Set up specific product edge cases
        if pid == 'P101': # Wireless Mouse - Low Stock
            name = 'Wireless Mouse'
            avail = 7
            reorder_level = 10
            status = 'Low Stock'
        elif pid == 'P102': # Mechanical Keyboard - Out of Stock (Edge Case)
            name = 'Mechanical Keyboard'
            avail = 0
            reorder_level = 10
            status = 'Out of Stock'
        elif pid == 'P103': # 1080p Monitor - Damaged stock
            name = '1080p Monitor'
            avail = 12
            damaged = 3
            status = 'Damaged'
        elif pid == 'P104': # USB-C Docking Station - Overstocked
            name = 'USB-C Docking Station'
            avail = 120
            reorder_level = 15
            status = 'Overstocked'
        elif pid == 'P105': # Bluetooth Headset - Missing stock (will trigger exception)
            name = 'Bluetooth Headset'
            avail = 15
            status = 'Healthy'

        products_data.append((pid, name, cat, sku, zone, loc, avail, reserved, damaged, reorder_level, reorder_qty, supplier, status))

    cursor.executemany('''
        INSERT INTO products (id, name, category, sku, zone, location, available_qty, reserved_qty, damaged_qty, reorder_level, reorder_qty, supplier, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', products_data)


    # --- 2. SEED WORKERS (10 Pickers & 5 Packers) ---
    pickers_data = [
        ('PK101', 'John Doe', 'Zone A', 'Picking', 'O103'),
        ('PK102', 'Sarah Smith', 'Zone B', 'Delayed', 'O104'),
        ('PK103', 'Mike Johnson', 'Zone C', 'Idle', None),
        ('PK104', 'Emily Davis', 'Zone D', 'Picking', 'O108'),
        ('PK105', 'Robert Wilson', 'Zone E', 'Idle', None),
        ('PK106', 'Jessica Taylor', 'Zone F', 'Idle', None),
        ('PK107', 'David Anderson', 'Zone G', 'Idle', None),
        ('PK108', 'Amanda Thomas', 'Zone H', 'Idle', None),
        ('PK109', 'Daniel Jackson', 'Zone I', 'Idle', None),
        ('PK110', 'Ashley White', 'Zone J', 'Idle', None)
    ]
    cursor.executemany('INSERT INTO pickers (id, name, zone, status, active_order_id) VALUES (?, ?, ?, ?, ?)', pickers_data)

    packers_names = ['Chris Brown', 'Patricia Miller', 'James Wilson', 'Linda Jones', 'Michael Green']


    # --- 3. SEED ORDERS & ORDER ITEMS (30 orders with realistic status distribution and deadlines) ---
    # We will seed 30 orders.
    # Standard customer types
    customers = ['TechCorp Solutions', 'E-Shop Global', 'Omni Retailers', 'Axiom Supply', 'LogiTrans Group', 'Nova Retail', 'Apex Enterprises', 'Alpha Partners']
    
    orders_data = []
    order_items_data = []

    for i in range(1, 31):
        oid = f"O{100+i}"
        cust = customers[i % len(customers)]
        
        # Dates
        order_date = (now - timedelta(days=random.randint(1, 4), hours=random.randint(1, 23))).isoformat()
        
        # Deadlines and Priorities
        # Specific edge cases first
        if i == 1: # Order O101 - Urgent critical order with shortage (competing for P101)
            deadline = (now + timedelta(hours=3)).isoformat()
            priority_score = 85
            priority_level = 'Critical'
            status = 'Pending Allocation'
            risk_level = 'High'
        elif i == 2: # Order O102 - Lower priority order holding stock of P101
            deadline = (now + timedelta(days=2)).isoformat()
            priority_score = 35
            priority_level = 'Medium'
            status = 'Allocated'
            risk_level = 'Low'
        elif i == 3: # Order O103 - Currently picking in Zone A
            deadline = (now + timedelta(hours=5)).isoformat()
            priority_score = 75
            priority_level = 'Critical'
            status = 'Picking'
            risk_level = 'Medium'
        elif i == 4: # Order O104 - Currently picking in Zone B, delayed worker
            deadline = (now + timedelta(hours=1)).isoformat()
            priority_score = 90
            priority_level = 'Critical'
            status = 'Picking'
            risk_level = 'Critical'
        elif i == 5: # Order O105 - QC Failure
            deadline = (now + timedelta(hours=8)).isoformat()
            priority_score = 65
            priority_level = 'High'
            status = 'Quality Check'
            risk_level = 'High'
        elif i == 6: # Order O106 - Ready for Dispatch but Delayed
            deadline = (now - timedelta(hours=2)).isoformat() # Past deadline!
            priority_score = 95
            priority_level = 'Critical'
            status = 'Ready for Dispatch'
            risk_level = 'Critical'
        else:
            # Random distribution for the rest of 30 orders
            hours_to_deadline = random.choice([4, 8, 12, 24, 48, 72])
            deadline = (now + timedelta(hours=hours_to_deadline)).isoformat()
            priority_score = random.randint(10, 75)
            
            if priority_score >= 70:
                priority_level = 'Critical'
            elif priority_score >= 50:
                priority_level = 'High'
            elif priority_score >= 30:
                priority_level = 'Medium'
            else:
                priority_level = 'Low'
                
            # Random statuses: Created, Pending Allocation, Allocated, Picking, Packed, Quality Check, Ready for Dispatch, Dispatched, Cancelled
            status_opts = ['Created', 'Pending Allocation', 'Allocated', 'Picking', 'Packed', 'Ready for Dispatch', 'Dispatched']
            status = random.choices(status_opts, weights=[10, 20, 20, 20, 10, 10, 10])[0]
            
            risk_level = 'Low'
            if priority_level in ['Critical', 'High'] and hours_to_deadline <= 8:
                risk_level = 'High'
            elif hours_to_deadline <= 24:
                risk_level = 'Medium'

        payment_status = 'Paid' if random.random() > 0.1 else 'Pending'

        orders_data.append((oid, cust, order_date, deadline, priority_score, priority_level, status, risk_level, payment_status))

        # Add items to order
        # Ensure O101 and O102 require P101 (Wireless Mouse) to show competing allocation!
        if oid == 'O101':
            # Needs 10 units of P101
            order_items_data.append((oid, 'P101', 10, 0)) # Available is 7, allocated is 0 initially.
            # And also needs 2 units of P104
            order_items_data.append((oid, 'P104', 2, 2))
        elif oid == 'O102':
            # Needs 5 units of P101
            order_items_data.append((oid, 'P101', 5, 5)) # Allocated all 5 units from available 7!
        elif oid == 'O103':
            # Needs 2 units of P103, 1 unit of P106
            order_items_data.append((oid, 'P103', 2, 2))
            order_items_data.append((oid, 'P106', 1, 1))
        elif oid == 'O104':
            # Needs 1 unit of P108
            order_items_data.append((oid, 'P108', 1, 1))
        elif oid == 'O105':
            # Needs 3 units of P110
            order_items_data.append((oid, 'P110', 3, 3))
        elif oid == 'O106':
            # Needs 4 units of P112
            order_items_data.append((oid, 'P112', 4, 4))
        else:
            # General order items (1 to 3 items)
            item_count = random.randint(1, 3)
            sampled_prod_ids = random.sample([f"P{100+k}" for k in range(1, 51)], item_count)
            for prod_id in sampled_prod_ids:
                # Exclude P101 for simplicity of reallocation demonstration
                if prod_id == 'P101' and oid != 'O101' and oid != 'O102':
                    prod_id = 'P105'
                qty = random.randint(1, 5)
                # If order is dispatched, allocated = qty.
                # If allocated, allocated = qty.
                # If Created/Pending, allocated = 0 or partial.
                allocated = 0
                if status in ['Allocated', 'Picking', 'Packed', 'Ready for Dispatch', 'Dispatched']:
                    allocated = qty
                order_items_data.append((oid, prod_id, qty, allocated))

    cursor.executemany('''
        INSERT INTO orders (id, customer, order_date, deadline, priority_score, priority_level, status, risk_level, payment_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', orders_data)

    cursor.executemany('''
        INSERT INTO order_items (order_id, product_id, quantity, allocated_qty)
        VALUES (?, ?, ?, ?)
    ''', order_items_data)


    # Sync reserved_qty in products table based on allocated order items (where orders are not yet dispatched)
    cursor.execute('''
        SELECT product_id, SUM(allocated_qty) as total_reserved
        FROM order_items
        JOIN orders ON order_items.order_id = orders.id
        WHERE orders.status NOT IN ('Dispatched', 'Cancelled')
        GROUP BY product_id
    ''')
    for row in cursor.fetchall():
        cursor.execute('''
            UPDATE products 
            SET reserved_qty = ? 
            WHERE id = ?
        ''', (row['total_reserved'], row['product_id']))


    # --- 4. SEED PICKING TASKS (for orders in Picking status) ---
    # O103 in Zone A (PK101)
    # O104 in Zone B (PK102)
    # Plus a couple of others
    picking_tasks_data = [
        ('PK101', 'O103', 'Zone A', 'P103 x2, P106 x1', 3, 'Picking', (now - timedelta(minutes=45)).isoformat(), (now + timedelta(minutes=15)).isoformat(), None),
        ('PK102', 'O104', 'Zone B', 'P108 x1', 1, 'Delayed', (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=1)).isoformat(), None),
        ('PK104', 'O108', 'Zone D', 'P115 x3', 3, 'Picking', (now - timedelta(minutes=10)).isoformat(), (now + timedelta(minutes=20)).isoformat(), None)
    ]
    # Add waiting tasks for allocated orders
    cursor.execute("SELECT id FROM orders WHERE status = 'Allocated'")
    allocated_orders = [r[0] for r in cursor.fetchall()]
    for a_oid in allocated_orders[:4]:
        # Get items details
        cursor.execute("SELECT product_id, quantity FROM order_items WHERE order_id = ?", (a_oid,))
        items = cursor.fetchall()
        items_str = ", ".join([f"{r[0]} x{r[1]}" for r in items])
        qty = sum([r[1] for r in items])
        # Find zone from first product
        cursor.execute("SELECT zone FROM products WHERE id = ?", (items[0][0],))
        zone = cursor.fetchone()[0]
        picking_tasks_data.append((None, a_oid, zone, items_str, qty, 'Waiting', None, None, None))

    cursor.executemany('''
        INSERT INTO picking_tasks (picker_id, order_id, zone, items_summary, quantity, status, start_time, est_completion, act_completion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', picking_tasks_data)


    # --- 5. SEED PACKING TASKS (for orders in Packed, QC, or Ready) ---
    # O105 (QC)
    # O106 (Ready)
    # We will seed packing tasks for these and other packed orders
    packing_tasks_data = [
        ('O105', 'P110 x3', 'Standard Box', 'Quality Check', packers_names[0], 12, 'Pending'),
        ('O106', 'P112 x4', 'Heavy Duty Box', 'Completed', packers_names[1], 15, 'Pass')
    ]
    cursor.execute("SELECT id FROM orders WHERE status = 'Packed'")
    packed_orders = [r[0] for r in cursor.fetchall()]
    for p_oid in packed_orders:
        cursor.execute("SELECT product_id, quantity FROM order_items WHERE order_id = ?", (p_oid,))
        items = cursor.fetchall()
        items_str = ", ".join([f"{r[0]} x{r[1]}" for r in items])
        packing_tasks_data.append((p_oid, items_str, 'Standard Box', 'Waiting', None, None, 'Pending'))

    cursor.executemany('''
        INSERT INTO packing_tasks (order_id, items_summary, package_type, status, assigned_worker, packing_time, quality_check_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', packing_tasks_data)


    # --- 6. SEED EXCEPTIONS (At least 20 exceptions) ---
    # Predefined critical exceptions
    exceptions_data = [
        ('EX101', 'Damaged Item', 'P103', 'Medium', (now - timedelta(hours=10)).isoformat(), '3 units of 1080p Monitor detected as physically damaged during stock take.', 'Create supplier damage log and adjust available quantity down by 3.', 'Open', None),
        ('EX102', 'Missing Item', 'P105', 'High', (now - timedelta(hours=8)).isoformat(), '2 units of Bluetooth Headset missing from location E-4-C.', 'Perform cycle count in Zone E. Trigger micro-reorder if stock discrepancy is real.', 'Investigating', None),
        ('EX103', 'Insufficient Stock', 'O101', 'Critical', (now - timedelta(hours=2)).isoformat(), 'Order O101 (Critical Priority) requires 10 units of P101 but available stock is only 7 units.', 'Reallocate 5 units of P101 currently reserved for lower-priority Order O102.', 'Action Required', None),
        ('EX104', 'Picking Delay', 'O104', 'High', (now - timedelta(hours=1)).isoformat(), 'Order O104 picking time exceeded estimate by 60 mins in Zone B due to worker delay.', 'Escalate order, assign picker PK103 to assist, or re-route other items.', 'Open', None),
        ('EX105', 'Quality Check Failure', 'O105', 'High', (now - timedelta(minutes=30)).isoformat(), 'Order O105 failed packaging inspection: Wrong quantity of items (2 packed instead of 3).', 'Return package to packing station for correction.', 'Action Required', None),
        ('EX106', 'Dispatch Delay', 'O106', 'Critical', (now - timedelta(hours=3)).isoformat(), 'Order O106 is ready for dispatch but delivery vehicle allocation is delayed.', 'Contact carrier Apex Logistics or reassign to next scheduled carrier.', 'Open', None)
    ]

    # Fill up to 20 exceptions with realistic values
    exception_types = [
        ('Damaged Item', 'Product damaged in zone shelf', 'Medium', 'Adjust stock'),
        ('Missing Item', 'Item not found in specified location', 'High', 'Run cycle count'),
        ('Wrong Item', 'Picker selected incorrect color/model', 'Medium', 'Swap items'),
        ('Insufficient Stock', 'Order item blocked by stockout', 'High', 'Procure or reallocate'),
        ('Picking Delay', 'Order picking delayed due to zone traffic', 'Low', 'Wait or redirect'),
        ('Packing Delay', 'Worker packing bottleneck', 'Low', 'Assign support'),
        ('Quality Check Failure', 'Product minor scratch or packaging dent', 'Medium', 'Repack item'),
        ('Dispatch Delay', 'Carrier pickup missed slot', 'Medium', 'Reschedule carrier')
    ]

    for j in range(7, 21):
        ex_id = f"EX{100+j}"
        extype, desc_tpl, sev, rec_tpl = exception_types[j % len(exception_types)]
        
        # pick a random order or product
        if extype in ['Damaged Item', 'Missing Item']:
            ref = f"P{100 + random.randint(10, 50)}"
            desc = f"{desc_tpl} {ref}."
            rec = f"{rec_tpl} and verify balance."
        else:
            ref = f"O{100 + random.randint(10, 30)}"
            desc = f"{desc_tpl} for order {ref}."
            rec = f"{rec_tpl} immediately."

        time_str = (now - timedelta(hours=random.randint(4, 48))).isoformat()
        status = random.choice(['Open', 'Investigating', 'Resolved'])
        res_notes = 'Issue investigated and resolved.' if status == 'Resolved' else None
        
        exceptions_data.append((ex_id, extype, ref, sev, time_str, desc, rec, status, res_notes))

    cursor.executemany('''
        INSERT INTO exceptions (id, type, ref_id, severity, detected_time, description, recommendation, status, resolution_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', exceptions_data)


    # --- 7. SEED RECOMMENDATIONS ---
    # Pre-populate recommendations
    recommendations_data = [
        (
            'REC101', 
            'Reallocate Stock for Urgent Order O101', 
            'Allocate 5 units of P101 (Wireless Mouse) from lower priority Order O102 to Critical Order O101.',
            'Allocation',
            'O101',
            'Order O101 is Critical and has an active deadline in 3 hours. Order O102 is Medium priority and is not scheduled for picking yet.',
            'Order O101 can be fully allocated and picked immediately. Order O102 allocation status will drop to Partially Allocated.',
            'Critical',
            'Pending',
            '{"action": "reallocate_stock", "from_order": "O102", "to_order": "O101", "product_id": "P101", "quantity": 5}'
        ),
        (
            'REC102',
            'Reorder Low Stock: Wireless Mouse (P101)',
            'Generate replenishment purchase order for 50 units of Wireless Mouse (P101).',
            'Reorder',
            'P101',
            'Available stock (7 units) has fallen below reorder level (10 units). Currently 5 units are reserved.',
            'Replenish warehouse safety stock and prevent future stockouts. Expected delivery: 3 days.',
            'High',
            'Pending',
            '{"action": "reorder_product", "product_id": "P101", "quantity": 50}'
        ),
        (
            'REC103',
            'Reorder Out of Stock: Mechanical Keyboard (P102)',
            'Generate urgent replenishment purchase order for 40 units of Mechanical Keyboard (P102).',
            'Reorder',
            'P102',
            'Available stock is 0. 3 orders are currently pending allocation for this item.',
            'Fulfill pending backlog of 3 orders. Expected delivery: 2 days.',
            'Critical',
            'Pending',
            '{"action": "reorder_product", "product_id": "P102", "quantity": 40}'
        ),
        (
            'REC104',
            'Reassign Pickers to Zone B',
            'Move Picker PK103 (Mike Johnson) from Zone C (Idle) to Zone B (Delayed Picker, 4 orders pending).',
            'Worker Reassignment',
            'PK103',
            'Zone B picking capacity is overloaded (Sarah Smith is delayed and backlog is rising). Zone C is idle.',
            'Resolve picking delay in Zone B, reducing average picking delay by 25 minutes.',
            'High',
            'Pending',
            '{"action": "reassign_worker", "picker_id": "PK103", "new_zone": "Zone B"}'
        )
    ]
    cursor.executemany('''
        INSERT INTO recommendations (id, title, description, type, ref_id, reason, impact, priority, status, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', recommendations_data)


    # --- 8. SEED AUDIT LOGS ---
    audit_logs_data = [
        ((now - timedelta(hours=24)).isoformat(), 'Warehouse Manager', 'System Seeding', 'Warehouse operations database initialized and seeded.', 'Initial database generation'),
        ((now - timedelta(hours=12)).isoformat(), 'Warehouse Manager', 'Stock Adjust', 'Adjusted product P103 damaged qty to 3.', 'Physical inspection found damaged boxes in Zone A.'),
        ((now - timedelta(hours=6)).isoformat(), 'Warehouse Operator', 'Order Release', 'Released orders O101, O102, O103, and O104 to fulfillment.', 'Standard fulfillment cycle batch release.'),
        ((now - timedelta(hours=4)).isoformat(), 'Warehouse Manager', 'Worker Move', 'Assigned Picker PK101 to Order O103 in Zone A.', 'Order priority critical escalation.')
    ]
    cursor.executemany('''
        INSERT INTO audit_logs (timestamp, user_role, action, details, reason)
        VALUES (?, ?, ?, ?, ?)
    ''', audit_logs_data)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    seed_db()
    print("Database successfully initialized and seeded at:", DB_PATH)
