# automation_web.py
from __future__ import annotations

import os
import re
import csv
import time
import json
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd # type: ignore
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from PyPDF2 import PdfMerger
import subprocess
import sys

import config

from workers import (
    DeviceWorker,
    CreationDeviceWorker,
    ConfirmationWorker,
    CombinedTarget,
    get_device_status_snapshot,
    list_connected_devices,
)

app = Flask(__name__)
app.secret_key = "changeme"  # replace in production


# =========================
# Helpers for paths & CSVs
# =========================

def _urlpath(*parts: str) -> str:
    return os.path.join(*parts).replace("\\", "/")


def _safe_headers() -> List[str]:
    headers = getattr(config, "FIELDNAMES", None)
    if isinstance(headers, list) and headers:
        return headers
    return [
        "NOM", "PRENOM", "PHONE",
        "CREATION", "RESERVATION",
        "gender", "email", "numero_tlf",
        "numero_passport", "numero_visa",
        "nationalite", "date_reservation", "heure"
    ]


def _ensure_csv(path: str, headers: List[str]):
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(headers)


def _count_rows(csv_path: str) -> int:
    total, _ = _count_rows_and_confirmed(csv_path)
    return total


def _count_rows_and_confirmed(csv_path: str) -> Tuple[int, int]:
    if not os.path.exists(csv_path):
        print("does not exist:", csv_path)
        return 0, 0
    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        total = int(len(df))
        confirmed = 0
        if total and "CONFIRMATION" in df.columns:
            confirm_mask = df["CONFIRMATION"].astype(str).str.strip() == "1"
            confirmed = int(confirm_mask.sum())
        return total, confirmed
    except Exception:
        return 0, 0


def _count_rows_needing_creation(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        return 0
    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        if df.empty:
            return 0
        col = df.get("CREATION")
        if col is None:
            return len(df)
        s = col.astype(str).str.strip()
        mask = ~s.isin(["1", "-1"])  # needs creation
        return int(mask.sum())
    except Exception:
        return 0


# =========================
# Date parsing from folder
# =========================

FOLDER_REGEX_CANON = r"^\d{2}_\d{2}__\d{4}$"     # MM_DD__YYYY
FOLDER_REGEX_SLASH = r"^\d{2}/\d{2}/\d{4}$"      # MM/DD/YYYY

def parse_target_date_from_folder(folder_name: str) -> Optional[str]:
    if re.match(FOLDER_REGEX_CANON, folder_name):
        mm, dd, yyyy = folder_name[:2], folder_name[3:5], folder_name[-4:]
        return f"{dd}/{mm}"
    if re.match(FOLDER_REGEX_SLASH, folder_name):
        mm, dd, yyyy = folder_name.split("/")
        return f"{dd}/{mm}"
    m = re.match(r"^(\d{2})\D+(\d{2})\D+(\d{4})$", folder_name)
    if m:
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}/{mm}"
    return None


# =========================
# CSV stats (global files)
# =========================

def get_csv_stats():
    csv_files = {
        "all": ("ALL", getattr(config, "ALL_CSV_PATH", "")),
        "hommes": ("HOMMES", getattr(config, "HOMMES_CSV_PATH", "")),
        "femmes": ("FEMMES", getattr(config, "FEMMES_CSV_PATH", "")),
    }
    stats = {}
    for key, (label, path) in csv_files.items():
        total = 0
        with_account = 0
        confirmed = 0
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str)
                total = len(df)
                if key != "all":
                    if "CREATION" in df.columns:
                        creation_col = pd.to_numeric(df["CREATION"], errors="coerce").fillna(0)
                        with_account = int((creation_col == 1).sum())
                    if "CONFIRMATION" in df.columns:
                        confirmation_col = pd.to_numeric(df["CONFIRMATION"], errors="coerce").fillna(0)
                        confirmed = int((confirmation_col == 1).sum())
            except Exception as e:
                print(f"Failed to read {path}: {e}")

        stats[key] = {"label": label, "total": total}
        if key != "all":
            stats[key]["with_account"] = with_account
            stats[key]["confirmed"] = confirmed
    return stats


# =========================
# Daily folders (MM_DD__YYYY)
# =========================

