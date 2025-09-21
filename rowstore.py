# rowstore.py
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Optional, Tuple, Dict

import pandas as pd

try:
    import portalocker  # pip install portalocker
except Exception:  # very last resort – runs without locking
    portalocker = None


@contextmanager
def with_csv_lock(path: str, timeout: int = 30):
    """
    Cross-platform file lock using portalocker.
    If portalocker is missing, this becomes a no-op (not ideal but keeps you running).
    """
    lock_file = f"{path}.lock"
    if portalocker is None:
        yield
        return

    lock = portalocker.Lock(lock_file, timeout=timeout)
    with lock:
        yield


def load_df(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def save_df(df: pd.DataFrame, path: str):
    df.to_csv(path, index=False, encoding="utf-8")


def pop_first_row(path: str) -> Tuple[Optional[pd.Series], pd.DataFrame]:
    """
    Atomically remove and return the FIRST row, saving the remainder back.
    Returns (row, rest_df). If empty: (None, empty_df).
    """
    with with_csv_lock(path):
        df = load_df(path)
        if df.empty:
            return None, df
        row = df.iloc[0]
        rest = df.drop(df.index[0]).reset_index(drop=True)
        save_df(rest, path)
        return row, rest


def rotate_row_to_bottom(path: str, row_dict: Dict[str, str]):
    """
    Atomically append a row_dict to the bottom of the CSV,
    aligning columns both ways.
    """
    with with_csv_lock(path):
        df = load_df(path)
        row_df = pd.DataFrame([row_dict])
        # align columns both ways
        for c in df.columns:
            if c not in row_df.columns:
                row_df[c] = ""
        for c in row_df.columns:
            if c not in df.columns:
                df[c] = ""
        row_df = row_df[df.columns]
        new_df = pd.concat([df, row_df], ignore_index=True)
        save_df(new_df, path)


def append_row_dict(path: str, row_dict: Dict[str, str]):
    """
    Atomically append a row_dict; creates file if needed.
    """
    with with_csv_lock(path):
        df = load_df(path)
        if df.empty:
            # start with row's keys as columns
            df = pd.DataFrame(columns=list(row_dict.keys()))
        row_df = pd.DataFrame([row_dict])
        # align both ways
        for c in df.columns:
            if c not in row_df.columns:
                row_df[c] = ""
        for c in row_df.columns:
            if c not in df.columns:
                df[c] = ""
        row_df = row_df[df.columns]
        new_df = pd.concat([df, row_df], ignore_index=True)
        save_df(new_df, path)


def claim_next_row(path: str, worker_name: str) -> Tuple[Optional[pd.Series], bool]:
    """
    Find the first row whose WORKER is either this worker's name (resume)
    or empty (new), mark it with this worker's name, and return it.

    Returns (row, has_rows) where row is the claimed Series or None,
    and has_rows indicates whether the CSV had any rows at all.
    """
    with with_csv_lock(path):
        df = load_df(path)
        if df.empty:
            return None, False

        if "WORKER" not in df.columns:
            df["WORKER"] = ""

        # Normalize values to robustly compare (handle NaN/whitespace)
        worker_col = df["WORKER"].astype(str).str.strip().fillna("")

        mask_own   = worker_col == worker_name
        mask_empty = worker_col == ""

        # Prefer resuming your own previously claimed row; otherwise take an empty one
        if mask_own.any():
            idx = df.index[mask_own][0]
        elif mask_empty.any():
            idx = df.index[mask_empty][0]
        else:
            # there are rows, but none are resumable or empty
            return None, True

        df.at[idx, "WORKER"] = worker_name
        save_df(df, path)
        return df.loc[idx], True


def finalize_row(
    path: str,
    worker_name: str,
    row_dict: Dict[str, str],
    *,
    requeue: bool = False,
):
    """
    Remove the row currently claimed by ``worker_name``. If ``requeue`` is
    True, append ``row_dict`` back to the bottom (with WORKER cleared).
    ``row_dict`` should contain the most up-to-date data for that row.
    """
    with with_csv_lock(path):
        df = load_df(path)
        if "WORKER" not in df.columns:
            return

        mask = df["WORKER"] == worker_name
        if not mask.any():
            return

        idx = df.index[mask][0]
        df = df.drop(idx).reset_index(drop=True)

        if requeue:
            # ensure WORKER column exists and is cleared
            row_dict = dict(row_dict)
            row_dict["WORKER"] = ""
            row_df = pd.DataFrame([row_dict])
            for c in df.columns:
                if c not in row_df.columns:
                    row_df[c] = ""
            for c in row_df.columns:
                if c not in df.columns:
                    df[c] = ""
            row_df = row_df[df.columns]
            df = pd.concat([df, row_df], ignore_index=True)

        save_df(df, path)
