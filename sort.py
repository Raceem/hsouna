from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import List, Dict
import subprocess
import pandas as pd
from config import ALL_CSV_PATH, HOMMES_CSV_PATH, FEMMES_CSV_PATH, DEVICES

# logging
LOG = logging.getLogger("sort")
if not LOG.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

# CSV helpers
def _load_df(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()

def _save_df(df: pd.DataFrame, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")

def _append_row(dest_csv: str, row: dict) -> None:
    Path(dest_csv).parent.mkdir(parents=True, exist_ok=True)
    if not os.path.exists(dest_csv):
        _save_df(pd.DataFrame([row]), dest_csv)
        return
    existing = _load_df(dest_csv)
    for c in row.keys():
        if c not in existing.columns:
            existing[c] = ""
    for c in existing.columns:
        row.setdefault(c, "")
    existing = pd.concat([existing, pd.DataFrame([row])[existing.columns]], ignore_index=True)
    _save_df(existing, dest_csv)

def _normalize_gender(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"h", "m", "homme", "male", "man", "masculin"}:
        return "H"
    if s in {"f", "femme", "female", "woman", "feminin"}:
        return "F"
    return None

def select_devices_ui() -> List[str]:
    udids = [d.get("udid") for d in (DEVICES or []) if d.get("udid")]
    labels = [(d.get("name") or u) + f" ({u})" for d in (DEVICES or []) for u in [d.get("udid")] if u]
    try:
        import tkinter as tk
        from tkinter import ttk
        sel: List[str] = []
        root = tk.Tk()
        root.title("Select Phones")
        lb = tk.Listbox(root, selectmode=tk.EXTENDED, width=60, height=10)
        for it in labels:
            lb.insert(tk.END, it)
        lb.pack(padx=10, pady=10)
        btns = ttk.Frame(root); btns.pack(padx=10, pady=(0,10), fill="x")
        def ok():
            for i in lb.curselection():
                sel.append(udids[i])
            root.destroy()
        def all_():
            lb.select_set(0, tk.END)
        ttk.Button(btns, text="Select All", command=all_).pack(side="left")
        ttk.Button(btns, text="Start", command=ok).pack(side="right")
        root.mainloop()
        LOG.info("Selected devices: %s", ", ".join(sel) if sel else "<none>")
        return sel
    except Exception as e:
        LOG.info("UI not available (%s); continuing without selection.", e)
        return udids

def sort_all_by_gender(all_csv: str, hommes_csv: str, femmes_csv: str) -> dict:
    df = _load_df(all_csv)
    if df.empty:
        return {"total": 0, "hommes": 0, "femmes": 0, "unknown": 0}
    hommes = femmes = unknown = 0
    keep_rows = []
    for _, row in df.iterrows():
        g = _normalize_gender(row.get("gender"))
        if g == "H":
            _append_row(hommes_csv, row.to_dict()); hommes += 1
        elif g == "F":
            _append_row(femmes_csv, row.to_dict()); femmes += 1
        else:
            keep_rows.append(row); unknown += 1
    _save_df(pd.DataFrame(keep_rows), all_csv)
    return {"total": int(len(df)), "hommes": hommes, "femmes": femmes, "unknown": unknown}

def main():
    all_csv = os.getenv("CSV_FILE_OVERRIDE", ALL_CSV_PATH)
    _ = select_devices_ui()
    stats = sort_all_by_gender(all_csv, HOMMES_CSV_PATH, FEMMES_CSV_PATH)
    LOG.info("Sorted: total=%d, hommes=%d, femmes=%d, unknown/left=%d", stats["total"], stats["hommes"], stats["femmes"], stats["unknown"])

if __name__ == "__main__":
    main()