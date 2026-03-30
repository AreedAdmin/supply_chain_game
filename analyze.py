#!/usr/bin/env python3
"""
Supply Chain Game – optimization analysis report.

Usage:
    python analyze.py                                        # latest run
    python analyze.py --data-dir data/raw/2026-03-30_131530  # specific run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from optimizer import (
    FACTORY_BUILD_TIME_DAYS,
    FACTORY_CAPACITY_COST_PER_DRUM,
    FACTORY_FIXED_COST,
    GameData,
    RegionForecast,
    RegionInvestment,
    SQRecommendation,
    analyse_investments,
    forecast_demand,
    load_latest_run,
    optimize_inventory,
)
import config as cfg

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "data" / "reports"


# ── formatting helpers ─────────────────────────────────────────────────

def _money(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def _header(gd: GameData) -> str:
    day = gd.get("game_day", "?")
    cash_df = gd.get("cash_balance")
    cash_str = "?"
    if cash_df is not None and "cash" in cash_df.columns:
        raw = cash_df["cash"].iloc[-1]
        cash_str = _money(raw * 1_000)

    lines = [
        "",
        "=" * 72,
        "  SUPPLY CHAIN OPTIMIZATION REPORT",
        "=" * 72,
        f"  Generated : {datetime.now():%Y-%m-%d %H:%M}",
        f"  Game Day  : {day}",
        f"  Cash      : {cash_str}",
        f"  Revenue   : ${cfg.REVENUE_PER_DRUM:,.0f} per drum",
        "=" * 72,
    ]
    return "\n".join(lines)


def _demand_section(forecasts: list[RegionForecast]) -> str:
    lines = [
        "",
        "-" * 72,
        "  DEMAND FORECAST  (time-decayed, regime-change aware)",
        "-" * 72,
        f"  {'Region':<12} {'Avg(all)':>8} {'Avg(90d)':>9} "
        f"{'EWMA':>7} {'Trend':<15} {'Active(all)':>10} {'Active(90d)':>10}",
    ]
    for f in forecasts:
        lines.append(
            f"  {f.region:<12} {f.mean_all:>8.1f} {f.mean_recent:>9.1f} "
            f"{f.ewma_forecast:>7.1f} {f.trend:<15} "
            f"{f.nonzero_pct_all:>9.1f}% {f.nonzero_pct_recent:>9.1f}%"
        )

    lines.append("")
    lines.append("  Order Profile (recent 90 days):")
    lines.append(
        f"  {'Region':<12} {'Avg Order':>10} {'Peak':>8} {'Std':>8}"
    )
    for f in forecasts:
        if f.avg_order_size > 0:
            lines.append(
                f"  {f.region:<12} {f.avg_order_size:>10.0f} "
                f"{f.peak_demand:>8.0f} {f.std_recent:>8.1f}"
            )

    # Flag regime changes
    regime_changes = [f for f in forecasts if f.trend == "regime_change"]
    if regime_changes:
        lines.append("")
        lines.append("  ⚠  REGIME CHANGES DETECTED:")
        for f in regime_changes:
            lines.append(
                f"     {f.region}: activity jumped from {f.nonzero_pct_all:.1f}% "
                f"to {f.nonzero_pct_recent:.1f}% recently, "
                f"avg order = {f.avg_order_size:.0f} units"
            )

    return "\n".join(lines)


def _inventory_section(recs: list[SQRecommendation]) -> str:
    lines = [
        "",
        "-" * 72,
        "  WAREHOUSE PARAMETER RECOMMENDATIONS",
        "-" * 72,
    ]
    if not recs:
        lines.append("  (no warehouse data available)")
        return "\n".join(lines)

    for r in recs:
        lines.append(f"  Warehouse : {r.warehouse}")
        lines.append(f"  Serving   : {', '.join(r.served_regions)}")
        lines.append("")
        lines.append(
            f"  {'Param':<16} {'Current':>10} {'Recommended':>14}"
        )
        lines.append(
            f"  {'order_point':<16} {r.current_s:>10,} "
            f"{r.recommended_s:>14,}"
        )
        lines.append(
            f"  {'quantity':<16} {r.current_Q:>10,} "
            f"{r.recommended_Q:>14,}"
        )
        lines.append(
            f"  {'ship_method':<16} {r.shipping_method:>10} "
            f"{'(keep)':>14}"
        )
        lines.append("")
        lines.append(
            f"  Current avg cost/day : {_money(r.current_cost)}"
        )
        lines.append(
            f"  Optimized cost/day   : {_money(r.recommended_cost)}"
        )
        lines.append(
            f"  Estimated savings    : {_money(abs(r.savings_per_day))}/day"
        )

    return "\n".join(lines)


def _investment_section(investments: list[RegionInvestment]) -> str:
    lines = [
        "",
        "-" * 72,
        "  LOST REVENUE ANALYSIS  (time-decayed)",
        "-" * 72,
        f"  {'Region':<12} {'Tot.Demand':>10} {'Tot.Lost':>10} "
        f"{'Service%':>9} {'Lost Rev':>12} {'Daily(w)':>10} {'Annual Est':>12}",
    ]
    total_lost_rev = 0.0
    for inv in investments:
        total_lost_rev += inv.lost_revenue
        lines.append(
            f"  {inv.region:<12} {inv.total_demand:>10,.0f} "
            f"{inv.total_lost:>10,.0f} {inv.service_rate_pct:>8.1f}% "
            f"{_money(inv.lost_revenue):>12} "
            f"{_money(inv.daily_lost_revenue):>10} "
            f"{_money(inv.annual_lost_revenue_est):>12}"
        )
    lines.append(f"\n  TOTAL LOST REVENUE (cumulative): {_money(total_lost_rev)}")

    # Recent demand profile
    lines += [
        "",
        "-" * 72,
        "  RECENT DEMAND PROFILE (time-decayed, 90-day window)",
        "-" * 72,
        f"  {'Region':<12} {'Demand/day':>10} {'Active%':>8} "
        f"{'Avg Order':>10} {'Peak':>8}",
    ]
    for inv in investments:
        if inv.recent_daily_demand > 0.1:
            lines.append(
                f"  {inv.region:<12} {inv.recent_daily_demand:>10.1f} "
                f"{inv.recent_active_pct:>7.1f}% "
                f"{inv.avg_order_size:>10.0f} {inv.peak_demand:>8.0f}"
            )

    # Factory capacity recommendations
    lines += [
        "",
        "-" * 72,
        "  FACTORY INVESTMENT ANALYSIS",
        "-" * 72,
        f"  Build time: {FACTORY_BUILD_TIME_DAYS} days",
        f"  Fixed cost: {_money(FACTORY_FIXED_COST)}",
        f"  Equipment : {_money(FACTORY_CAPACITY_COST_PER_DRUM)} per drum/day capacity",
        "",
        f"  {'Region':<12} {'Capacity':>8} {'Build Cost':>12} "
        f"{'Payback':>10} {'Rationale'}",
    ]
    for inv in investments:
        if inv.recommended_capacity == 0:
            continue
        payback_str = (
            f"{inv.payback_days:.0f}d" if inv.payback_days < 9999
            else "N/A"
        )
        if inv.service_rate_pct > 95:
            rationale = "Well served – low priority"
        elif inv.avg_order_size > 50:
            rationale = f"Bulk orders ~{inv.avg_order_size:.0f}/order"
        else:
            rationale = f"Service rate {inv.service_rate_pct:.0f}%"
        lines.append(
            f"  {inv.region:<12} {inv.recommended_capacity:>5} d/d "
            f"{_money(inv.factory_build_cost):>12} "
            f"{payback_str:>10} {rationale}"
        )

    return "\n".join(lines)


def _wip_section(gd: GameData) -> str:
    lines = [
        "",
        "-" * 72,
        "  FACTORY WIP SUMMARY",
        "-" * 72,
    ]
    wip_data = gd.get("wip", {})
    if not wip_data:
        lines.append("  (no WIP data available – run pipeline to collect)")
        return "\n".join(lines)

    for name, df in wip_data.items():
        region = name.replace("wip_", "").replace("_", " ").title()
        numeric_cols = [c for c in df.columns if c != "day"]
        if not numeric_cols:
            continue
        recent = df.tail(30)
        lines.append(f"  Factory: {region}")
        for col in numeric_cols:
            avg = recent[col].mean()
            latest = df[col].iloc[-1]
            lines.append(
                f"    {col:<20} latest={latest:>8,.0f}   avg(30d)={avg:>8,.1f}"
            )
    return "\n".join(lines)


# ── main ───────────────────────────────────────────────────────────────

def build_report(gd: GameData) -> str:
    sections: list[str] = [_header(gd)]

    if "demand" in gd:
        forecasts = forecast_demand(gd["demand"])
        sections.append(_demand_section(forecasts))

    inv_recs = optimize_inventory(gd)
    sections.append(_inventory_section(inv_recs))

    if "demand" in gd and "lost_demand" in gd:
        investments = analyse_investments(gd)
        sections.append(_investment_section(investments))

    sections.append(_wip_section(gd))

    sections.append("\n" + "=" * 72)
    return "\n".join(sections)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("analyze")

    parser = argparse.ArgumentParser(
        description="Supply Chain Game optimisation report"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to a specific data/raw/<timestamp> folder",
    )
    args = parser.parse_args()

    gd = load_latest_run(data_dir=args.data_dir)
    report = build_report(gd)

    print(report)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_path = REPORT_DIR / f"report_{ts}.txt"
    report_path.write_text(report)
    log.info("Report saved to %s", report_path)


if __name__ == "__main__":
    main()
