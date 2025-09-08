import os
import re
import csv
import threading
from typing import List, Tuple, Dict, Optional
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


def _read_first_row(csv_path: str) -> Tuple[Optional[pd.Series], Optional[pd.DataFrame]]:
    """
    Return (first_row, full_df) where first_row is the first data row
    (or None if no rows). Caller decides whether/when to drop it.
    """
    if not os.path.exists(csv_path):
        return None, None
    try:
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        if len(df) == 0:
            return None, df
        return df.iloc[0], df
    except Exception as e:
        print(f"Failed to read {csv_path}: {e}")
        return None, None


def _append_row_dict(dest_csv: str, row_dict: Dict[str, str]):
    """
    Append a row dict to dest_csv, creating file with headers if needed.
    Preserve/extend headers if new columns appear.
    """
    base_headers = _safe_headers()
    if not os.path.exists(dest_csv):
        _ensure_csv(dest_csv, base_headers)

    # Load existing headers from file
    with open(dest_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            existing_headers = next(reader)
        except StopIteration:
            existing_headers = base_headers

    # Ensure we include all keys from row_dict + existing headers
    all_keys = list(existing_headers)
    for k in row_dict.keys():
        if k not in all_keys:
            all_keys.append(k)

    # If headers changed, rewrite file with new header order
    if all_keys != existing_headers:
        with open(dest_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        with open(dest_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in all_keys})

    # Append the new row
    with open(dest_csv, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writerow({k: row_dict.get(k, "") for k in all_keys})


def _drop_first_row_and_save(df: pd.DataFrame, src_csv: str):
    """
    Drop the first data row and save back (re-indexing so we never “skip”).
    """
    if len(df) == 0:
        return
    df = df.drop(df.index[0]).reset_index(drop=True)
    df.to_csv(src_csv, index=False, encoding="utf-8")


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
# Run one row via your scripts
# =========================

def _run_one_row_via_scripts(row: Dict[str, str], target_ddmm: str) -> Tuple[bool, Dict[str, str]]:
    """
    Temporarily replace config.CSV_FILE with a one-row CSV, set TARGET_DATE,
    run CreationReservation.py (if CREATION != '1') or login.py (if CREATION == '1'),
    then read back the updated row to decide success (RESERVATION == '1').
    """
    # Ensure TARGET_DATE in config.py is set to DD/MM for this run
    _set_config_var("TARGET_DATE", f'"{target_ddmm}"')

    working_csv = getattr(config, "CSV_FILE")
    print(f"Using working CSV: {working_csv}")

    # ---- Build headers from the actual row keys (plus required/common ones) ----
    required_cols = {"CREATION", "RESERVATION"}
    common_cols = {
        "nationalite", "email", "numero_tlf", "numero_passport",
        "numero_visa", "gender", "date_reservation", "heure",
        "NOM", "PRENOM", "PHONE"
    }
    headers = list(dict.fromkeys(list(row.keys()) + list(required_cols | common_cols)))  # ordered, de-duped

    # Guarantee required/common fields exist in the row dict
    for k in required_cols | common_cols:
        row.setdefault(k, "")

    # 1) Back up original working CSV if it exists
    backup_path = None
    if os.path.exists(working_csv):
        backup_path = working_csv + ".bak"
        try:
            os.replace(working_csv, backup_path)
        except Exception:
            import shutil
            shutil.copy2(working_csv, backup_path)
            os.remove(working_csv)

    # 2) Write the single-row working CSV (with full headers)
    with open(working_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in headers})

    # 3) Decide which script to run
    creation_flag = (row.get("CREATION") or "").strip()
    if creation_flag == "1":
        script, desc = "login.py", "Login & reservation (single row)"
    else:
        script, desc = "CreationReservation.py", "Create account & reservation (single row)"

    ok = False
    out_row = dict(row)
    try:
        # 4) Run the script (synchronously)
        automation.run_step(script, desc)

        # 5) Read the updated working CSV
        try:
            df_after = pd.read_csv(working_csv, dtype=str, keep_default_na=False)
            if len(df_after) > 0:
                out_row = {k: ("" if pd.isna(v) else str(v)) for k, v in df_after.iloc[0].to_dict().items()}
                ok = (out_row.get("RESERVATION") or "").strip() == "1"
            else:
                ok = False
        except Exception as e:
            print(f"Failed to read working CSV after script: {e}")
            ok = False
    finally:
        # 6) Restore or remove working CSV to leave environment clean
        try:
            os.remove(working_csv)
        except Exception:
            pass
        if backup_path and os.path.exists(backup_path):
            try:
                os.replace(backup_path, working_csv)
            except Exception:
                import shutil
                shutil.copy2(backup_path, working_csv)
                os.remove(backup_path)

    return ok, out_row






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


@app.route("/pause", methods=["POST"])
def pause():
    ok = automation.cancel_current()
    flash("Pipeline cancelled." if ok else "No running pipeline.")
    return redirect(url_for("index"))


@app.route("/files/<path:filename>")
def serve_file(filename):
    return send_from_directory(config.BASE_DIR, filename)


if __name__ == "__main__":
    app.run(debug=False)
