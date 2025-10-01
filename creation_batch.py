from __future__ import annotations

import os
import time
import threading
from typing import Callable, Tuple, List

import pandas as pd
from rowstore import with_csv_lock
from config import APP_PACKAGE, hard_reset_app


# ---- minimal CSV helpers (avoid circular imports) ----------------------------
def _load_df(csv_path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(csv_path, dtype=str, keep_default_na=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")


def _ensure_common_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col, default in [
        ("CREATION", ""),
        ("RESERVATION", ""),
        ("email", ""),
        ("numero_tlf", ""),
        ("numero_passport", ""),
        ("nationalite", ""),
    ]:
        if col not in df.columns:
            df[col] = default
    if "WORKER" not in df.columns:
        df["WORKER"] = ""
    return df


# ---- detect UiAutomator2 instrumentation crash ------------------------------
def _is_uia2_crash(err: Exception) -> bool:
    try:
        s = (str(err) or "").lower()
    except Exception:
        s = ""
    return (
        ("instrumentation process is not running" in s)
        or ("cannot be proxied to uiautomator2 server" in s)
    )


# ---- row claim/release -------------------------------------------------------
def claim_next_for_creation(src_csv: str, worker_name: str) -> Tuple[pd.Series | None, bool]:
    with with_csv_lock(src_csv):
        df = _load_df(src_csv)
        if df.empty:
            return None, False
        df = _ensure_common_columns(df)
        mask_need = (df["WORKER"].astype(str) == "") & (~df["CREATION"].astype(str).str.strip().isin(["1", "-1"]))
        if not mask_need.any():
            return None, False
        idx = df.index[mask_need][0]
        df.at[idx, "WORKER"] = worker_name
        _save_df(df, src_csv)
        return df.loc[idx], True


def release_row_with_update(src_csv: str, worker_name: str, updated: dict) -> None:
    """
    Generic release used on unexpected exceptions. Requeue the row by rotating it
    to the bottom so other rows can proceed, avoiding stalls.
    """
    with with_csv_lock(src_csv):
        df = _load_df(src_csv)
        if df.empty:
            return
        df = _ensure_common_columns(df)
        mask = df["WORKER"] == worker_name
        if not mask.any():
            return
        idx = df.index[mask][0]

        # Build merged row data with updates and clear WORKER
        merged = df.loc[idx].to_dict()
        merged.update({k: ("" if v is None else str(v)) for k, v in (updated or {}).items()})
        merged["WORKER"] = ""

        # Ensure all keys exist as columns
        for k in merged.keys():
            if k not in df.columns:
                df[k] = ""

        # Drop original and append to bottom
        df = df.drop(idx).reset_index(drop=True)
        df = pd.concat([df, pd.DataFrame([{c: merged.get(c, '') for c in df.columns}])], ignore_index=True)
        _save_df(df, src_csv)


def release_row_post_creation(src_csv: str, worker_name: str, updated: dict) -> None:
    """
    After running creation on a row, persist updates and route the row:
      - CREATION == '1' -> keep in place (it's finished and won't be picked again)
      - CREATION == '-1' -> drop permanently
      - any other value/empty -> rotate to bottom (requeue for later)
    """
    with with_csv_lock(src_csv):
        df = _load_df(src_csv)
        if df.empty:
            return
        df = _ensure_common_columns(df)
        mask = df["WORKER"] == worker_name
        if not mask.any():
            return
        idx = df.index[mask][0]
        status = str(updated.get("CREATION", "")).strip()

        # Merge fields from run into the current row snapshot
        merged = df.loc[idx].to_dict()
        merged.update({k: ("" if v is None else str(v)) for k, v in (updated or {}).items()})
        merged["WORKER"] = ""

        if status == "-1":
            # Permanent failure: drop row
            df = df.drop(idx).reset_index(drop=True)
            _save_df(df, src_csv)
            return

        # Ensure all keys exist as columns
        for k in merged.keys():
            if k not in df.columns:
                df[k] = ""

        if status == "1":
            # Success: write updates in-place and release
            for k, v in merged.items():
                if k not in df.columns:
                    df[k] = ""
                df.at[idx, k] = v
            _save_df(df, src_csv)
            return

        # Requeue: rotate to bottom
        df = df.drop(idx).reset_index(drop=True)
        df = pd.concat([df, pd.DataFrame([{c: merged.get(c, '') for c in df.columns}])], ignore_index=True)
        _save_df(df, src_csv)


# ---- worker loop -------------------------------------------------------------
def worker_loop(
    *,
    udid: str,
    src_csv: str,
    target_ddmm: str,
    label: str,
    row_func: Callable[[any, int, pd.Series, str, str], pd.DataFrame],
    get_driver: Callable[[str], any],
) -> Tuple[int, int]:
    """
    Returns (created_count, processed_count).
    """
    created = 0
    processed = 0
    drv = None
    try:
        drv = get_driver(udid)
        try:
            drv.update_settings({"newCommandTimeout": 1200})
        except Exception:
            pass

        while True:
            # health probe: ensure driver session is alive before claiming
            try:
                _ = drv.get_window_size()
            except Exception as e_probe:
                if _is_uia2_crash(e_probe):
                    try:
                        # no pool here; caller passes get_driver which may pool
                        drv = get_driver(udid)
                    except Exception:
                        return created, processed
            row, has = claim_next_for_creation(src_csv, label)
            if row is None:
                break
            tmp_path = f"{src_csv}.{udid}.tmp.csv"
            try:
                pd.DataFrame([row]).to_csv(tmp_path, index=False, encoding="utf-8")
                row_func(drv, 0, row, tmp_path, target_ddmm)
                out_df = _load_df(tmp_path)
                out_row = out_df.iloc[0].to_dict() if not out_df.empty else {}
                release_row_post_creation(src_csv, label, out_row)
                if str(out_row.get("CREATION", "")).strip() == "1":
                    created += 1
            except Exception as e:
                # If UiAutomator2 died, recreate driver and requeue row to bottom
                if _is_uia2_crash(e):
                    try:
                        drv = get_driver(udid)
                    except Exception:
                        pass
                # Best-effort release original row (rotate to bottom)
                try:
                    release_row_with_update(src_csv, label, row.to_dict())
                except Exception:
                    pass
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            # Restart app between rows to avoid stale state
            try:
                hard_reset_app(drv, APP_PACKAGE)
            except Exception:
                pass
            processed += 1
            time.sleep(0.05)
    finally:
        # keep driver alive for reuse in pool
        pass
    return created, processed


def run_creation_multidevice(
    *,
    udids: List[str],
    src_csv: str,
    target_ddmm: str,
    row_func: Callable[[any, int, pd.Series, str, str], pd.DataFrame],
    get_driver: Callable[[str], any],
) -> Tuple[int, int]:
    results: list[Tuple[int, int]] = [(0, 0)] * len(udids)

    def _runner(i: int, u: str):
        results[i] = worker_loop(
            udid=u,
            src_csv=src_csv,
            target_ddmm=target_ddmm,
            label=u,
            row_func=row_func,
            get_driver=get_driver,
        )

    threads: list[threading.Thread] = []
    for i, u in enumerate(udids):
        t = threading.Thread(target=_runner, args=(i, u), daemon=True, name=f"creation-{u}")
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    total_created = sum(c for c, _ in results)
    total_processed = sum(p for _, p in results)
    return total_created, total_processed
