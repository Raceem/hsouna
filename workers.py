# workers.py
from __future__ import annotations

import os
import time
import threading
import subprocess
from typing import Optional, Dict, Any, Tuple, List

import pandas as pd

import Creation
import automation
import config
from rowstore import (
    with_csv_lock,
    load_df,
    save_df,
    append_row_dict,
    claim_next_row,
    finalize_row,
)
from creation_batch import (
    claim_next_for_creation,
    release_row_post_creation,
    release_row_with_update,
)
from login import run_login_on_row
from CreationReservation import run_creation_on_row
from confirmation import run_confirmation_on_row

# ---------- Device cleanup/reset helpers (best-effort) ----------
try:
    from config import hard_reset_app  # your existing helper
except Exception:
    def hard_reset_app(driver, package: str):
        try:
            driver.execute_script(
                "mobile: shell",
                {"command": "pm", "args": ["clear", package], "includeStderr": True, "timeout": 20000},
            )
        except Exception as e:
            logger.info(f"[hard_reset_app] pm clear failed (continuing): {e}")
        try:
            driver.terminate_app(package)
        except Exception:
            pass
        driver.activate_app(package)
        try:
            driver.implicitly_wait(1)
        except Exception:
            pass





# ---------- Confirmation CSV helpers ----------
def claim_next_for_confirmation(src_csv: str, worker_name: str) -> Tuple[pd.Series | None, bool]:
    with with_csv_lock(src_csv):
        df = load_df(src_csv)
        if df.empty:
            return None, False
        if "WORKER" not in df.columns:
            df["WORKER"] = ""
        if "CONFIRMATION" not in df.columns:
            df["CONFIRMATION"] = ""

        worker_col = df["WORKER"].astype(str).str.strip()
        confirm_col = df["CONFIRMATION"].astype(str).str.strip()

        mask_pending = confirm_col != "1"
        mask_self = worker_col == worker_name
        mask_free = worker_col == ""

        eligible_self = df.index[mask_self & mask_pending]
        if len(eligible_self) > 0:
            idx = eligible_self[0]
        else:
            eligible = df.index[mask_free & mask_pending]
            if len(eligible) == 0:
                if ((worker_col != "") & mask_pending).any():
                    return None, True  # other workers still processing
                return None, False
            idx = eligible[0]

        df.at[idx, "WORKER"] = worker_name
        save_df(df, src_csv)
        return df.loc[idx], True


def release_row_post_confirmation(src_csv: str, worker_name: str, updated: dict, *, success: bool) -> None:
    with with_csv_lock(src_csv):
        df = load_df(src_csv)
        if df.empty:
            return
        if "WORKER" not in df.columns:
            df["WORKER"] = ""

        mask = df["WORKER"] == worker_name
        if not mask.any():
            return
        idx = df.index[mask][0]

        merged = df.loc[idx].to_dict()
        merged.update({k: ("" if v is None else str(v)) for k, v in (updated or {}).items()})
        merged["WORKER"] = ""

        for k in merged.keys():
            if k not in df.columns:
                df[k] = ""

        if success:
            for k, v in merged.items():
                if k not in df.columns:
                    df[k] = ""
                df.at[idx, k] = v
            save_df(df, src_csv)
            return

        df = df.drop(idx).reset_index(drop=True)
        df = pd.concat([df, pd.DataFrame([{c: merged.get(c, '') for c in df.columns}])], ignore_index=True)
        save_df(df, src_csv)
# ---------- Detect UiAutomator2 instrumentation crash ----------
def _is_uia2_crash(err: Exception) -> bool:
    try:
        s = (str(err) or "").lower()
    except Exception:
        s = ""
    return (
        ("instrumentation process is not running" in s)
        or ("cannot be proxied to uiautomator2 server" in s)
    )


# ---------- Per-device live status registry ----------
_DEVICE_STATUS: Dict[str, Dict[str, Any]] = {}
_STATUS_LOCK = threading.Lock()


def set_device_status(udid: str, **fields: Any) -> None:
    """Record live status for a UDID (thread-safe)."""
    with _STATUS_LOCK:
        s = _DEVICE_STATUS.get(udid, {})
        s.update(fields)
        s["udid"] = udid
        s["ts"] = time.time()
        _DEVICE_STATUS[udid] = s


