# workers.py
from __future__ import annotations

import time
import threading
from typing import Optional

import pandas as pd

import automation
import config
from rowstore import with_csv_lock, load_df, save_df, rotate_row_to_bottom, append_row_dict
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
    Processes the FIRST row repeatedly until:
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

                # ---- Peek first row (WITHOUT removing) ----
                with with_csv_lock(self.src_csv):
                    df = load_df(self.src_csv)
                    if df.empty:
                        self._status("source empty")
                        break
                    row_index = 0
                    row_series = df.iloc[row_index]

                # ---- Run creation or login in-process (keep driver alive) ----
                try:
                    creation_flag = str(row_series.get("CREATION", "")).strip()
                    if creation_flag == "1":
                        self._status("login", f"row0={row_series.get('nom','')}")
                        run_login_on_row(drv, row_index, row_series, self.src_csv, self.target_ddmm)
                    else:
                        self._status("creation", f"row0={row_series.get('nom','')}")
                        run_creation_on_row(drv, row_index, row_series, self.src_csv, self.target_ddmm)
                except Exception as e:
                    # soft reset app; keep session alive
                    self._status("row error", str(e))
                    try:
                        hard_reset_app(drv, config.APP_PACKAGE)
                    except Exception:
                        pass
                    # continue to routing with whatever is in the CSV now

                # ---- Check outcome on row 0 & route ----
                with with_csv_lock(self.src_csv):
                    df_after = load_df(self.src_csv)
                    if df_after.empty:
                        self._status("source empty after run")
                        break

                    row_after = df_after.iloc[0].to_dict()
                    created = str(row_after.get("CREATION", "")).strip() == "1"
                    reserved = str(row_after.get("RESERVATION", "")).strip() == "1"

                    if created and reserved:
                        # drop first from src
                        rest = df_after.drop(df_after.index[0]).reset_index(drop=True)
                        save_df(rest, self.src_csv)
                        # append to destination
                        append_row_dict(self.dest_csv, row_after)
                        self.success += 1
                        self._status("moved → dest", f"ok={self.success}")
                    else:
                        # explicit fail? drop
                        if str(row_after.get("CREATION", "")).strip() == "-1":
                            rest = df_after.drop(df_after.index[0]).reset_index(drop=True)
                            save_df(rest, self.src_csv)
                            self._status("dropped (CREATION=-1)")
                        else:
                            # rotate to bottom (keep columns aligned)
                            rest = df_after.drop(df_after.index[0]).reset_index(drop=True)
                            save_df(rest, self.src_csv)
                            rotate_row_to_bottom(self.src_csv, row_after)
                            self._status("rotated to bottom")

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