def _create_daily_folder_struct(folder_name: str):
    base_dir = config.BASE_DIR
    target = os.path.join(base_dir, folder_name)
    os.makedirs(target, exist_ok=True)

    headers = _safe_headers()
    _ensure_csv(os.path.join(target, "hommes.csv"), headers)
    _ensure_csv(os.path.join(target, "femmes.csv"), headers)

    os.makedirs(os.path.join(target, "hommes"), exist_ok=True)
    os.makedirs(os.path.join(target, "femmes"), exist_ok=True)


def get_daily_folders(sort_desc: bool = True):
    items = []
    base_dir = config.BASE_DIR
    if not os.path.isdir(base_dir):
        return items

    for name in os.listdir(base_dir):
        if not (re.match(FOLDER_REGEX_CANON, name) or re.match(FOLDER_REGEX_SLASH, name) or re.match(r"^\d{2}\D+\d{2}\D+\d{4}$", name)):
            continue

        abs_folder = os.path.join(base_dir, name)
        if not os.path.isdir(abs_folder):
            continue

        femmes_csv = os.path.join(abs_folder, "femmes.csv")
        hommes_csv = os.path.join(abs_folder, "hommes.csv")
        femmes_count, femmes_confirmed = _count_rows_and_confirmed(femmes_csv)
        hommes_count, hommes_confirmed = _count_rows_and_confirmed(hommes_csv)

        items.append({
            "folder": name,
            "women_count": femmes_count,
            "women_confirmed": femmes_confirmed,
            "men_count": hommes_count,
            "men_confirmed": hommes_confirmed,
            "mtime": os.path.getmtime(abs_folder),
            "subfolders": [
                {"name": "femmes", "path": _urlpath(name, "femmes")},
                {"name": "hommes", "path": _urlpath(name, "hommes")},
            ]
        })

    items.sort(key=lambda r: r["mtime"], reverse=sort_desc)
    return items


# =========================
# Batch registry (multi-batch) + queue
# =========================

@dataclass
class Batch:
    id: int
    folder: str
    gender: str  # "men" or "women"
    src_csv: str
    dest_csv: str
    target_ddmm: str
    total_target: int
    devices: List[str]
    screenshot_root: str = ""
    mode: str = "reservation"
    stop_event: threading.Event = field(default_factory=threading.Event)
    combined: CombinedTarget = field(default=None)
    threads: List[threading.Thread] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)

    @property
    def done(self) -> int:
        return int(self.combined.done if self.combined else 0)

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self.threads)


_batches: Dict[int, Batch] = {}
_batches_lock = threading.Lock()
_busy_devices: set[str] = set()
_next_batch_id = 1

# A very small, FIFO job queue for future batches
@dataclass
class QueuedJob:
    folder: str
    gender: str
    src_csv: str
    dest_csv: str
    target_ddmm: str
    total_target: int
    devices: List[str]
    screenshot_root: str = ""
    mode: str = "reservation"
    queued_ts: float = field(default_factory=time.time)

_job_queue: list[QueuedJob] = []  # FIFO


def _alloc_batch_id() -> int:
    global _next_batch_id
    with _batches_lock:
        bid = _next_batch_id
        _next_batch_id += 1
        return bid


def _mark_busy(udids: List[str]) -> None:
    """Mark devices busy.

    Caller must already hold `_batches_lock`.
    Avoid taking the same lock here to prevent self-deadlocks when called
    from within a `_batches_lock` critical section.
    """
    _busy_devices.update(udids)


def _mark_free(udids: List[str]) -> None:
    """Mark devices free.

    Caller must already hold `_batches_lock`.
    """
    for u in udids:
        _busy_devices.discard(u)


def _devices_available(udids: List[str]) -> bool:
    with _batches_lock:
        return all(u not in _busy_devices for u in udids)