def _parse_adb_devices_l(output: str) -> List[Dict[str, str]]:
    devices: List[Dict[str, str]] = []
    for line in output.splitlines():
        s = line.strip()
        if not s or s.startswith("List of devices"):
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[1] == "device":
            udid = parts[0]
            label = udid
            for p in parts[2:]:
                if p.startswith("model:"):
                    label = p.split(":", 1)[1] or label
                    break
                if p.startswith("device:"):
                    label = p.split(":", 1)[1] or label
            devices.append({"udid": udid, "name": label})
    return devices


def list_connected_devices() -> List[Dict[str, str]]:
    """Return connected ADB devices with a friendly label (model/device)."""
    try:
        proc = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, check=False)
        out = proc.stdout or ""
        return _parse_adb_devices_l(out)
    except Exception:
        return []


def get_device_status_snapshot() -> Dict[str, Dict[str, Any]]:
    """Return a snapshot of device statuses, merged with live ADB discovery.

    - Includes any devices currently connected via ADB (idle if no worker).
    - Preserves active worker-provided entries.
    """
    with _STATUS_LOCK:
        snap = {k: dict(v) for k, v in _DEVICE_STATUS.items()}
        try:
            for d in list_connected_devices():
                snap.setdefault(
                    d["udid"],
                    {
                        "udid": d["udid"],
                        "label": d.get("name") or d["udid"],
                        "state": "idle",
                        "processed": 0,
                        "success": 0,
                        "note": "",
                        "batch_id": None,
                        "active": False,
                        "ts": 0,
                    },
                )
                # Ensure label is friendly if missing
                if not snap[d["udid"]].get("label"):
                    snap[d["udid"]]["label"] = d.get("name") or d["udid"]
        except Exception:
            pass
        return snap


# ---------- Shared (combined) target object for a batch ----------
class CombinedTarget:
    """
    Thread-safe shared counter across workers in the same batch.
    Call add_success() when a worker completes one successful row.
    """
    def __init__(self, total: int):
        self.total = int(total)
        self.done = 0
        self._lock = threading.Lock()

    def reached(self) -> bool:
        with self._lock:
            return self.done >= self.total

    def add_success(self, n: int = 1) -> Tuple[int, bool]:
        with self._lock:
            self.done += n
            return self.done, self.done >= self.total


