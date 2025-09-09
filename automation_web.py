# automation_web.py
from __future__ import annotations

import os
import re
import csv
import threading
from typing import List, Optional
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
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

import automation
import config
from workers import DeviceWorker  # NEW: multi-device workers


app = Flask(__name__)
app.secret_key = "changeme"  # replace in production


# =========================
# Helpers for paths & CSVs
# =========================

def _urlpath(*parts: str) -> str:
    """Join path parts and normalize to forward slashes for URLs."""
    return os.path.join(*parts).replace("\\", "/")


def _safe_headers() -> List[str]:
    """
    Prefer config.FIELDNAMES if present; otherwise a safe default
    (includes CREATION/RESERVATION which your scripts use).
    """
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
    """Create a CSV with headers if it does not exist."""
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)


def _count_rows(csv_path: str) -> int:
    """Count data rows (excluding header) for a CSV if it exists."""
    if not os.path.exists(csv_path):
        return 0
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except Exception as e:
        print(f"Failed to count rows in {csv_path}: {e}")
        return 0


# =========================
# Date parsing from folder
# =========================

FOLDER_REGEX_CANON = r"^\d{2}_\d{2}__\d{4}$"     # MM_DD__YYYY (canonical)
FOLDER_REGEX_SLASH = r"^\d{2}/\d{2}/\d{4}$"      # MM/DD/YYYY (tolerated)

def parse_target_date_from_folder(folder_name: str) -> Optional[str]:
    """
    Accepts:
      - MM_DD__YYYY
      - MM/DD/YYYY
    Returns TARGET_DATE as 'DD/MM' (string), or None if unparseable.
    """
    if re.match(FOLDER_REGEX_CANON, folder_name):
        mm, dd, yyyy = folder_name[:2], folder_name[3:5], folder_name[-4:]
        return f"{dd}/{mm}"
    if re.match(FOLDER_REGEX_SLASH, folder_name):
        mm, dd, yyyy = folder_name.split("/")
        return f"{dd}/{mm}"
    # Try tolerant extractor (any non-digit delimiter; accept double underscore)
    m = re.match(r"^(\d{2})\D+(\d{2})\D+(\d{4})$", folder_name)
    if m:
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}/{mm}"
    return None


def _set_config_var(var: str, value_literal: str) -> None:
    """
    Edit config.py, setting a top-level assignment: VAR = <value_literal>.
    Keeps other lines intact. Creates the var if missing.
    """
    cfg_path = os.path.join(os.path.dirname(__file__), "config.py")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"config.py not found at {cfg_path}")

    pattern = rf"^{var}\s*=.*$"
    new_line = f"{var} = {value_literal}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += new_line + "\n"

    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(content)






# =========================
# CSV stats (global files)
# =========================

def get_csv_stats():
    """
    Collect basic statistics about configured CSV files.
    """
    csv_files = {
        "all": ("ALL", config.ALL_CSV_PATH),
        "hommes": ("HOMMES", config.HOMMES_CSV_PATH),
        "femmes": ("FEMMES", config.FEMMES_CSV_PATH),
    }

    stats = {}
    for key, (label, path) in csv_files.items():
        total = 0
        with_account = 0
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str)
                total = len(df)
                if key != "all" and "CREATION" in df.columns:
                    creation_col = pd.to_numeric(df["CREATION"], errors="coerce").fillna(0)
                    with_account = int((creation_col == 1).sum())
            except Exception as e:
                print(f"Failed to read {path}: {e}")

        stats[key] = {"label": label, "total": total}
        if key != "all":
            stats[key]["with_account"] = with_account

    return stats


# =========================
# Daily folders (MM_DD__YYYY)
# =========================

def _create_daily_folder_struct(folder_name: str):
    """
    Create:
      BASE_DIR/folder_name/
        hommes.csv
        femmes.csv
        hommes/
        femmes/
    """
    base_dir = config.BASE_DIR
    target = os.path.join(base_dir, folder_name)
    os.makedirs(target, exist_ok=True)

    headers = _safe_headers()
    _ensure_csv(os.path.join(target, "hommes.csv"), headers)
    _ensure_csv(os.path.join(target, "femmes.csv"), headers)

    os.makedirs(os.path.join(target, "hommes"), exist_ok=True)
    os.makedirs(os.path.join(target, "femmes"), exist_ok=True)


