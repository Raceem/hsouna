# workers.py
from __future__ import annotations

import os
import time
import threading
from typing import Optional

import pandas as pd

import automation
import config
from rowstore import (
    load_df,
    save_df,
    append_row_dict,
    claim_next_row,
    finalize_row,
)
from login import run_login_on_row
from CreationReservation import run_creation_on_row

# If you have a fast in-app reset util, import it (optional safety).
try:
    from sort import hard_reset_app  # your existing helper
except Exception:
    def hard_reset_app(driver, package: str):
        # best-effort no-op fallback
        try:
            driver.terminate_app(package)
        except Exception:
            pass
        try:
            driver.activate_app(package)
        except Exception:
            pass


class DeviceWorker(threading.Thread):
    """
    One worker per device (udid). Keeps a persistent Appium driver alive.
    Claims the next unassigned row (using the WORKER column) and processes it
    repeatedly until:
      - success_target reached (if provided)
      - src CSV is empty
      - stop_event is set
    """
    def __init__(
        self,
        udid: str,
        src_csv: str,
        dest_csv: str,
        target_ddmm: str,
        stop_event: threading.Event,
        success_target: Optional[int] = None,
        label: Optional[str] = None,
    ):
        super().__init__(name=f"worker-{udid or 'default'}", daemon=True)
        self.udid = udid
        self.src_csv = src_csv
        self.dest_csv = dest_csv
        self.target_ddmm = target_ddmm
        self.stop_event = stop_event
        self.success_target = success_target
        self.label = label or self.name

        self.processed = 0
        self.success = 0

    def _status(self, msg: str, sub: str = ""):
        try:
            automation._STATE.set_step(
                f"{self.label} | ok={self.success} proc={self.processed}",
                f"{msg} {sub}".strip()
            )
        except Exception:
            pass

    def run(self):
        # get (or create) a persistent driver for this device
        drv = None
        try:
            try:
                # your config.get_driver can accept udid (step 1 you already did)
                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
            except Exception as e:
                self._status("driver init failed", str(e))
                return

            self._status("started")

            while not self.stop_event.is_set():
                if self.success_target is not None and self.success >= self.success_target:
                    self._status("success target reached")
                    break

                # ---- Claim a free row via WORKER column ----
                row_series, has_rows = claim_next_row(self.src_csv, self.label)
                if row_series is None:
                    if has_rows:
                        # all rows currently claimed by other workers
                        self._status("waiting for row")
                        time.sleep(0.5)
                        continue
                    else:
                        self._status("source empty")
                        break

                # Work on a temporary single-row CSV so run_* functions can mutate it
                tmp_path = f"{self.src_csv}.{self.udid}.tmp.csv"
                try:
                    save_df(pd.DataFrame([row_series]), tmp_path)

                    # ---- Run creation or login (keep driver alive) ----
                    try:
                        creation_flag = str(row_series.get("CREATION", "")).strip()
                        if creation_flag == "1":
                            self._status("login", f"row0={row_series.get('nom','')}")
                            run_login_on_row(drv, 0, row_series, tmp_path, self.target_ddmm)
                        else:
                            self._status("creation", f"row0={row_series.get('nom','')}")
                            run_creation_on_row(drv, 0, row_series, tmp_path, self.target_ddmm)
                    except Exception as e:
                        # soft reset app; keep session alive
                        self._status("row error", str(e))
                        try:
                            hard_reset_app(drv, config.APP_PACKAGE)
                        except Exception:
                            pass

                    # ---- Check outcome & route ----
                    df_after = load_df(tmp_path)
                    if df_after.empty:
                        row_after = {}
                    else:
                        row_after = df_after.iloc[0].to_dict()
                    created = str(row_after.get("CREATION", "")).strip() == "1"
                    reserved = str(row_after.get("RESERVATION", "")).strip() == "1"

                    if created and reserved:
                        row_after.pop("WORKER", None)
                        append_row_dict(self.dest_csv, row_after)
                        finalize_row(self.src_csv, self.label, row_after, requeue=False)
                        self.success += 1
                        self._status("moved → dest", f"ok={self.success}")
                    else:
                        if str(row_after.get("CREATION", "")).strip() == "-1":
                            finalize_row(self.src_csv, self.label, row_after, requeue=False)
                            self._status("dropped (CREATION=-1)")
                        else:
                            finalize_row(self.src_csv, self.label, row_after, requeue=True)
                            self._status("rotated to bottom")

                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                self.processed += 1
                time.sleep(0.05)  # tiny breather

            self._status("stopped")

        finally:
            # Keep driver alive for future batches? If you prefer to close, uncomment:
            # try:
            #     if drv: drv.quit()
            # except Exception:
            #     pass
            pass