class DeviceWorker(threading.Thread):
    """
    One worker per device (udid). Keeps a persistent Appium driver alive.
    Claims the next unassigned row (via WORKER column) and processes it until:
      - combined_target is reached (if provided)
      - per-device success_target is reached (if provided)
      - source CSV is empty
      - stop_event (shared) or local stop is set
    """

    def __init__(
        self,
        udid: str,
        src_csv: str,
        dest_csv: str,
        target_ddmm: str,
        stop_event: threading.Event,
        success_target: Optional[int] = None,
        combined_target: Optional[CombinedTarget] = None,
        label: Optional[str] = None,
        batch_id: Optional[int] = None,
    ):
        super().__init__(name=f"worker-{udid or 'default'}", daemon=True)
        self.udid = udid
        self.src_csv = src_csv
        self.dest_csv = dest_csv
        self.target_ddmm = target_ddmm
        self.stop_event_shared = stop_event
        self.local_stop_event = threading.Event()  # allows per-device stop
        self.success_target = success_target
        self.combined_target = combined_target
        self.label = label or self.name
        self.batch_id = batch_id

        self.processed = 0
        self.success = 0

        # Initial status
        set_device_status(
            self.udid,
            batch_id=self.batch_id,
            label=self.label,
            state="init",
            processed=self.processed,
            success=self.success,
            src_csv=self.src_csv,
            dest_csv=self.dest_csv,
            target_ddmm=self.target_ddmm,
            note="",
            active=True,
        )

    # ---- public control: per-device stop ----
    def request_stop(self) -> None:
        self.local_stop_event.set()

    # ---- internal: unified stop flag ----
    def _should_stop(self) -> bool:
        if self.local_stop_event.is_set():
            return True
        if self.stop_event_shared.is_set():
            return True
        return False

    # ---- status helper (also updates legacy global step for compatibility) ----
    def _status(self, state: str, note: str = "", extra: Optional[Dict[str, Any]] = None):
        payload = {
            "batch_id": self.batch_id,
            "label": self.label,
            "state": state,
            "processed": self.processed,
            "success": self.success,
            "note": note,
            "active": not self._should_stop(),
        }
        if extra:
            payload.update(extra)
        set_device_status(self.udid, **payload)

        # Keep existing UI step feedback working
        try:
            automation._STATE.set_step(
                f"{self.label} | ok={self.success} proc={self.processed}",
                f"{state} {note}".strip()
            )
        except Exception:
            pass

    def run(self):
        drv = None
        try:
            # Acquire or create a persistent driver for this specific UDID
            try:
                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
            except Exception as e:
                self._status("driver_init_failed", str(e))
                return

            # Optional extra safety: extend newCommandTimeout at runtime
            try:
                drv.update_settings({"newCommandTimeout": 1200})
            except Exception:
                pass

            self._status("started")

            while not self._should_stop():
                # Health probe: if UiAutomator2 crashed, recreate driver session
                try:
                    _ = drv.get_window_size()
                except Exception as e_probe:
                    if _is_uia2_crash(e_probe):
                        self._status("uia2_restart", "recreating driver")
                        try:
                            if hasattr(config, "reset_driver"):
                                config.reset_driver(self.udid)
                        except Exception:
                            pass
                        try:
                            drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                            try:
                                drv.update_settings({"newCommandTimeout": 1200})
                            except Exception:
                                pass
                        except Exception as e_new:
                            self._status("driver_init_failed", str(e_new))
                            break
                # Check shared target first
                if self.combined_target and self.combined_target.reached():
                    self._status("combined_target_reached")
                    break

                # Also respect per-device success target if provided
                if self.success_target is not None and self.success >= self.success_target:
                    self._status("device_target_reached")
                    break

                # ---- Claim a free row via WORKER column ----
                row_series, has_rows = claim_next_row(self.src_csv, self.label)
                if row_series is None:
                    if has_rows:
                        # all rows currently claimed by other workers
                        self._status("waiting_for_row")
                        time.sleep(0.5)
                        continue
                    else:
                        self._status("source_empty")
                        break

                # Prepare a tmp single-row CSV for the row functions to mutate
                tmp_path = f"{self.src_csv}.{self.udid}.tmp.csv"
                nom = str(row_series.get("nom", "") or row_series.get("NOM", ""))
                try:
                    save_df(pd.DataFrame([row_series]), tmp_path)

                    # ---- Run creation or login (keep driver alive) ----
                    try:
                        creation_flag = str(row_series.get("CREATION", "")).strip()
                        if creation_flag == "1":
                            self._status("login", f"row={nom}")
                            run_login_on_row(drv, 0, row_series, tmp_path, self.target_ddmm)
                        else:
                            self._status("creation", f"row={nom}")
                            run_creation_on_row(drv, 0, row_series, tmp_path, self.target_ddmm)
                    except Exception as e:
                        # Recover from UiAutomator2 crash by recreating driver; otherwise soft reset app
                        self._status("row_error", str(e))
                        if _is_uia2_crash(e):
                            try:
                                if hasattr(config, "reset_driver"):
                                    config.reset_driver(self.udid)
                            except Exception:
                                pass
                            try:
                                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                                try:
                                    drv.update_settings({"newCommandTimeout": 1200})
                                except Exception:
                                    pass
                            except Exception as e_new:
                                self._status("driver_init_failed", str(e_new))
                                break
                        else:
                            try:
                                hard_reset_app(drv, config.APP_PACKAGE)
                            except Exception:
                                pass

                    # ---- Check outcome & route ----
                    df_after = load_df(tmp_path)
                    row_after = df_after.iloc[0].to_dict() if not df_after.empty else {}

                    created = str(row_after.get("CREATION", "")).strip() == "1"
                    reserved = str(row_after.get("RESERVATION", "")).strip() == "1"

                    if created and reserved:
                        # Move to destination & finalize without requeue
                        row_after.pop("WORKER", None)
                        append_row_dict(self.dest_csv, row_after)
                        finalize_row(self.src_csv, self.label, row_after, requeue=False)

                        # Success accounting
                        self.success += 1
                        note = ""
                        if self.combined_target:
                            total_done, reached = self.combined_target.add_success(1)
                            note = f"batch_done={total_done}/{self.combined_target.total}"
                            self._status("moved_to_dest", note)
                            if reached:
                                self._status("combined_target_reached")
                                break
                        else:
                            self._status("moved_to_dest", note)
                    else:
                        # Drop permanently if CREATION == -1
                        if str(row_after.get("CREATION", "")).strip() == "-1":
                            finalize_row(self.src_csv, self.label, row_after, requeue=False)
                            self._status("dropped_CREATION_-1")
                        else:
                            # Requeue to bottom for another attempt later
                            finalize_row(self.src_csv, self.label, row_after, requeue=True)
                            self._status("rotated_to_bottom")

                finally:
                    # Always bring app back to a clean landing between rows
                    try:
                        hard_reset_app(drv, config.APP_PACKAGE)
                    except Exception:
                        pass
                    # Cleanup temp CSV
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                self.processed += 1
                time.sleep(0.05)  # tiny breather

            self._status("stopped")

        finally:
            # Keep driver alive for reuse. If you want to close here, uncomment:
            # try:
            #     if drv:
            #         drv.quit()
            # except Exception:
            #     pass
            set_device_status(self.udid, active=False)