def get_daily_folders(sort_desc: bool = True):
    """
    List only folders with name MM_DD__YYYY (we also tolerate slash-name folders),
    and show femmes/hommes line counts from sub-CSV files.
    """
    items = []
    base_dir = config.BASE_DIR
    if not os.path.isdir(base_dir):
        return items

    for name in os.listdir(base_dir):
        # Filter to plausible date folders
        if not (re.match(FOLDER_REGEX_CANON, name) or re.match(FOLDER_REGEX_SLASH, name) or re.match(r"^\d{2}\D+\d{2}\D+\d{4}$", name)):
            continue

        abs_folder = os.path.join(base_dir, name)
        if not os.path.isdir(abs_folder):
            continue

        femmes_csv = os.path.join(abs_folder, "femmes.csv")
        hommes_csv = os.path.join(abs_folder, "hommes.csv")
        femmes_count = _count_rows(femmes_csv)
        hommes_count = _count_rows(hommes_csv)

        items.append({
            "folder": name,
            "women_count": femmes_count,
            "men_count": hommes_count,
            "mtime": os.path.getmtime(abs_folder),
            "subfolders": [
                {"name": "femmes", "path": _urlpath(name, "femmes")},
                {"name": "hommes", "path": _urlpath(name, "hommes")},
            ]
        })

    items.sort(key=lambda r: r["mtime"], reverse=sort_desc)
    return items


# =========================
# Routes
# =========================

@app.route("/", methods=["GET"])
def index():
    status = automation.get_status()
    csv_stats = get_csv_stats()
    daily_folders = get_daily_folders()
    return render_template(
        "index.html",
        status=status,
        csv_stats=csv_stats,
        daily_folders=daily_folders
    )

@app.route("/all/sort", methods=["POST"])
def all_sort():
    # block if something else is running
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))

    try:
        # Ensure sort.py reads from ALL.csv (use forward slashes)
        all_posix = Path(config.ALL_CSV_PATH).as_posix()
        _set_config_var("CSV_FILE", repr(all_posix))

        # If your sort.py expects explicit output paths in config, you can also enforce:
        # _set_config_var("HOMMES_CSV_PATH", repr(Path(config.HOMMES_CSV_PATH).as_posix()))
        # _set_config_var("FEMMES_CSV_PATH", repr(Path(config.FEMMES_CSV_PATH).as_posix()))

        # Run sort.py (it should mutate ALL/HOMMES/FEMMES as per your script)
        automation.run_step("sort.py", "Sort ALL into HOMMES/FEMMES via sort.py")
        flash("Sorting completed (ALL → HOMMES/FEMMES).", "success")

    except Exception as e:
        flash(f"Sort failed: {e}", "danger")

    return redirect(url_for("index"))

@app.route("/creation/hommes", methods=["POST"])
def run_creation_hommes():
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))
    try:
        csv_posix = Path(config.HOMMES_CSV_PATH).as_posix()
        os.environ["CSV_FILE_OVERRIDE"] = csv_posix
        try:
            automation.run_step("Creation.py", "Run Creation.py on HOMMES")
            flash("Started Creation.py for HOMMES.", "success")
        finally:
            os.environ.pop("CSV_FILE_OVERRIDE", None)
    except Exception as e:
        flash(f"Creation failed: {e}", "danger")
    return redirect(url_for("index"))

@app.route("/creation/femmes", methods=["POST"])
def run_creation_femmes():
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))
    try:
        csv_posix = Path(config.FEMMES_CSV_PATH).as_posix()
        os.environ["CSV_FILE_OVERRIDE"] = csv_posix
        try:
            automation.run_step("Creation.py", "Run Creation.py on FEMMES")
            flash("Started Creation.py for FEMMES.", "success")
        finally:
            os.environ.pop("CSV_FILE_OVERRIDE", None)
    except Exception as e:
        flash(f"Creation failed: {e}", "danger")
    return redirect(url_for("index"))

# ===== REMOVED: old /run_batch men/women route =====


@app.route("/add_daily_folder", methods=["POST"])
def add_daily_folder():
    """
    Create a folder using a user-chosen date (YYYY-MM-DD).
    Folder name becomes MM_DD__YYYY. If exists, append -2, -3, ...
    """
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
    # block if something else is running
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))

    # read selection
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

    # read file
    file = request.files.get("pdf")
    if not file or not file.filename.lower().endswith(".pdf"):
        flash("Please select a PDF file.", "danger")
        return redirect(url_for("index"))

    try:
        # Save PDF into BASE_DIR/_inbox/<filename>
        inbox_dir = os.path.join(config.BASE_DIR, "_inbox")
        os.makedirs(inbox_dir, exist_ok=True)
        save_path = os.path.join(inbox_dir, file.filename)
        file.save(save_path)

        # Use POSIX (forward slashes) to avoid \a issues on Windows
        csv_posix = Path(csv_target).as_posix()
        pdf_posix = Path(save_path).as_posix()

        # Run pdf.py with environment overrides instead of editing config.py
        os.environ["CSV_FILE_OVERRIDE"] = csv_posix
        os.environ["PDF_FILE_OVERRIDE"] = pdf_posix
        try:
            automation.run_step("pdf.py", f"Import PDF into {target} via pdf.py")
            flash(f"Imported {file.filename} into {target}.", "success")
        finally:
            os.environ.pop("CSV_FILE_OVERRIDE", None)
            os.environ.pop("PDF_FILE_OVERRIDE", None)

    except Exception as e:
        flash(f"Import failed: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/merge_pdfs", methods=["POST"])