def _start_batch(folder: str, gender: str, src_csv: str, dest_csv: str, target_ddmm: str, total_target: int, udids: List[str], *, mode: str = "reservation", screenshot_root: str = "") -> int:
    """Start a batch immediately (assumes devices are available). Returns batch id.

    mode: "reservation" -> DeviceWorker, "creation" -> CreationDeviceWorker
    """
    # Create batch
    batch_id = _alloc_batch_id()
    batch = Batch(
        id=batch_id,
        folder=folder,
        gender=gender,
        src_csv=src_csv,
        dest_csv=dest_csv,
        target_ddmm=target_ddmm,
        total_target=total_target,
        devices=udids,
        screenshot_root=screenshot_root,
        mode=mode,
        combined=CombinedTarget(total_target),
    )

    # Launch workers
    selected = [d for d in getattr(config, "DEVICES", []) if d.get("udid") in udids]
    for d in selected:
        udid = d["udid"]
        label = d.get("name") or udid
        if mode == "creation":
            t = CreationDeviceWorker(
                udid=udid,
                src_csv=src_csv,
                target_ddmm=target_ddmm,
                stop_event=batch.stop_event,
                combined_target=batch.combined,
                label=label,
                batch_id=batch_id,
            )
        elif mode == "confirmation":
            t = ConfirmationWorker(
                udid=udid,
                src_csv=src_csv,
                screenshot_root=screenshot_root or os.path.join(config.BASE_DIR, folder),
                stop_event=batch.stop_event,
                combined_target=batch.combined,
                label=label,
                batch_id=batch_id,
            )
        elif mode == "gender_sort":
            # NEW: sorter reads from ALL and routes to HOMMES/FEMMES
            from workers import GenderSortWorker  # local import
            t = GenderSortWorker(
                udid=udid,
                all_csv=getattr(config, "ALL_CSV_PATH", ""),
                hommes_csv=getattr(config, "HOMMES_CSV_PATH", ""),
                femmes_csv=getattr(config, "FEMMES_CSV_PATH", ""),
                target_ddmm=target_ddmm,
                stop_event=batch.stop_event,
                combined_target=batch.combined,
                label=label,
                batch_id=batch_id,
            )
        else:
            t = DeviceWorker(
                udid=udid,
                src_csv=src_csv,
                dest_csv=dest_csv,
                target_ddmm=target_ddmm,
                stop_event=batch.stop_event,
                combined_target=batch.combined,
                label=label,
                batch_id=batch_id,
            )
        t.start()
        batch.threads.append(t)


    with _batches_lock:
        _batches[batch_id] = batch
        _mark_busy(udids)
    return batch_id


def _reap_finished_batches() -> None:
    """Check for finished batches, free devices, and remove them."""
    finished: list[int] = []
    with _batches_lock:
        for bid, b in list(_batches.items()):
            if not b.running:  # all threads exited
                finished.append(bid)
                # free devices in same critical section
                _mark_free(b.devices)
    # perform cleanup actions (outside lock)
    for bid in finished:
        b = None
        with _batches_lock:
            b = _batches.pop(bid, None)
        if b:
            # Device-side cleanup
            for udid in b.devices:
                cleanup_device(udid)


def _dispatcher_loop():
    """Background loop: reaps finished batches and starts next queued jobs when devices are free."""
    while True:
        try:
            _reap_finished_batches()
            # Try to start next queued job (FIFO)
            job_to_start: Optional[QueuedJob] = None
            with _batches_lock:
                if _job_queue:
                    qj = _job_queue[0]
                    if all(u not in _busy_devices for u in qj.devices):
                        job_to_start = _job_queue.pop(0)
            if job_to_start:
                try:
                    _start_batch(
                        folder=job_to_start.folder,
                        gender=job_to_start.gender,
                        src_csv=job_to_start.src_csv,
                        dest_csv=job_to_start.dest_csv,
                        target_ddmm=job_to_start.target_ddmm,
                        total_target=job_to_start.total_target,
                        udids=job_to_start.devices,
                        mode=getattr(job_to_start, 'mode', 'reservation'),
                        screenshot_root=getattr(job_to_start, 'screenshot_root', ""),
                    )
                except Exception:
                    # Failed to launch; push back to queue tail for retry
                    with _batches_lock:
                        _job_queue.append(job_to_start)
        except Exception:
            pass
        time.sleep(1.0)


# =========================
# Routes
# =========================