class ConfirmationWorker(threading.Thread):
    """Process confirmation rows on a dedicated device."""

    def __init__(
        self,
        udid: str,
        src_csv: str,
        screenshot_root: str,
        stop_event: threading.Event,
        combined_target: Optional[CombinedTarget] = None,
        label: Optional[str] = None,
        batch_id: Optional[int] = None,
    ):
        super().__init__(name=f"confirmation-{udid or 'default'}", daemon=True)
        self.udid = udid
        self.src_csv = src_csv
        self.screenshot_root = screenshot_root
        self.stop_event_shared = stop_event
        self.local_stop_event = threading.Event()
        self.combined_target = combined_target
        self.label = label or self.name
        self.batch_id = batch_id

        self.processed = 0
        self.success = 0

        set_device_status(
            self.udid,
            batch_id=self.batch_id,
            label=self.label,
            state="init",
            processed=self.processed,
            success=self.success,
            src_csv=self.src_csv,
            dest_csv=self.screenshot_root,
            note="",
            active=True,
        )

    def request_stop(self) -> None:
        self.local_stop_event.set()

    def _should_stop(self) -> bool:
        return self.local_stop_event.is_set() or self.stop_event_shared.is_set()

    def _status(self, state: str, note: str = "") -> None:
        set_device_status(
            self.udid,
            batch_id=self.batch_id,
            label=self.label,
            state=state,
            processed=self.processed,
            success=self.success,
            note=note,
            active=not self._should_stop(),
        )
        try:
            automation._STATE.set_step(
                f"{self.label} | ok={self.success} proc={self.processed}",
                f"{state} {note}".strip(),
            )
        except Exception:
            pass

    def run(self):
        drv = None
        try:
            try:
                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
            except Exception as e:
                self._status("driver_init_failed", str(e))
                return

            try:
                drv.update_settings({"newCommandTimeout": 1200})
            except Exception:
                pass

            self._status("started")

            while not self._should_stop():
                row_series, has_rows = claim_next_for_confirmation(self.src_csv, self.label)
                if row_series is None:
                    if has_rows:
                        self._status("waiting_for_row")
                        time.sleep(0.5)
                        continue
                    self._status("no_eligible_rows")
                    break

                tmp_path = f"{self.src_csv}.{self.udid}.confirm.tmp.csv"
                nom = str(row_series.get("nom", "") or row_series.get("NOM", ""))
                try:
                    save_df(pd.DataFrame([row_series]), tmp_path)
                    try:
                        self._status("confirming", f"row={nom}")
                        run_confirmation_on_row(drv, 0, row_series, tmp_path, self.screenshot_root)
                        df_after = load_df(tmp_path)
                        row_after = df_after.iloc[0].to_dict() if not df_after.empty else row_series.to_dict()
                        success = str(row_after.get("CONFIRMATION", "")).strip() == "1"
                        release_row_post_confirmation(self.src_csv, self.label, row_after, success=success)
                        if success:
                            self.success += 1
                            note = row_after.get("confirmation_path", "")
                            if self.combined_target:
                                total_done, reached = self.combined_target.add_success(1)
                                note = note or f"batch_done={total_done}/{self.combined_target.total}"
                                self._status("confirmed", note)
                                if reached:
                                    self._status("combined_target_reached")
                                    break
                            else:
                                self._status("confirmed", note)
                        else:
                            self._status("confirmation_flag_not_set")
                    except Exception as e_row:
                        self._status("row_error", str(e_row))
                        df_after = load_df(tmp_path)
                        row_after = df_after.iloc[0].to_dict() if not df_after.empty else row_series.to_dict()
                        release_row_post_confirmation(self.src_csv, self.label, row_after, success=False)
                        if _is_uia2_crash(e_row):
                            try:
                                if hasattr(config, "reset_driver"):
                                    config.reset_driver(self.udid)
                            except Exception:
                                pass
                            try:
                                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                                try:
                                    drv.update_settings({"newCommandTimeout": 1200})
                                except Exception:
                                    pass
                            except Exception as e_new:
                                self._status("driver_init_failed", str(e_new))
                                break
                        else:
                            try:
                                hard_reset_app(drv, config.APP_PACKAGE)
                            except Exception:
                                pass
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    try:
                        hard_reset_app(drv, config.APP_PACKAGE)
                    except Exception:
                        pass

                self.processed += 1
                time.sleep(0.05)

            self._status("stopped")
        finally:
            set_device_status(self.udid, active=False)