def merge_pdfs():
    """Merge uploaded PDF files into a single document for download."""
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


@app.route("/status")
def status():
    return jsonify(automation.get_status())


# ===== NEW: Multi-device batch control =====

_active_batch = {"stop": None, "threads": []}

@app.route("/run_batch_multi", methods=["POST"])
def run_batch_multi():
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))

    folder = (request.form.get("folder") or "").strip()
    gender = (request.form.get("gender") or "").strip()  # "men" or "women"
    try:
        per_device_target = request.form.get("per_device_target", "").strip()
        per_device_target = int(per_device_target) if per_device_target else None
    except Exception:
        per_device_target = None

    target_ddmm = parse_target_date_from_folder(folder)
    if not target_ddmm:
        flash("Invalid folder name for target date.", "danger")
        return redirect(url_for("index"))

    if gender not in {"men", "women"}:
        flash("Please select a valid gender: men or women.", "danger")
        return redirect(url_for("index"))

    src_csv = config.HOMMES_CSV_PATH if gender == "men" else config.FEMMES_CSV_PATH
    dest_csv = os.path.join(config.BASE_DIR, folder, "hommes.csv" if gender == "men" else "femmes.csv")
    _ensure_csv(dest_csv, _safe_headers())

    devices = getattr(config, "DEVICES", [])
    if not devices:
        flash("No devices configured in config.DEVICES.", "danger")
        return redirect(url_for("index"))

    stop_event = threading.Event()
    _active_batch["stop"] = stop_event
    _active_batch["threads"] = []

    # mark running for UI
    try:
        automation._STATE.set_running(True)
        automation._STATE.set_step("multi-device batch", f"{len(devices)} device(s) → {folder} ({gender})")
    except Exception:
        pass

    # spin a worker per device
    for d in devices:
        udid = d.get("udid")
        name = d.get("name") or udid
        t = DeviceWorker(
            udid=udid,
            src_csv=src_csv,
            dest_csv=dest_csv,
            target_ddmm=target_ddmm,
            stop_event=stop_event,
            success_target=per_device_target,
            label=f"{name or udid}",
        )
        t.start()
        _active_batch["threads"].append(t)

    flash(f"Started multi-device batch on {len(devices)} device(s) → {folder} [{gender}].", "success")
    return redirect(url_for("index"))

@app.route("/stop_batch_multi", methods=["POST"])
def stop_batch_multi():
    # 1) Signal threads to stop
    if _active_batch["stop"]:
        _active_batch["stop"].set()
        for t in _active_batch["threads"]:
            try:
                t.join(timeout=5)
            except Exception:
                pass
        _active_batch["stop"] = None
        _active_batch["threads"] = []

    # 2) Ensure device-side & cached-driver cleanup (prevents zombie UIA2)
    try:
        devices = getattr(config, "DEVICES", [])
        for d in devices:
            udid = d.get("udid")
            if udid:
                cleanup_device(udid)
    except Exception:
        pass

    # 3) Clear UI status
    try:
        automation._STATE.set_running(False)
        automation._STATE.set_step("idle", "")
    except Exception:
        pass

    flash("Multi-device batch stopped and devices cleaned.", "info")
    return redirect(url_for("index"))
# ===== existing pause (for old child-proc flows) kept as-is =====
@app.route("/pause", methods=["POST"])
def pause():
    ok = automation.cancel_current()
    flash("Pipeline cancelled." if ok else "No running pipeline.")
    return redirect(url_for("index"))


@app.route("/files/<path:filename>")
def serve_file(filename):
    return send_from_directory(config.BASE_DIR, filename)

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
    """
    Hard reset device-side automation state:
      - close any Appium driver we have
      - kill UIA2 server & test apks
      - remove any forwarded ports
      - stop AUT just in case
    """
    # 1) Drop cached driver (from config.py pool)
    try:
        if hasattr(config, "reset_driver"):
            config.reset_driver(udid)
    except Exception:
        pass

    # 2) Kill UiAutomator2 servers
    _adb(udid, "shell", "am", "force-stop", "io.appium.uiautomator2.server")
    _adb(udid, "shell", "am", "force-stop", "io.appium.uiautomator2.server.test")

    # 3) Remove ALL forwards for this device (safer than removing a single port)
    _adb(udid, "forward", "--remove-all")

    # 4) Stop the AUT (optional but harmless)
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
    app.run(debug=False)
