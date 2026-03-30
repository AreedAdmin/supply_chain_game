"""
URL registry, region mappings, and data-endpoint definitions
for The Supply Chain Game at op.responsive.net.
"""

BASE_URL = "https://op.responsive.net"

LOGIN_URL = f"{BASE_URL}/sc/imperial/entry.html"
MAIN_URL = f"{BASE_URL}/SupplyChain/SCAccess"
PLOT_URL = f"{BASE_URL}/SupplyChain/SCPlotk"
HQ_URL = f"{BASE_URL}/SupplyChain/SCCorp?submit=change"

REGIONS = {
    1: "Calopeia",
    2: "Sorange",
    3: "Tyran",
    4: "Entworpe",
    5: "Fardo",
}

# ── Headquarters plot endpoints (accessed from SCCorp popup) ────────────
# The submit and data values are derived from the onclick handlers on the
# HQ page buttons.  They will be verified/overridden at runtime when
# discover_hq_endpoints() parses the actual page.
HQ_ENDPOINTS = {
    "demand": {
        "submit": "plot demand",
        "data": "DEMAND1",
    },
    "lost_demand": {
        "submit": "plot lost demand",
        "data": "LOST1",
    },
    "cash_balance": {
        "submit": "plot cash balance",
        "data": "BALANCE",
    },
}

# ── Warehouse endpoints (per region that has a warehouse) ───────────────
WAREHOUSE_URL_TEMPLATE = f"{BASE_URL}/SupplyChain/SCWarehouse?submit=change&region={{region}}"

WAREHOUSE_ENDPOINTS = {
    "inventory": {
        "submit": "plot+inventory",
        "data_template": "WH{region}",
    },
    "shipments": {
        "submit": "plot+shipments",
        "data_template": "SHIP{region}SEG{{seg}}",
    },
}

# Regions where we currently operate a warehouse (update as you expand).
ACTIVE_WAREHOUSE_REGIONS = [1]

# Known shipment segments per warehouse region.
# Each warehouse can ship via multiple segments; update as you discover more.
SHIPMENT_SEGMENTS = {
    1: [1],
}

# ── Factory endpoints (per region that has a factory) ──────────────────
FACTORY_URL_TEMPLATE = f"{BASE_URL}/SupplyChain/SCFactory?submit=change&region={{region}}"

FACTORY_ENDPOINTS = {
    "wip": {
        "submit": "plot+wip",
        "data_template": "WIP{region}",
    },
}

ACTIVE_FACTORY_REGIONS = [1]

# ── Game economics (from HQ page: "Revenue per drum is $1,450.00") ────
REVENUE_PER_DRUM = 1_450.00

SHIPPING_COSTS = {
    "mail": {"per_unit": 150.00, "lead_time_days": 1},
    "truck": {"per_truck": 15_000.00, "lead_time_days": 7},
}

FULFILLMENT_COSTS = {
    "Calopeia": 150.00,
    "Sorange": 200.00,
    "Tyran": 200.00,
    "Entworpe": 200.00,
    "Fardo": 400.00,
}

# ── Factory investment economics (from game UI) ───────────────────────
FACTORY_FIXED_COST = 500_000.0
FACTORY_CAPACITY_COST_PER_DRUM = 50_000.0
FACTORY_BUILD_TIME_DAYS = 90
PRODUCTION_COST_FIXED = 1_500.0    # fixed cost per production batch
PRODUCTION_COST_PER_UNIT = 1_000.0 # variable cost per drum

# ── Timeouts (milliseconds) ────────────────────────────────────────────
PAGE_LOAD_TIMEOUT = 15_000
DOWNLOAD_TIMEOUT = 30_000