# --- NEW: GenderSortWorker ----------------------------------------------------
class GenderSortWorker(threading.Thread):
    """
    Multi-device sorter:
      - Reads from ALL (src_csv)
      - Creates account, probes permit to determine gender (no reservation)
      - Updates gender and CREATION=1
      - Appends row to HOMMES/FEMMES, then deletes from ALL
      - Marks CREATION=-1 rows as dropped (no requeue)
      - On other failures, requeues the row to bottom of ALL
    """

    def __init__(
        self,
        udid: str,
        all_csv: str,
        hommes_csv: str,
        femmes_csv: str,
        target_ddmm: str,
        stop_event: threading.Event,
        combined_target: Optional[CombinedTarget] = None,
        label: Optional[str] = None,
        batch_id: Optional[int] = None,
    ):
        super().__init__(name=f"gender-sort-{udid or 'default'}", daemon=True)
        self.udid = udid
        self.src_csv = all_csv
        self.hommes_csv = hommes_csv
        self.femmes_csv = femmes_csv
        self.target_ddmm = target_ddmm
        self.stop_event_shared = stop_event
        self.local_stop_event = threading.Event()
        self.combined_target = combined_target
        self.label = label or self.name
        self.batch_id = batch_id

        self.processed = 0
        self.success = 0

        set_device_status(
            self.udid,
            batch_id=self.batch_id,
            label=self.label,
            state="init",
            processed=self.processed,
            success=self.success,
            src_csv=self.src_csv,
            dest_csv=f"{self.hommes_csv} / {self.femmes_csv}",
            target_ddmm=self.target_ddmm,
            note="",
            active=True,
        )

    def request_stop(self) -> None:
        self.local_stop_event.set()

    def _should_stop(self) -> bool:
        return self.local_stop_event.is_set() or self.stop_event_shared.is_set()

    def _status(self, state: str, note: str = "", extra: Optional[Dict[str, Any]] = None):
        payload = {
            "batch_id": self.batch_id,
            "label": self.label,
            "state": state,
            "processed": self.processed,
            "success": self.success,
            "note": note,
            "active": not self._should_stop(),
        }
        if extra:
            payload.update(extra)
        set_device_status(self.udid, **payload)
        try:
            automation._STATE.set_step(
                f"{self.label} | ok={self.success} proc={self.processed}",
                f"{state} {note}".strip()
            )
        except Exception:
            pass

    def run(self):
        from gender_sort import run_gender_probe_on_row, _append_then_delete  # local import to avoid cycles
        drv = None
        try:
            # Driver
            try:
                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                try:
                    drv.update_settings({"newCommandTimeout": 1200})
                except Exception:
                    pass
            except Exception as e:
                self._status("driver_init_failed", str(e))
                return

            self._status("started")

            while not self._should_stop():
                # Health probe
                try:
                    _ = drv.get_window_size()
                except Exception as e_probe:
                    if _is_uia2_crash(e_probe):
                        self._status("uia2_restart", "recreating driver")
                        try:
                            if hasattr(config, "reset_driver"):
                                config.reset_driver(self.udid)
                        except Exception:
                            pass
                        try:
                            drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                            try:
                                drv.update_settings({"newCommandTimeout": 1200})
                            except Exception:
                                pass
                        except Exception as e_new:
                            self._status("driver_init_failed", str(e_new))
                            break

                # Combined target check
                if self.combined_target and self.combined_target.reached():
                    self._status("combined_target_reached")
                    break

                # Claim next from ALL
                row_series, has_rows = claim_next_row(self.src_csv, self.label)
                if row_series is None:
                    if has_rows:
                        self._status("waiting_for_row")
                        time.sleep(0.5)
                        continue
                    else:
                        self._status("source_empty")
                        break

                tmp_path = f"{self.src_csv}.{self.udid}.tmp.csv"
                try:
                    save_df(pd.DataFrame([row_series]), tmp_path)
                    self._status("probing", f"{row_series.get('numero_passport','')}")
                    df_after, outcome = run_gender_probe_on_row(
                        drv, 0, row_series, tmp_path, self.target_ddmm,
                        self.hommes_csv, self.femmes_csv
                    )
                    out_row = df_after.iloc[0].to_dict() if not df_after.empty else {}

                    # Route based on outcome
                    if outcome in {"ROUTED_H", "ROUTED_F"}:
                        dest = self.hommes_csv if outcome.endswith("_H") else self.femmes_csv
                        # Append first (dedupe inside helper), then delete from ALL
                        ok = _append_then_delete(self.src_csv, dest, out_row)
                        if ok:
                            # finalize-and-delete (do NOT requeue)
                            finalize_row(self.src_csv, self.label, out_row, requeue=False)
                            self.success += 1
                            note = "→ HOMMES" if dest == self.hommes_csv else "→ FEMMES"
                            if self.combined_target:
                                total_done, reached = self.combined_target.add_success(1)
                                note += f" | batch {total_done}/{self.combined_target.total}"
                                self._status("routed", note)
                                if reached:
                                    self._status("combined_target_reached")
                                    break
                            else:
                                self._status("routed", note)
                        else:
                            # append failed → requeue to bottom
                            finalize_row(self.src_csv, self.label, out_row, requeue=True)
                            self._status("append_failed_requeued")

                    elif outcome == "DROPPED":
                        finalize_row(self.src_csv, self.label, out_row, requeue=False)
                        self._status("dropped_creation_minus1")

                    elif outcome == "SKIPPED":
                        # Already finalized elsewhere; just delete this claim without requeue
                        finalize_row(self.src_csv, self.label, out_row, requeue=False)
                        self._status("skipped")

                    else:
                        # REQUEUED or failures → rotate to bottom
                        finalize_row(self.src_csv, self.label, out_row, requeue=True)
                        self._status("rotated_to_bottom")

                except Exception as e:
                    self._status("row_error", str(e))
                    # Recreate driver on UiA2 crash; otherwise just rotate claimed row to bottom
                    try:
                        if _is_uia2_crash(e):
                            if hasattr(config, "reset_driver"):
                                config.reset_driver(self.udid)
                            drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                            try:
                                drv.update_settings({"newCommandTimeout": 1200})
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # best-effort requeue original row
                    try:
                        finalize_row(self.src_csv, self.label, row_series.to_dict(), requeue=True)
                    except Exception:
                        pass
                finally:
                    # bring app back to a clean landing
                    try:
                        hard_reset_app(drv, config.APP_PACKAGE)
                    except Exception:
                        pass
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                self.processed += 1
                time.sleep(0.05)

            self._status("stopped")

        finally:
            set_device_status(self.udid, active=False)