@app.route("/", methods=["GET"])
def index():
    # Keep config.DEVICES fresh when AUTO_DEVICES=1
    try:
        if hasattr(config, "refresh_devices"):
            config.refresh_devices()
    except Exception:
        pass

    csv_stats = get_csv_stats()
    daily_folders = get_daily_folders()
    connected = {d["udid"]: d for d in list_connected_devices()}
    configured = getattr(config, "DEVICES", [])
    # Union of configured and connected, mark connected state
    seen = set()
    devices_for_form = []
    for d in configured:
        u = d.get("udid");  seen.add(u)
        label = connected.get(u, {}).get("name") or d.get("name") or u
        devices_for_form.append({"udid": u, "name": label, "connected": bool(u in connected)})
    # Add any extra connected devices not in config (still selectable)
    for u, d in connected.items():
        if u in seen:
            continue
        devices_for_form.append({"udid": u, "name": d.get("name") or u, "connected": True})
    return render_template(
        "index.html",
        csv_stats=csv_stats,
        daily_folders=daily_folders,
        devices=devices_for_form,
    )

@app.route("/sort_all_multi", methods=["POST"])
def sort_all_multi():
    try:
        udids = request.form.getlist("udid")
        if not udids:
            flash("Please select at least one device for ALL sorting.", "warning")
            return redirect(url_for("index"))

        all_csv = getattr(config, "ALL_CSV_PATH", None)
        hommes_csv = getattr(config, "HOMMES_CSV_PATH", None)
        femmes_csv = getattr(config, "FEMMES_CSV_PATH", None)
        if not all([all_csv, hommes_csv, femmes_csv]):
            flash("ALL/HOMMES/FEMMES CSV paths are not fully configured.", "danger")
            return redirect(url_for("index"))

        total_target = 0
        try:
            if os.path.exists(all_csv):
                df = pd.read_csv(all_csv, dtype=str, keep_default_na=False)
                if not df.empty:
                    s = df.get("CREATION")
                    if s is None:
                        total_target = len(df)
                    else:
                        mask = ~s.astype(str).str.strip().isin(["1", "-1"])
                        total_target = int(mask.sum())
        except Exception:
            total_target = 0

        if total_target <= 0:
            # Allow running anyway; the workers will stop when source is empty
            total_target = 999999

        # If selected devices are busy, enqueue this job instead of rejecting
        with _batches_lock:
            conflicts = [u for u in udids if u in _busy_devices]
        if conflicts:
            with _batches_lock:
                _job_queue.append(QueuedJob(
                    folder="ALL→H/F",
                    gender="both",
                    src_csv=all_csv,
                    dest_csv="",  # not used by sorter
                    target_ddmm=getattr(config, "TARGET_DATE", ""),
                    total_target=total_target,
                    devices=udids,
                    mode="gender_sort",
                ))
                pos = len(_job_queue)
            flash(f"Devices busy; ALL sort queued at position {pos}.", "info")
            return redirect(url_for("index"))

        # Start immediately
        batch_id = _start_batch(
            folder="ALL→H/F",
            gender="both",
            src_csv=all_csv,          # for display only
            dest_csv="",              # not used by sorter
            target_ddmm=getattr(config, "TARGET_DATE", ""),
            total_target=total_target,
            udids=udids,
            mode="gender_sort",
        )
        flash(f"Started ALL sorter batch #{batch_id} on {len(udids)} device(s).", "success")
    except Exception as e:
        flash(f"Sorting failed: {e}", "danger")
    return redirect(url_for("index"))

@app.route("/all/sort", methods=["POST"])
def all_sort():
    try:
        all_posix = Path(getattr(config, "ALL_CSV_PATH", "")).as_posix()
        if not all_posix:
            raise RuntimeError("ALL_CSV_PATH is not set in config.")
        # If your sort.py reads config.CSV_FILE, ensure it points to ALL:
        cfg_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(cfg_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"^CSV_FILE\s*=.*$", f"CSV_FILE = {all_posix!r}", content, flags=re.MULTILINE)
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(content)
        env = os.environ.copy()
        proc = subprocess.Popen([sys.executable, str(Path("sort.py"))], env=env)
        flash("Sorting completed (ALL → HOMMES/FEMMES).", "success")
    except Exception as e:
        flash(f"Sort failed: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/creation/hommes", methods=["POST"])
