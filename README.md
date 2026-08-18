# SMART WAREHOUSE AI
### Smart Warehouse Operations & Order Fulfillment System

A complete, polished, and hackathon-ready Decision-Support Warehouse Management System (WMS). Rather than acting as a static CRUD database, this system dynamically automates the **"Exception → Decision → Resolution"** lifecycle to optimize stock allocation, worker routing, and priority scheduling.

---

## 1. Core Problem & Objective
Traditional warehouses face major friction points: lack of real-time visibility, stockouts, delayed picking sequences, and sub-optimal inventory allocation when high-priority orders compete with low-priority orders for the same resources. 

**Smart Warehouse AI** acts as a decision-support command center that analyzes data, raises alerts, calculates delay risks, proposes optimizations, and allows managers to take corrective actions instantly.

---

## 2. Key Features

### 🏠 Command Center Dashboard
- Displays **KPI Cards** representing Total Products, Total Inventory, Pending/Picking orders, Low Stock, Out-of-Stock, and Damaged count, and a real-time Fulfillment Rate.
- Incorporates a **Hackathon Live Demo** panel to trigger a live fulfillment scenario in real-time.
- Shows active operational bottlenecks and pending smart recommendations.

### 📦 Smart Inventory & Allocation Engine
- Detects stock status (Healthy, Low Stock, Out of Stock, Overstocked, Damaged) and generates action recommendations.
- **Stock Reallocation**: Intelligently resolves shortages for Critical orders by suggesting to steal allocated stock from lower-priority orders. Managers can Accept or Reject this reallocation.
- Modals to adjust stock levels manually or log damaged boxes.

### 🛒 Smart Order Prioritization Scorecard
- Computes priority scores based on:
  $$\text{Priority Score} = \text{Deadline Urgency (0-40)} + \text{Customer Importance (0-25)} + \text{Delay Risk (0-20)} + \text{Order Age (0-15)}$$
- Classifies orders into **Critical** ($\ge 70$), **High** ($50\text{--}69$), **Medium** ($30\text{--}49$), and **Low** ($<30$).
- Displays a visual scorecard explaining exactly **why** an order received its priority.

### 👷 Optimized Picking & Routing
- Renders **Current vs Optimized picking paths** using location clustering.
- Displays metrics showing distance reduction percentages and transit time saved.
- Flags zone congestion backlogs and recommends worker reassignments.

### 📦 Packing & Quality Control Checklist
- Checklist containing 5 validations (Quantities, Product codes, Product integrity, Address verification, Box seals) that must be passed before dispatch.
- **Fail QC** actions automatically log a Quality Failure exception and return the order to picking.

### ⚠️ Exception Lifecycle Timeline
- Logs incidents (Damaged, Missing, Stock Shortage, QC Failure, Dispatch delays).
- Displays a visual timeline mapping: **Exception ID** $\rightarrow$ **Decision Recommendation** $\rightarrow$ **Resolution Notes**.

### 🔮 What-If Sandbox Simulator
- Slider controls modeling disruptions: influx of urgent orders, carrier delays, capacity loss, damaged boxes, or key product stockouts.
- Renders side-by-side comparison (Current vs Simulated metrics) and suggests AI mitigations.

### 📊 Analytics & Auditing
- Chart.js dashboards showing category densities, exception volumes, order statuses, and daily dispatch counts.
- Time-stamped auditing logging user actions.

---

## 3. Technology Stack
- **Frontend**: HTML5, CSS3 (Glassmorphism, custom dark/light variables), JavaScript (Vanilla ES6, AJAX), Lucide Icons, Chart.js.
- **Backend**: Python 3.13+, Flask.
- **Database**: SQLite.

---

## 4. Project Folder Structure
```text
ware house/
│
├── app.py                      # Flask Application entrypoint & routes
├── README.md                   # Project documentation
│
├── database/
│   ├── db_manager.py           # SQLite tables schema creation & seeding
│   └── warehouse.db            # Local database file (auto-generated)
│
├── backend/
│   ├── decision_engine.py      # Priority scores, bottlenecks, stock health rules
│   ├── recommendation_engine.py# Scans states, writes/executes recommendation triggers
│   └── services.py             # KPIs, Simulator calculator, Picking path sequence
│
├── frontend/
│   └── templates/              # HTML Templates extending base.html
│       ├── base.html
│       ├── dashboard.html
│       ├── inventory.html
│       ├── orders.html
│       ├── order_detail.html
│       ├── picking.html
│       ├── packing.html
│       ├── exceptions.html
│       ├── recommendations.html
│       ├── simulator.html
│       ├── analytics.html
│       └── audit_logs.html
│
└── static/
    ├── css/
    │   └── styles.css          # Dark-tech styling sheet
    └── js/
        └── app.js              # Global theme and toast handlers
```

---

## 5. Installation & Setup

1. **Clone or Navigate** to the project directory:
   ```bash
   cd "c:\Users\DEVIKA\Desktop\ware house"
   ```

2. **Verify Flask is Installed**:
   This project requires Flask. If you do not have it, run:
   ```bash
   pip install Flask
   ```

3. **Initialize and Seed the Database**:
   Run the seeding script to create `warehouse.db` with 50+ products, 30+ orders, and edge cases:
   ```bash
   python database/db_manager.py
   ```

4. **Launch the Application**:
   Run the web server:
   ```bash
   python app.py
   ```
   The application will start on: **`http://127.0.0.1:5000`**

---

## 6. Testing & Seeding Verification
A verification script is included to test backend models:
```bash
python "C:\Users\DEVIKA\.gemini\antigravity\brain\b1ba0231-35ef-4afd-b4f9-31c0b239a76f\scratch\verify_system.py"
```

---

## 7. Mock Login & User Role Switcher
Test different roles using the dropdown switcher in the top navigation bar:
- **Warehouse Manager**: Full access to simulator, dashboard analytics, recommendations inbox, and audits.
- **Warehouse Operator**: Standard access to inventory adjustments, orders, and audits.
- **Picker**: Dedicated view of picking maps, routing optimization paths, and active picking task queues.
- **Packing Staff**: Access to packing station backlogs and quality verification checklists.

---

## 8. Live Demonstration Guide (Hackathon judges)
1. Navigate to the **Dashboard** `http://127.0.0.1:5000/`.
2. Locate the **HACKATHON LIVE DEMO MODE** panel at the top.
3. Click **`🔥 RUN LIVE SCENARIO`**.
4. The panel displays a live progressive stepper as the Decision Engine performs calculations:
   - *Baseline checks*: Finds Wireless Mouse (`P101`) has 7 units.
   - *Order Shortage*: Urgent Order `O101` requires 10 units. Available is insufficient.
   - *Score Calculation*: Order `O101` priority score is computed (85 - Critical).
   - *Conflict Search*: Medium priority Order `O102` holds 5 allocated units.
   - *Recommendation generated*: Allocate 5 units of `P101` from lower-priority `O102` to `O101`.
   - *Acceptance & Execution*: Automatically modifies database tables: `O101` changes status to fully `Allocated`, `O102` drops to `Partially Allocated`. available stock of `P101` is depleted (0).
   - *Trigger Alerts*: Reorder recommendation `REC-REORDER-P101` is escalated to Critical status.
5. Watch the dashboard reload automatically to see the updated KPIs. Visit the **Audit Log** page to verify the manager's action history.