class CreationDeviceWorker(threading.Thread):
    """Simplified worker for creation-only batches.

    - Claims rows that are not yet created (CREATION not in {"1","-1"}).
    - Runs creation only; never proceeds to login/reservation.
    - Marks progress when CREATION becomes "1" and releases row in place.
    """

    def __init__(
        self,
        udid: str,
        src_csv: str,
        target_ddmm: str,
        stop_event: threading.Event,
        combined_target: Optional[CombinedTarget] = None,
        label: Optional[str] = None,
        batch_id: Optional[int] = None,
    ):
        super().__init__(name=f"creation-worker-{udid or 'default'}", daemon=True)
        self.udid = udid
        self.src_csv = src_csv
        self.target_ddmm = target_ddmm
        self.stop_event_shared = stop_event
        self.local_stop_event = threading.Event()
        self.combined_target = combined_target
        self.label = label or self.name
        self.batch_id = batch_id

        self.processed = 0
        self.success = 0

        set_device_status(
            self.udid,
            batch_id=self.batch_id,
            label=self.label,
            state="init",
            processed=self.processed,
            success=self.success,
            src_csv=self.src_csv,
            dest_csv=self.src_csv,
            target_ddmm=self.target_ddmm,
            note="",
            active=True,
        )

    def request_stop(self) -> None:
        self.local_stop_event.set()

    def _should_stop(self) -> bool:
        if self.local_stop_event.is_set():
            return True
        if self.stop_event_shared.is_set():
            return True
        return False

    def _status(self, state: str, note: str = "", extra: Optional[Dict[str, Any]] = None):
        payload = {
            "batch_id": self.batch_id,
            "label": self.label,
            "state": state,
            "processed": self.processed,
            "success": self.success,
            "note": note,
            "active": not self._should_stop(),
        }
        if extra:
            payload.update(extra)
        set_device_status(self.udid, **payload)

        try:
            automation._STATE.set_step(
                f"{self.label} | ok={self.success} proc={self.processed}",
                f"{state} {note}".strip(),
            )
        except Exception:
            pass

    def run(self):
        drv = None
        try:
            try:
                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
            except Exception as e:
                self._status("driver_init_failed", str(e))
                return

            try:
                drv.update_settings({"newCommandTimeout": 1200})
            except Exception:
                pass

            self._status("started")

            while not self._should_stop():
                # Health probe
                try:
                    _ = drv.get_window_size()
                except Exception as e_probe:
                    if _is_uia2_crash(e_probe):
                        self._status("uia2_restart", "recreating driver")
                        try:
                            if hasattr(config, "reset_driver"):
                                config.reset_driver(self.udid)
                        except Exception:
                            pass
                        try:
                            drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                            try:
                                drv.update_settings({"newCommandTimeout": 1200})
                            except Exception:
                                pass
                        except Exception as e_new:
                            self._status("driver_init_failed", str(e_new))
                            break

                # Combined target reached?
                if self.combined_target and self.combined_target.reached():
                    self._status("combined_target_reached")
                    break

                # Claim a row that needs creation
                row_series, has_rows = claim_next_for_creation(self.src_csv, self.label)
                if row_series is None:
                    # Nothing eligible; stop
                    self._status("no_eligible_rows")
                    break

                tmp_path = f"{self.src_csv}.{self.udid}.tmp.csv"
                nom = str(row_series.get("nom", "") or row_series.get("NOM", ""))
                try:
                    save_df(pd.DataFrame([row_series]), tmp_path)

                    try:
                        self._status("creation", f"row={nom}")
                        Creation.run_creation_on_row(drv, 0, row_series, tmp_path, self.target_ddmm)
                    except Exception as e:
                        self._status("row_error", str(e))
                        if _is_uia2_crash(e):
                            try:
                                if hasattr(config, "reset_driver"):
                                    config.reset_driver(self.udid)
                            except Exception:
                                pass
                            try:
                                drv = config.get_driver(self.udid) if hasattr(config, "get_driver") else config.setup_driver()
                                try:
                                    drv.update_settings({"newCommandTimeout": 1200})
                                except Exception:
                                    pass
                            except Exception as e_new:
                                self._status("driver_init_failed", str(e_new))
                                break
                        else:
                            try:
                                hard_reset_app(drv, config.APP_PACKAGE)
                            except Exception:
                                pass

                    # Outcome: update and route per creation-only rules
                    df_after = load_df(tmp_path)
                    row_after = df_after.iloc[0].to_dict() if not df_after.empty else {}
                    created = str(row_after.get("CREATION", "")).strip() == "1"

                    try:
                        release_row_post_creation(self.src_csv, self.label, row_after)
                    except Exception:
                        # fallback: best-effort release
                        try:
                            release_row_with_update(self.src_csv, self.label, row_after)
                        except Exception:
                            pass

                    if created:
                        self.success += 1
                        note = ""
                        if self.combined_target:
                            total_done, reached = self.combined_target.add_success(1)
                            note = f"batch_done={total_done}/{self.combined_target.total}"
                            self._status("created", note)
                            if reached:
                                self._status("combined_target_reached")
                                break
                        else:
                            self._status("created", note)
                    else:
                        self._status("rotated_or_dropped")

                finally:
                    try:
                        hard_reset_app(drv, config.APP_PACKAGE)
                    except Exception:
                        pass
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                self.processed += 1
                time.sleep(0.05)

            self._status("stopped")

        finally:
            set_device_status(self.udid, active=False)

