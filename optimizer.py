"""
Analytics and optimization engine for The Supply Chain Game.

Components
----------
- DataLoader          – reads the latest scraped data into DataFrames
- DemandForecaster    – time-decayed demand analysis with regime-change detection
- InventoryOptimizer  – (s,Q) reorder-point / order-quantity optimisation
- InvestmentAdvisor   – lost-revenue analysis, factory capacity, region ranking
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd

import config as cfg

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PARAMS = ROOT / "data" / "params"


# ════════════════════════════════════════════════════════════════════════
#  Data Loader
# ════════════════════════════════════════════════════════════════════════

class GameData(TypedDict, total=False):
    demand: pd.DataFrame
    lost_demand: pd.DataFrame
    cash_balance: pd.DataFrame
    inventory: dict[str, pd.DataFrame]
    shipments: dict[str, pd.DataFrame]
    wip: dict[str, pd.DataFrame]
    warehouse_params: dict
    run_dir: Path
    game_day: int


def load_latest_run(data_dir: Path | None = None) -> GameData:
    """
    Read the most recent scraper output into a structured dict.

    If *data_dir* is given it is used directly; otherwise the newest
    timestamped subfolder under ``data/raw/`` is picked.
    """
    if data_dir is None:
        candidates = sorted(
            p for p in DATA_RAW.iterdir() if p.is_dir()
        )
        if not candidates:
            raise FileNotFoundError("No data runs found in data/raw/")
        data_dir = candidates[-1]

    gd: GameData = {"run_dir": data_dir, "inventory": {}, "shipments": {}, "wip": {}}

    for xls in sorted(data_dir.glob("*.xls")):
        df = pd.read_excel(xls)
        name = xls.stem.lower()

        if name == "demand":
            gd["demand"] = df
        elif name == "lost_demand":
            gd["lost_demand"] = df
        elif name == "cash_balance":
            if "Unnamed: 1" in df.columns:
                df = df.rename(columns={"Unnamed: 1": "cash"})
            gd["cash_balance"] = df
        elif name.startswith("inventory_"):
            gd["inventory"][name] = df
        elif name.startswith("shipments_"):
            gd["shipments"][name] = df
        elif name.startswith("wip_"):
            gd["wip"][name] = df

    param_files = sorted(DATA_PARAMS.glob("warehouse_params_*.json"))
    if param_files:
        gd["warehouse_params"] = json.loads(param_files[-1].read_text())

    if "demand" in gd:
        gd["game_day"] = int(gd["demand"]["day"].max())

    log.info(
        "Loaded run %s  (game day %s, %d files)",
        data_dir.name,
        gd.get("game_day", "?"),
        len(list(data_dir.glob("*.xls"))),
    )
    return gd


# ════════════════════════════════════════════════════════════════════════
#  Demand Forecaster  (time-decayed, regime-change aware)
# ════════════════════════════════════════════════════════════════════════

@dataclass
class RegionForecast:
    region: str
    mean_all: float
    mean_recent: float        # time-decayed mean over recent window
    std_recent: float
    trend: str                # "increasing", "decreasing", "stable", "bulk_orders", "regime_change"
    ewma_forecast: float
    nonzero_pct_all: float    # % of ALL days with demand > 0
    nonzero_pct_recent: float # % of RECENT days with demand > 0
    avg_order_size: float     # mean demand when demand > 0 (recent)
    peak_demand: float        # max single-day demand (recent)


def _time_decay_weights(n: int, half_life: int = 30) -> np.ndarray:
    """Exponential decay weights: most recent day = 1, oldest ~ 0."""
    t = np.arange(n, 0, -1, dtype=float)
    w = np.exp(-np.log(2) * t / half_life)
    return w / w.sum()


def forecast_demand(
    demand_df: pd.DataFrame,
    window: int = 90,
    span: int = 30,
) -> list[RegionForecast]:
    """
    Analyse demand per region using time-decayed weighting and
    regime-change detection for bulk-order patterns.
    """
    regions = [c for c in demand_df.columns if c != "day"]
    results: list[RegionForecast] = []

    for r in regions:
        series = demand_df[r].astype(float)
        recent = series.tail(window)
        weights = _time_decay_weights(len(recent))

        mean_all = series.mean()
        mean_recent = float(np.average(recent.values, weights=weights))
        std_recent = recent.std()
        ewma = series.ewm(span=span).mean().iloc[-1]

        nonzero_all = (series > 0).mean()
        nonzero_recent = (recent > 0).mean()

        recent_nonzero = recent[recent > 0]
        avg_order_size = float(recent_nonzero.mean()) if len(recent_nonzero) > 0 else 0.0
        peak_demand = float(recent.max())

        # ── trend classification ───────────────────────────────────────
        # Split recent window into thirds for finer trend detection
        third = max(1, len(recent) // 3)
        p1 = recent.iloc[:third].sum()
        p2 = recent.iloc[third:2*third].sum()
        p3 = recent.iloc[2*third:].sum()

        # Detect bulk-order pattern: few active days but large order sizes
        is_bulk = avg_order_size > 50 and nonzero_recent < 0.3

        # Detect regime change: recent activity >> historical activity
        is_regime_change = (
            nonzero_recent > nonzero_all * 3
            and nonzero_all < 0.20
            and nonzero_recent > 0.02
        )

        if is_bulk:
            if is_regime_change or (nonzero_recent > nonzero_all * 2):
                trend = "regime_change"
            else:
                trend = "bulk_orders"
        elif nonzero_all < 0.05 and nonzero_recent < 0.02:
            trend = "sporadic"
        elif p3 > p1 * 1.3:
            trend = "increasing"
        elif p3 < p1 * 0.7:
            trend = "decreasing"
        else:
            trend = "stable"

        results.append(RegionForecast(
            region=r,
            mean_all=round(mean_all, 1),
            mean_recent=round(mean_recent, 1),
            std_recent=round(std_recent, 1),
            trend=trend,
            ewma_forecast=round(ewma, 1),
            nonzero_pct_all=round(nonzero_all * 100, 1),
            nonzero_pct_recent=round(nonzero_recent * 100, 1),
            avg_order_size=round(avg_order_size, 0),
            peak_demand=round(peak_demand, 0),
        ))

    return results


# ════════════════════════════════════════════════════════════════════════
#  Inventory Optimizer  (s, Q) policy – time-decayed, served-regions
# ════════════════════════════════════════════════════════════════════════

@dataclass
class SQRecommendation:
    warehouse: str
    current_s: int
    current_Q: int
    recommended_s: int
    recommended_Q: int
    current_cost: float
    recommended_cost: float
    savings_per_day: float
    shipping_method: str
    served_regions: list[str] = field(default_factory=list)


def _simulate_sq(
    daily_demand: np.ndarray,
    s: int,
    Q: int,
    lead_time: int = 1,
    holding_cost_per_unit: float = 0.10,
    stockout_cost_per_unit: float = 1_450.0,
    shipping_cost_per_unit: float = 150.0,
) -> float:
    """
    Simulate an (s, Q) inventory policy over a demand trace and return
    the average daily total cost.

    Holding cost calibrated to ~$0.10/unit/day, reflecting opportunity
    cost of capital at ~2.5% annual on $1,450 inventory value.
    """
    n = len(daily_demand)
    inventory = float(s + Q)
    pending_orders: list[tuple[int, int]] = []
    total_holding = 0.0
    total_stockout = 0.0
    total_shipping = 0.0

    for day in range(n):
        new_pending = []
        for arrival, qty in pending_orders:
            if arrival <= day:
                inventory += qty
                total_shipping += qty * shipping_cost_per_unit
            else:
                new_pending.append((arrival, qty))
        pending_orders = new_pending

        demand = daily_demand[day]
        if inventory >= demand:
            inventory -= demand
        else:
            lost = demand - inventory
            total_stockout += lost * stockout_cost_per_unit
            inventory = 0.0

        total_holding += inventory * holding_cost_per_unit

        if inventory <= s and not pending_orders:
            pending_orders.append((day + lead_time, Q))

    return (total_holding + total_stockout + total_shipping) / n


def _get_served_regions(wh_params: dict) -> list[str]:
    """Extract region names that the warehouse is configured to serve."""
    served = []
    for entry in wh_params.get("outbound", []):
        if entry.get("serve") is True:
            served.append(entry["destination"])
    return served


def optimize_inventory(
    gd: GameData,
    window: int = 180,
) -> list[SQRecommendation]:
    """
    For each active warehouse, grid-search for (s, Q) that minimises
    simulated total cost over the most recent *window* days.

    Uses only demand from regions actually served by the warehouse,
    with time-decay weighting so recent demand patterns dominate.
    """
    demand_df = gd.get("demand")
    wh_params = gd.get("warehouse_params", {})
    if demand_df is None:
        return []

    served_regions = _get_served_regions(wh_params)
    if not served_regions:
        served_regions = ["Calopeia"]

    available_cols = [c for c in served_regions if c in demand_df.columns]
    if not available_cols:
        return []

    # Use shipments (actual fulfilled demand) rather than raw demand
    # for regions the warehouse serves, to reflect what actually flows
    # through this warehouse.  Fall back to demand if shipments missing.
    ship_data = gd.get("shipments", {})
    if ship_data:
        ship_df = list(ship_data.values())[0]
        ship_cols = [c for c in available_cols if c in ship_df.columns]
        if ship_cols:
            # Actual fulfilled + demand for what we SHOULD serve
            # Use raw demand so the optimizer accounts for spike risk
            pass

    recent_demand = demand_df[available_cols].tail(window).sum(axis=1).values

    current_s = int(wh_params.get("inbound", [{}])[0].get("order_point", 2000))
    current_Q = int(wh_params.get("inbound", [{}])[0].get("quantity", 1000))
    method = wh_params.get("inbound", [{}])[0].get("shipping_method", "mail")

    lead_time = cfg.SHIPPING_COSTS.get(method, {}).get("lead_time_days", 1)
    ship_cost = cfg.SHIPPING_COSTS.get(method, {}).get("per_unit", 150.0)

    current_cost = _simulate_sq(
        recent_demand, current_s, current_Q,
        lead_time=lead_time, shipping_cost_per_unit=ship_cost,
    )

    best_cost = current_cost
    best_s, best_Q = current_s, current_Q

    # Demand statistics for search range calibration
    avg_demand = recent_demand.mean()
    max_demand = recent_demand.max()

    # Search range must account for bulk orders (e.g. 250-unit spikes)
    s_max = max(int(max_demand * 3), int(avg_demand * 15))
    s_step = max(1, int(avg_demand * 0.5))
    q_max = max(int(max_demand * 3), int(avg_demand * 12))
    q_step = max(1, int(avg_demand * 0.5))

    s_range = range(max(1, int(avg_demand)), s_max + 1, s_step)
    q_range = range(max(1, int(avg_demand)), q_max + 1, q_step)

    for s_candidate in s_range:
        for q_candidate in q_range:
            cost = _simulate_sq(
                recent_demand, s_candidate, q_candidate,
                lead_time=lead_time, shipping_cost_per_unit=ship_cost,
            )
            if cost < best_cost:
                best_cost = cost
                best_s, best_Q = s_candidate, q_candidate

    savings = current_cost - best_cost

    rec = SQRecommendation(
        warehouse="Calopeia",
        current_s=current_s,
        current_Q=current_Q,
        recommended_s=best_s,
        recommended_Q=best_Q,
        current_cost=round(current_cost, 2),
        recommended_cost=round(best_cost, 2),
        savings_per_day=round(savings, 2),
        shipping_method=method,
        served_regions=served_regions,
    )
    log.info(
        "Inventory opt (served=%s): s=%d->%d, Q=%d->%d, savings=$%.0f/day",
        available_cols, current_s, best_s, current_Q, best_Q, savings,
    )
    return [rec]


# ════════════════════════════════════════════════════════════════════════
#  Investment Advisor  (with factory cost model)
# ════════════════════════════════════════════════════════════════════════

FACTORY_FIXED_COST = cfg.FACTORY_FIXED_COST
FACTORY_CAPACITY_COST_PER_DRUM = cfg.FACTORY_CAPACITY_COST_PER_DRUM
FACTORY_BUILD_TIME_DAYS = cfg.FACTORY_BUILD_TIME_DAYS
PRODUCTION_COST_FIXED = cfg.PRODUCTION_COST_FIXED
PRODUCTION_COST_PER_UNIT = cfg.PRODUCTION_COST_PER_UNIT


@dataclass
class RegionInvestment:
    region: str
    total_demand: float
    total_lost: float
    service_rate_pct: float
    lost_revenue: float
    daily_lost_revenue: float
    annual_lost_revenue_est: float
    fulfillment_cost: float
    # Time-decayed metrics (recent window)
    recent_daily_demand: float
    recent_active_pct: float
    avg_order_size: float
    peak_demand: float
    # Factory recommendation
    recommended_capacity: int
    factory_build_cost: float
    payback_days: float
    priority: int = 0


def _recommend_capacity(
    recent_demand: pd.Series,
    window: int = 90,
    buffer_factor: float = 1.3,
) -> int:
    """
    Recommend factory capacity in drums/day.

    The factory produces at a steady daily rate while the warehouse
    buffers demand spikes, so capacity is sized to the average daily
    demand × buffer_factor, not peak burst demand.
    """
    recent = recent_demand.tail(window)

    nonzero = recent[recent > 0]
    if len(nonzero) == 0:
        return 0

    # Time-decayed average gives more weight to recent activity
    weights = _time_decay_weights(len(recent))
    weighted_avg = float(np.average(recent.values, weights=weights))

    capacity = weighted_avg * buffer_factor
    return max(1, int(np.ceil(capacity)))


def analyse_investments(
    gd: GameData,
    recent_window: int = 90,
) -> list[RegionInvestment]:
    """
    Calculate lost revenue per region with time-decayed weighting,
    recommend factory capacity, and rank by investment priority.
    """
    demand_df = gd.get("demand")
    lost_df = gd.get("lost_demand")
    if demand_df is None or lost_df is None:
        return []

    regions = [c for c in demand_df.columns if c != "day"]
    n_days = len(demand_df)
    results: list[RegionInvestment] = []

    for r in regions:
        total_demand = demand_df[r].sum()
        total_lost = lost_df[r].sum()
        service_rate = (
            (1 - total_lost / total_demand) * 100 if total_demand > 0 else 100.0
        )

        # Time-decayed lost revenue using recent window
        recent_demand = demand_df[r].tail(recent_window)
        recent_lost = lost_df[r].tail(recent_window)
        weights = _time_decay_weights(len(recent_lost))

        weighted_daily_lost = float(np.average(recent_lost.values, weights=weights))
        weighted_daily_demand = float(np.average(recent_demand.values, weights=weights))

        lost_rev_total = total_lost * cfg.REVENUE_PER_DRUM
        daily_lost_rev = weighted_daily_lost * cfg.REVENUE_PER_DRUM
        annual_est = daily_lost_rev * 365

        fc = cfg.FULFILLMENT_COSTS.get(r, 200.0)

        recent_nonzero = recent_demand[recent_demand > 0]
        avg_order = float(recent_nonzero.mean()) if len(recent_nonzero) > 0 else 0.0
        peak = float(recent_demand.max())
        active_pct = float((recent_demand > 0).mean() * 100)

        # Factory capacity recommendation
        capacity = _recommend_capacity(demand_df[r], window=recent_window)
        build_cost = FACTORY_FIXED_COST + capacity * FACTORY_CAPACITY_COST_PER_DRUM
        net_revenue_per_unit = (
            cfg.REVENUE_PER_DRUM - PRODUCTION_COST_PER_UNIT - fc
        )
        daily_net = weighted_daily_demand * net_revenue_per_unit
        payback = build_cost / daily_net if daily_net > 0 else float("inf")

        results.append(RegionInvestment(
            region=r,
            total_demand=total_demand,
            total_lost=total_lost,
            service_rate_pct=round(service_rate, 1),
            lost_revenue=round(lost_rev_total, 0),
            daily_lost_revenue=round(daily_lost_rev, 0),
            annual_lost_revenue_est=round(annual_est, 0),
            fulfillment_cost=fc,
            recent_daily_demand=round(weighted_daily_demand, 1),
            recent_active_pct=round(active_pct, 1),
            avg_order_size=round(avg_order, 0),
            peak_demand=round(peak, 0),
            recommended_capacity=capacity,
            factory_build_cost=round(build_cost, 0),
            payback_days=round(payback, 0),
        ))

    results.sort(key=lambda x: x.annual_lost_revenue_est, reverse=True)
    for i, r in enumerate(results, 1):
        r.priority = i

    return results