def run_creation_hommes():
    try:
        udids = request.form.getlist("udid")
        if not udids:
            flash("Please select at least one device for HOMMES creation.", "warning")
            return redirect(url_for("index"))
        src_csv = getattr(config, "HOMMES_CSV_PATH", None)
        if not src_csv:
            flash("HOMMES_CSV_PATH is not configured.", "danger")
            return redirect(url_for("index"))

        total_target = _count_rows_needing_creation(src_csv)
        if total_target <= 0:
            flash("No rows need creation in HOMMES.", "info")
            return redirect(url_for("index"))

        # Queue if busy
        with _batches_lock:
            conflicts = [u for u in udids if u in _busy_devices]
        if conflicts:
            with _batches_lock:
                _job_queue.append(QueuedJob(
                    folder="Creation",
                    gender="men",
                    src_csv=src_csv,
                    dest_csv=src_csv,
                    target_ddmm=getattr(config, "TARGET_DATE", ""),
                    total_target=total_target,
                    devices=udids,
                    mode="creation",
                ))
                pos = len(_job_queue)
            flash(f"Devices busy; creation queued at position {pos}.", "info")
            return redirect(url_for("index"))

        batch_id = _start_batch(
            folder="Creation",
            gender="men",
            src_csv=src_csv,
            dest_csv=src_csv,
            target_ddmm=getattr(config, "TARGET_DATE", ""),
            total_target=total_target,
            udids=udids,
            mode="creation",
        )
        flash(f"Started Creation batch #{batch_id} for HOMMES on {len(udids)} device(s).", "success")
    except Exception as e:
        flash(f"Creation failed: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/creation/femmes", methods=["POST"])
def run_creation_femmes():
    try:
        udids = request.form.getlist("udid")
        if not udids:
            flash("Please select at least one device for FEMMES creation.", "warning")
            return redirect(url_for("index"))
        src_csv = getattr(config, "FEMMES_CSV_PATH", None)
        if not src_csv:
            flash("FEMMES_CSV_PATH is not configured.", "danger")
            return redirect(url_for("index"))

        total_target = _count_rows_needing_creation(src_csv)
        if total_target <= 0:
            flash("No rows need creation in FEMMES.", "info")
            return redirect(url_for("index"))

        with _batches_lock:
            conflicts = [u for u in udids if u in _busy_devices]
        if conflicts:
            with _batches_lock:
                _job_queue.append(QueuedJob(
                    folder="Creation",
                    gender="women",
                    src_csv=src_csv,
                    dest_csv=src_csv,
                    target_ddmm=getattr(config, "TARGET_DATE", ""),
                    total_target=total_target,
                    devices=udids,
                    mode="creation",
                ))
                pos = len(_job_queue)
            flash(f"Devices busy; creation queued at position {pos}.", "info")
            return redirect(url_for("index"))

        batch_id = _start_batch(
            folder="Creation",
            gender="women",
            src_csv=src_csv,
            dest_csv=src_csv,
            target_ddmm=getattr(config, "TARGET_DATE", ""),
            total_target=total_target,
            udids=udids,
            mode="creation",
        )
        flash(f"Started Creation batch #{batch_id} for FEMMES on {len(udids)} device(s).", "success")
    except Exception as e:
        flash(f"Creation failed: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/add_daily_folder", methods=["POST"])
def add_daily_folder():
    base_dir = config.BASE_DIR
    os.makedirs(base_dir, exist_ok=True)

    date_str = request.form.get("target_date", "").strip()
    if not date_str:
        flash("Please choose a date before creating a folder.")
        return redirect(url_for("index"))

    try:
        chosen_dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date format. Please pick a date again.")
        return redirect(url_for("index"))

    folder_base = chosen_dt.strftime("%m_%d__%Y")
    candidate = folder_base
    n = 2
    while os.path.exists(os.path.join(base_dir, candidate)):
        candidate = f"{folder_base}-{n}"
        n += 1

    _create_daily_folder_struct(candidate)
    flash(f"Created {candidate} with hommes/femmes CSVs and subfolders.")
    return redirect(url_for("index"))


