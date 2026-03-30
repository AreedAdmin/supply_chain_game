#!/usr/bin/env python3
"""
Supply Chain Game – data-download pipeline.

Usage:
    python pipeline.py              # one-shot run (headless)
    python pipeline.py --headed     # one-shot with visible browser (debugging)
    python pipeline.py --discover   # only run endpoint discovery, then exit

Downloaded XLS files land in  data/raw/<timestamp>/
Warehouse parameters land in  data/params/<timestamp>.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import os

import config as cfg
from scraper import SupplyChainScraper

ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PARAMS = ROOT / "data" / "params"
LOG_DIR = ROOT / "logs"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def load_credentials() -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".ENV")
    username = os.getenv("USERNAME", "").strip()
    password = os.getenv("PASSWORD", "").strip()
    if not username or not password:
        raise EnvironmentError(
            "USERNAME and PASSWORD must be set in .env"
        )
    return username, password


def save_warehouse_params(
    params: dict, dest_dir: Path, timestamp: str
) -> Path:
    """Persist warehouse params as both JSON and a flat CSV."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    json_path = dest_dir / f"warehouse_params_{timestamp}.json"
    json_path.write_text(json.dumps(params, indent=2))

    csv_path = dest_dir / f"warehouse_params_{timestamp}.csv"
    rows: list[dict] = []
    for entry in params.get("inbound", []):
        row = {"region": params["region"], "direction": "inbound", **entry}
        rows.append(row)
    for entry in params.get("outbound", []):
        row = {"region": params["region"], "direction": "outbound", **entry}
        rows.append(row)
    if rows:
        all_keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for k in row:
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    return json_path


def run(headless: bool = True, discover_only: bool = False) -> None:
    log = logging.getLogger("pipeline")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest_dir = DATA_RAW / timestamp

    username, password = load_credentials()
    scraper = SupplyChainScraper(username, password, headless=headless)

    try:
        scraper.start()
        scraper.login()

        # ── 1. discover endpoints from live pages ──────────────────────
        log.info("Discovering HQ endpoints …")
        scraper.discover_hq_endpoints()

        for region in cfg.ACTIVE_WAREHOUSE_REGIONS:
            log.info("Discovering warehouse segments for region %d …", region)
            scraper.discover_warehouse_segments(region)

        if discover_only:
            log.info("Discovery complete. HQ_ENDPOINTS = %s", cfg.HQ_ENDPOINTS)
            log.info("SHIPMENT_SEGMENTS = %s", cfg.SHIPMENT_SEGMENTS)
            return

        # ── 2. download HQ data (demand, lost demand, cash) ───────────
        log.info("Downloading HQ data …")
        hq_files = scraper.download_hq_data(dest_dir)
        log.info("HQ downloads: %s", [p.name for p in hq_files])

        # ── 3. download warehouse data (inventory, shipments) ─────────
        for region in cfg.ACTIVE_WAREHOUSE_REGIONS:
            region_name = cfg.REGIONS.get(region, str(region))
            log.info("Downloading warehouse data for %s …", region_name)
            wh_files = scraper.download_warehouse_data(region, dest_dir)
            log.info(
                "%s warehouse downloads: %s",
                region_name,
                [p.name for p in wh_files],
            )

        # ── 4. download factory data (WIP) ────────────────────────────
        for region in cfg.ACTIVE_FACTORY_REGIONS:
            region_name = cfg.REGIONS.get(region, str(region))
            log.info("Downloading factory data for %s …", region_name)
            fac_files = scraper.download_factory_data(region, dest_dir)
            log.info(
                "%s factory downloads: %s",
                region_name,
                [p.name for p in fac_files],
            )

        # ── 5. scrape warehouse parameters ─────────────────────────────
        for region in cfg.ACTIVE_WAREHOUSE_REGIONS:
            region_name = cfg.REGIONS.get(region, str(region))
            log.info("Scraping warehouse params for %s …", region_name)
            params = scraper.scrape_warehouse_params(region)
            saved = save_warehouse_params(params, DATA_PARAMS, timestamp)
            log.info("Params saved to %s", saved)

        log.info("Pipeline complete – files in %s", dest_dir)

    except Exception:
        log.exception("Pipeline failed")
        raise
    finally:
        scraper.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supply Chain Game data pipeline"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible browser window (for debugging)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Only discover endpoints, don't download data",
    )
    args = parser.parse_args()

    setup_logging()
    run(headless=not args.headed, discover_only=args.discover)


if __name__ == "__main__":
    main()
