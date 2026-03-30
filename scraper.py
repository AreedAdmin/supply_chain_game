"""
Playwright-based scraper for The Supply Chain Game.

Handles authentication, dynamic endpoint discovery, XLS downloads,
and warehouse-parameter extraction.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

import config as cfg

log = logging.getLogger(__name__)


class SupplyChainScraper:
    """Stateful scraper that keeps a single authenticated browser session."""

    def __init__(self, username: str, password: str, headless: bool = True):
        self._username = username
        self._password = password
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the browser and create a fresh context."""
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(accept_downloads=True)
        self._page = self._context.new_page()
        self._page.set_default_timeout(cfg.PAGE_LOAD_TIMEOUT)
        log.info("Browser started (headless=%s)", self._headless)

    def close(self) -> None:
        """Tear down browser resources (tolerates already-closed handles)."""
        for resource, name in [
            (self._context, "context"),
            (self._browser, "browser"),
        ]:
            try:
                if resource:
                    resource.close()
            except Exception:
                log.debug("Ignoring error closing %s", name)
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            log.debug("Ignoring error stopping playwright")
        log.info("Browser closed")

    # ── authentication ─────────────────────────────────────────────────

    def login(self) -> None:
        """
        Navigate to the login page, fill credentials, and submit.
        Verifies we land on SCAccess after login.
        """
        page = self._page
        page.goto(cfg.LOGIN_URL, wait_until="networkidle")
        log.info("Loaded login page")

        # The form has two text inputs: team-id and password.
        # Locate by input type rather than name (which we haven't confirmed).
        inputs = page.locator("input[type='text'], input[type='password']")
        count = inputs.count()
        if count < 2:
            raise RuntimeError(
                f"Expected at least 2 login inputs, found {count}"
            )

        inputs.nth(0).fill(self._username)
        inputs.nth(1).fill(self._password)

        # Submit – look for an explicit submit button, then fall back to Enter.
        submit_btn = page.locator(
            "input[type='submit'], button[type='submit']"
        )
        if submit_btn.count() > 0:
            submit_btn.first.click()
        else:
            inputs.nth(1).press("Enter")

        page.wait_for_url("**/SCAccess**", timeout=cfg.PAGE_LOAD_TIMEOUT)
        log.info("Login successful – landed on %s", page.url)

    # ── endpoint discovery ─────────────────────────────────────────────

    def discover_hq_endpoints(self) -> dict[str, dict]:
        """
        Open the HQ popup page and parse the <form> elements to
        build a mapping of endpoint-name -> {submit, data} params.
        Each plot button lives in its own form with hidden inputs for
        'submit' and 'data'.
        Returns the discovered dict and also updates cfg.HQ_ENDPOINTS.
        """
        page = self._open_popup(cfg.HQ_URL)
        forms = page.locator("form[action='SCPlotk']")
        discovered: dict[str, dict] = {}

        for i in range(forms.count()):
            form = forms.nth(i)
            submit_hidden = form.locator("input[type='hidden'][name='submit']")
            data_hidden = form.locator("input[type='hidden'][name='data']")

            if submit_hidden.count() == 0 or data_hidden.count() == 0:
                continue

            submit_val = submit_hidden.input_value()
            data_val = data_hidden.input_value()
            label_btn = form.locator("input[type='submit']")
            label = label_btn.get_attribute("value") if label_btn.count() else submit_val
            key = self._sanitise_key(label)
            discovered[key] = {"submit": submit_val, "data": data_val}
            log.info("HQ endpoint discovered: %s -> %s", key, discovered[key])

        if discovered:
            cfg.HQ_ENDPOINTS.update(discovered)

        page.close()
        return discovered

    def discover_warehouse_segments(self, region: int) -> list[int]:
        """
        Open the warehouse page for *region* and return the list of
        shipment-segment indices available (e.g. [1, 2]).
        """
        url = cfg.WAREHOUSE_URL_TEMPLATE.format(region=region)
        page = self._open_popup(url)
        html = page.content()
        segments = sorted(
            {int(m) for m in re.findall(r"SHIP\d+SEG(\d+)", html)}
        )
        page.close()
        if segments:
            cfg.SHIPMENT_SEGMENTS[region] = segments
            log.info("Region %d shipment segments: %s", region, segments)
        return segments

    # ── data download ──────────────────────────────────────────────────

    def download_plot(
        self,
        submit: str,
        data: str,
        dest_dir: Path,
        filename: str | None = None,
    ) -> Path:
        """
        Navigate to a SCPlotk page, click the download button, and save
        the resulting XLS file into *dest_dir*.

        Returns the path of the saved file.
        """
        params = urlencode({"submit": submit, "data": data}, safe="+")
        url = f"{cfg.PLOT_URL}?{params}"

        page = self._open_popup(url)
        page.wait_for_load_state("networkidle")

        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_name = filename or f"{data}.xls"

        download_btn = page.locator("button.download")
        if download_btn.count() == 0:
            download_btn = page.locator(
                "button[title='download'], [class*='download']"
            )

        if download_btn.count() == 0:
            page.close()
            raise RuntimeError(
                f"No download button found on {url}"
            )

        dest_path = dest_dir / safe_name
        with page.expect_download(timeout=cfg.DOWNLOAD_TIMEOUT) as dl_info:
            download_btn.first.click()
        download = dl_info.value
        download.save_as(str(dest_path))

        log.info("Downloaded %s -> %s", url, dest_path)
        page.close()
        return dest_path

    def download_hq_data(self, dest_dir: Path) -> list[Path]:
        """Download all HQ plot data (demand, lost demand, cash)."""
        paths: list[Path] = []
        for name, ep in cfg.HQ_ENDPOINTS.items():
            try:
                p = self.download_plot(
                    submit=ep["submit"],
                    data=ep["data"],
                    dest_dir=dest_dir,
                    filename=f"{name}.xls",
                )
                paths.append(p)
            except Exception:
                log.exception("Failed to download HQ endpoint '%s'", name)
        return paths

    def download_warehouse_data(
        self, region: int, dest_dir: Path
    ) -> list[Path]:
        """Download inventory and shipment data for a given warehouse."""
        paths: list[Path] = []
        region_name = cfg.REGIONS.get(region, f"region{region}")

        # Inventory
        inv = cfg.WAREHOUSE_ENDPOINTS["inventory"]
        data_key = inv["data_template"].format(region=region)
        try:
            p = self.download_plot(
                submit=inv["submit"],
                data=data_key,
                dest_dir=dest_dir,
                filename=f"inventory_{region_name}.xls",
            )
            paths.append(p)
        except Exception:
            log.exception("Failed to download inventory for region %d", region)

        # Shipments (one file per segment)
        segments = cfg.SHIPMENT_SEGMENTS.get(region, [1])
        ship = cfg.WAREHOUSE_ENDPOINTS["shipments"]
        for seg in segments:
            data_key = ship["data_template"].format(region=region).format(
                seg=seg
            )
            try:
                p = self.download_plot(
                    submit=ship["submit"],
                    data=data_key,
                    dest_dir=dest_dir,
                    filename=f"shipments_{region_name}_seg{seg}.xls",
                )
                paths.append(p)
            except Exception:
                log.exception(
                    "Failed to download shipments region %d seg %d",
                    region,
                    seg,
                )

        return paths

    # ── factory data download ──────────────────────────────────────────

    def download_factory_data(
        self, region: int, dest_dir: Path
    ) -> list[Path]:
        """Download WIP (work-in-progress) data for a factory."""
        paths: list[Path] = []
        region_name = cfg.REGIONS.get(region, f"region{region}")

        for name, ep in cfg.FACTORY_ENDPOINTS.items():
            data_key = ep["data_template"].format(region=region)
            try:
                p = self.download_plot(
                    submit=ep["submit"],
                    data=data_key,
                    dest_dir=dest_dir,
                    filename=f"{name}_{region_name}.xls",
                )
                paths.append(p)
            except Exception:
                log.exception(
                    "Failed to download factory %s for region %d", name, region
                )
        return paths

    # ── warehouse parameter scraping ───────────────────────────────────

    def scrape_warehouse_params(self, region: int) -> dict:
        """
        Open the warehouse config page and extract current parameters:
        - inbound: factory location, shipping method, order point, qty, priority
        - outbound: destinations served and fulfillment costs
        """
        url = cfg.WAREHOUSE_URL_TEMPLATE.format(region=region)
        page = self._open_popup(url)
        page.wait_for_load_state("networkidle")

        params: dict = {"region": region}
        bordered_tables = page.locator("table[border='1']")

        # ── inbound table (first bordered table) ──────────────────────
        inbound: list[dict] = []
        if bordered_tables.count() >= 1:
            rows = bordered_tables.nth(0).locator("tr")
            for i in range(rows.count()):
                cells = rows.nth(i).locator("td")
                if cells.count() < 5:
                    continue
                row: dict = {}
                row["factory"] = cells.nth(0).inner_text().strip()

                select = cells.nth(1).locator("select")
                if select.count() > 0:
                    row["shipping_method"] = select.input_value()
                else:
                    row["shipping_method"] = cells.nth(1).inner_text().strip()

                for idx, key in [
                    (2, "order_point"),
                    (3, "quantity"),
                    (4, "priority"),
                ]:
                    inp = cells.nth(idx).locator("input")
                    if inp.count() > 0:
                        row[key] = inp.input_value()
                    else:
                        row[key] = cells.nth(idx).inner_text().strip()
                inbound.append(row)
        params["inbound"] = inbound

        # ── outbound table (second bordered table) ─────────────────────
        outbound: list[dict] = []
        if bordered_tables.count() >= 2:
            rows = bordered_tables.nth(1).locator("tr")
            for i in range(rows.count()):
                cells = rows.nth(i).locator("td")
                if cells.count() < 3:
                    continue
                row = {
                    "destination": cells.nth(0).inner_text().strip(),
                    "fulfillment_cost": cells.nth(1).inner_text().strip(),
                }
                cb = cells.nth(2).locator("input[type='checkbox']")
                if cb.count() > 0:
                    row["serve"] = cb.is_checked()
                else:
                    row["serve"] = cells.nth(2).inner_text().strip()
                outbound.append(row)
        params["outbound"] = outbound

        page.close()
        log.info("Scraped warehouse params for region %d", region)
        return params

    # ── helpers ─────────────────────────────────────────────────────────

    def _open_popup(self, url: str) -> Page:
        """Open a URL in a new tab (mimics the game's popup windows)."""
        page = self._context.new_page()
        page.set_default_timeout(cfg.PAGE_LOAD_TIMEOUT)
        page.goto(url, wait_until="networkidle")
        return page

    @staticmethod
    def _sanitise_key(text: str) -> str:
        """Turn a button label like 'plot demand' into 'demand'."""
        text = text.lower().strip()
        text = re.sub(r"^plot\s+", "", text)
        return re.sub(r"\s+", "_", text)