@app.route("/import_pdf", methods=["POST"])
def import_pdf():
    target = (request.form.get("target") or "ALL").upper()
    target_map = {
        "ALL":     getattr(config, "ALL_CSV_PATH", None),
        "HOMMES":  getattr(config, "HOMMES_CSV_PATH", None),
        "FEMMES":  getattr(config, "FEMMES_CSV_PATH", None),
    }
    csv_target = target_map.get(target)
    if not csv_target:
        flash("Invalid target selection.", "danger")
        return redirect(url_for("index"))

    file = request.files.get("pdf")
    if not file or not file.filename.lower().endswith(".pdf"):
        flash("Please select a PDF file.", "danger")
        return redirect(url_for("index"))

    try:
        inbox_dir = os.path.join(config.BASE_DIR, "_inbox")
        os.makedirs(inbox_dir, exist_ok=True)
        save_path = os.path.join(inbox_dir, file.filename)
        file.save(save_path)

        csv_posix = Path(csv_target).as_posix()
        pdf_posix = Path(save_path).as_posix()

        env = os.environ.copy()
        env["CSV_FILE_OVERRIDE"] = csv_posix
        env["PDF_FILE_OVERRIDE"] = pdf_posix

        # Run pdf.py with the current Python interpreter and capture output
        proc = subprocess.run(
            [sys.executable, str(Path("pdf.py"))],
            capture_output=True,
            text=True,
            env=env,
        )
        # Echo to server console for debugging
        if proc.stdout:
            print("[pdf.py stdout]", proc.stdout)
        if proc.stderr:
            print("[pdf.py stderr]", proc.stderr)

        if proc.returncode == 0:
            flash(f"Imported {file.filename} into {target}.", "success")
        else:
            err = proc.stderr.strip() or "Unknown error"
            flash(f"Import failed (pdf.py exit {proc.returncode}): {err}", "danger")

    except Exception as e:
        flash(f"Import failed: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/merge_pdfs", methods=["POST"])
def merge_pdfs():
    files = request.files.getlist("pdfs")
    if not files or all(f.filename == "" for f in files):
        flash("No PDF files selected.")
        return redirect(url_for("index"))

    merger = PdfMerger()
    for f in files:
        if f and f.filename.lower().endswith(".pdf"):
            merger.append(f)

    merged = BytesIO()
    merger.write(merged)
    merger.close()
    merged.seek(0)

    return send_file(
        merged,
        as_attachment=True,
        download_name="merged.pdf",
        mimetype="application/pdf",
    )


# ---------- Batch launch ----------
@app.route("/run_batch_multi", methods=["POST"])
def run_batch_multi():
    # Keep devices fresh (autopopulate) before resolving selections
    try:
        if hasattr(config, "refresh_devices"):
            config.refresh_devices()
    except Exception:
        pass
    folder = (request.form.get("folder") or "").strip()
    gender = (request.form.get("gender") or "").strip()  # "men" or "women"
    try:
        total_target = int(request.form.get("count", "1").strip() or "1")
        total_target = max(1, total_target)
    except Exception:
        total_target = 1

    target_ddmm = parse_target_date_from_folder(folder)
    if not target_ddmm:
        flash("Invalid folder name for target date.", "danger")
        return redirect(url_for("index"))

    if gender not in {"men", "women"}:
        flash("Please select a valid gender: men or women.", "danger")
        return redirect(url_for("index"))

    src_csv = getattr(config, "HOMMES_CSV_PATH", "") if gender == "men" else getattr(config, "FEMMES_CSV_PATH", "")
    dest_csv = os.path.join(config.BASE_DIR, folder, "hommes.csv" if gender == "men" else "femmes.csv")
    _ensure_csv(dest_csv, _safe_headers())

    # Selected devices
    selected_udids = request.form.getlist("devices")
    all_devices = getattr(config, "DEVICES", [])
    selected = [d for d in all_devices if d.get("udid") in selected_udids]
    udids = [d.get("udid") for d in selected if d.get("udid")]

    if not udids:
        flash("Please select at least one device.", "danger")
        return redirect(url_for("index"))

    # If selected devices are busy, enqueue this job instead of rejecting
    with _batches_lock:
        conflicts = [u for u in udids if u in _busy_devices]
    if conflicts:
        with _batches_lock:
            _job_queue.append(QueuedJob(
                folder=folder,
                gender=gender,
                src_csv=src_csv,
                dest_csv=dest_csv,
                target_ddmm=target_ddmm,
                total_target=total_target,
                devices=udids,
            ))
            pos = len(_job_queue)
        flash(f"Devices busy; job queued at position {pos}. It will start automatically when devices free.", "info")
        return redirect(url_for("index"))

    # Create batch
    batch_id = _alloc_batch_id()
    batch = Batch(
        id=batch_id,
        folder=folder,
        gender=gender,
        src_csv=src_csv,
        dest_csv=dest_csv,
        target_ddmm=target_ddmm,
        total_target=total_target,
        devices=udids,
        combined=CombinedTarget(total_target),
    )

    # Launch workers
    for d in selected:
        udid = d["udid"]
        label = d.get("name") or udid
        t = DeviceWorker(
            udid=udid,
            src_csv=src_csv,
            dest_csv=dest_csv,
            target_ddmm=target_ddmm,
            stop_event=batch.stop_event,
            combined_target=batch.combined,
            label=label,
            batch_id=batch_id,
        )
        t.start()
        batch.threads.append(t)

    with _batches_lock:
        _batches[batch_id] = batch
        _mark_busy(udids)

    flash(f"Started batch #{batch_id}: {total_target} target → {folder} [{gender}] on {len(udids)} device(s).", "success")
    return redirect(url_for("index"))


# ---------- Stop a specific batch ----------

@app.route("/run_confirmation_multi", methods=["POST"])
def run_confirmation_multi():
    try:
        if hasattr(config, "refresh_devices"):
            config.refresh_devices()
    except Exception:
        pass

    folder = (request.form.get("folder") or "").strip()
    gender = (request.form.get("gender") or "").strip()

    if not folder:
        flash("Folder is required for confirmation runs.", "danger")
        return redirect(url_for("index"))
    if gender not in {"men", "women"}:
        flash("Please select a valid gender: men or women.", "danger")
        return redirect(url_for("index"))

    base_folder = os.path.join(config.BASE_DIR, folder)
    src_csv = os.path.join(base_folder, "hommes.csv" if gender == "men" else "femmes.csv")
    screenshot_root = base_folder

    if not os.path.exists(src_csv):
        flash(f"CSV not found for {gender} in {folder}.", "danger")
        return redirect(url_for("index"))

    try:
        requested_count = int((request.form.get("count") or "0").strip() or "0")
        if requested_count < 0:
            requested_count = 0
    except Exception:
        requested_count = 0

    pending_count = 0
    try:
        df = pd.read_csv(src_csv, dtype=str, keep_default_na=False)
        if not df.empty:
            conf = df.get("CONFIRMATION")
            res = df.get("RESERVATION")
            conf_mask = conf.astype(str).str.strip() if conf is not None else pd.Series([""] * len(df))
            res_mask = res.astype(str).str.strip() if res is not None else pd.Series(["1"] * len(df))
            needs_confirm = (res_mask != "0") & (conf_mask != "1")
            pending_count = int(needs_confirm.sum())
    except Exception:
        pending_count = 0

    if pending_count <= 0:
        flash("No reservations pending confirmation for this selection.", "info")
        return redirect(url_for("index"))

    total_target = requested_count if requested_count > 0 else pending_count
    total_target = min(total_target, pending_count)

    selected_udids = request.form.getlist("devices")
    all_devices = getattr(config, "DEVICES", [])
    selected = [d for d in all_devices if d.get("udid") in selected_udids]
    udids = [d.get("udid") for d in selected if d.get("udid")]

    if not udids:
        flash("Please select at least one device.", "danger")
        return redirect(url_for("index"))

    target_ddmm = parse_target_date_from_folder(folder) or ""

    with _batches_lock:
        conflicts = [u for u in udids if u in _busy_devices]
    if conflicts:
        with _batches_lock:
            _job_queue.append(QueuedJob(
                folder=folder,
                gender=gender,
                src_csv=src_csv,
                dest_csv=src_csv,
                target_ddmm=target_ddmm,
                total_target=total_target,
                devices=udids,
                screenshot_root=screenshot_root,
                mode="confirmation",
            ))
            pos = len(_job_queue)
        flash(f"Devices busy; confirmation job queued at position {pos}.", "info")
        return redirect(url_for("index"))

    batch_id = _start_batch(
        folder=folder,
        gender=gender,
        src_csv=src_csv,
        dest_csv=src_csv,
        target_ddmm=target_ddmm,
        total_target=total_target,
        udids=udids,
        mode="confirmation",
        screenshot_root=screenshot_root,
    )

    flash(
        f"Started confirmation batch #{batch_id}: {total_target} target(s) for {folder} [{gender}] on {len(udids)} device(s).",
        "success",
    )
    return redirect(url_for("index"))

@app.route("/stop_batch_multi/<int:batch_id>", methods=["POST"])
def stop_batch_multi(batch_id: int):
    batch = None
    with _batches_lock:
        batch = _batches.get(batch_id)
    if not batch:
        flash(f"Batch #{batch_id} not found.", "warning")
        return redirect(url_for("index"))

    # Signal and join
    batch.stop_event.set()
    for t in batch.threads:
        try:
            t.join(timeout=5)
        except Exception:
            pass

    # Cleanup device side
    for udid in batch.devices:
        cleanup_device(udid)

    # Free and remove
    with _batches_lock:
        _mark_free(batch.devices)
        _batches.pop(batch_id, None)

    flash(f"Stopped batch #{batch_id}.", "info")
    return redirect(url_for("index"))


# ---------- Status JSON (batches + per-device) ----------
@app.route("/status")
def status():
    with _batches_lock:
        batches = []
        for b in _batches.values():
            batches.append({
                "id": b.id,
                "folder": b.folder,
                "gender": b.gender,
                "mode": getattr(b, "mode", "reservation"),
                "target": b.total_target,
                "done": b.done,
                "devices": b.devices,
                "running": b.running,
                "created_ts": b.created_ts,
            })
        queue = [
            {
                "folder": q.folder,
                "gender": q.gender,
                "mode": getattr(q, "mode", "reservation"),
                "target": q.total_target,
                "devices": q.devices,
                "queued_ts": q.queued_ts,
            }
            for q in _job_queue
        ]
    devices = get_device_status_snapshot()
    return jsonify({
        "running": any(b.get("running") for b in batches),
        "current_step": f"{len(batches)} active batch(es)",
        "batches": batches,
        "queue": queue,
        "devices": devices,
    })


@app.route("/files/<path:filename>")
def serve_file(filename):
    return send_from_directory(config.BASE_DIR, filename)


# ---------- ADB helpers & cleanup ----------
import subprocess
import atexit

def _adb(udid: str, *cmd: str) -> None:
    try:
        subprocess.run(
            ["adb", "-s", udid, *cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

def cleanup_device(udid: str):
    # close cached driver if your config pools it
    try:
        if hasattr(config, "reset_driver"):
            config.reset_driver(udid)
    except Exception:
        pass

    _adb(udid, "shell", "am", "force-stop", "io.appium.uiautomator2.server")
    _adb(udid, "shell", "am", "force-stop", "io.appium.uiautomator2.server.test")
    _adb(udid, "forward", "--remove-all")
    _adb(udid, "shell", "am", "force-stop", getattr(config, "APP_PACKAGE", "com.moh.nusukapp"))

def cleanup_all_devices():
    devs = getattr(config, "DEVICES", [])
    for d in devs:
        udid = d.get("udid")
        if udid:
            cleanup_device(udid)

@atexit.register
def _on_exit_cleanup():
    try:
        cleanup_all_devices()
    except Exception:
        pass


if __name__ == "__main__":
    # Launch dispatcher thread once
    try:
        _dispatcher = threading.Thread(target=_dispatcher_loop, name="dispatcher", daemon=True)
        _dispatcher.start()
    except Exception:
        pass
    app.run(debug=False, threaded=True)

