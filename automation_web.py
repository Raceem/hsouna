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


def _handle_plus_action(big_csv_path: str, dest_folder: str, dest_file: str, label_for_flash: str):
    """
    Single-shot handler for + Men / + Women:
      - parse date from folder name (MM_DD__YYYY or MM/DD/YYYY) -> DD/MM
      - read the first row from the big CSV
      - set TARGET_DATE to DD/MM and run correct script for that row
      - on success: drop it from big CSV, append to destination folder CSV
    """
    # 0) Derive target date from folder name
    target_ddmm = parse_target_date_from_folder(dest_folder)
    if not target_ddmm:
        flash(f"{label_for_flash}: cannot parse date from folder name '{dest_folder}'. Expected MM_DD__YYYY or MM/DD/YYYY.", "danger")
        return

    # 1) Read first data row from the big CSV
    row_series, df_big = _read_first_row(big_csv_path)
    if row_series is None:
        flash(f"No rows available in {os.path.basename(big_csv_path)}.", "warning")
        return
    row = {k: ("" if v is None else str(v)) for k, v in row_series.to_dict().items()}

    # 2) Run via your scripts with TARGET_DATE set to the folder's date (DD/MM)
    ok, row_out = _run_one_row_via_scripts(row, target_ddmm)
    if not ok:
        flash(f"{label_for_flash}: automation did not complete successfully.", "danger")
        return

    # 3) On success → move row: remove from big CSV, append into the daily folder CSV
    folder_root = os.path.join(config.BASE_DIR, dest_folder)
    if not os.path.isdir(folder_root):
        flash(f"Destination folder not found: {dest_folder}", "danger")
        return

    dest_csv = os.path.join(folder_root, dest_file)
    _ensure_csv(dest_csv, _safe_headers())

    # Remove first row from big CSV and reindex (so the next click picks the next person)
    _drop_first_row_and_save(df_big, big_csv_path)

    # Append the updated row to the selected folder CSV
    _append_row_dict(dest_csv, row_out)

    flash(f"{label_for_flash}: processed for {target_ddmm} and moved to {dest_file}.", "success")


# =========================
# Background drainers (skip failures)
# =========================

def _drain_big_csv_for_folder(*, big_csv_path: str, dest_folder: str, dest_file: str, label_for_flash: str,   max_success: Optional[int] = None,
                              prioritize_creation: bool = False,
):
    """
    Background loop: take the first row from big_csv_path, run scripts using the
    folder's date, on success move it into BASE_DIR/<dest_folder>/<dest_file>,
    on failure SKIP the row (drop it) and continue, until the big CSV is empty
    or a user cancel occurs (Pause/Stop).
    """
    try:
        # Mark as running for the duration of the draining session
        automation._STATE.set_running(True)
        automation._STATE.set_step(f"Drain {os.path.basename(big_csv_path)} → {dest_folder}", f"{label_for_flash} draining")
    except Exception:
        pass

    try:
        # Resolve once (same date for all rows in this run)
        target_ddmm = parse_target_date_from_folder(dest_folder)
        if not target_ddmm:
            print(f"[drain] Cannot parse date from folder name: {dest_folder}")
            return

        # Ensure destination exists
        folder_root = os.path.join(config.BASE_DIR, dest_folder)
        os.makedirs(folder_root, exist_ok=True)
        _ensure_csv(os.path.join(folder_root, dest_file), _safe_headers())
        if prioritize_creation and os.path.exists(big_csv_path):
            try:
                df_pri = pd.read_csv(big_csv_path, dtype=str, keep_default_na=False)
                if "CREATION" in df_pri.columns:
                    df_pri["__creation_int__"] = pd.to_numeric(df_pri["CREATION"], errors="coerce").fillna(0).astype(int)
                    df_pri.sort_values("__creation_int__", ascending=False, inplace=True)
                    df_pri.drop(columns="__creation_int__", inplace=True)
                    df_pri.to_csv(big_csv_path, index=False, encoding="utf-8")
            except Exception as e:
                print(f"[drain] Could not prioritize CREATION rows: {e}")
        # A place to log skipped rows (audit)
        processed = 0
        skipped = 0

        while True:
            if max_success is not None and processed >= max_success:
                print(f"[drain] Hit success target: {processed}/{max_success}")
                break
            # If user pressed Pause/Stop, the child process is killed; we stop after current loop
            snap = automation.get_status()
            # If some other process toggled running to False, stop gracefully
            if not snap.get("running", False) and processed + skipped > 0:
                print("[drain] Detected cancel; stopping after current iteration.")
                break

            # Pull first row
            row_series, df_big = _read_first_row(big_csv_path)
            if row_series is None:
                print("[drain] No more rows.")
                break

            row = {k: ("" if v is None else str(v)) for k, v in row_series.to_dict().items()}

            # Run one row
            ok, row_out = _run_one_row_via_scripts(row, target_ddmm)

            if ok:
                # Remove from big CSV, append to folder CSV
                _drop_first_row_and_save(df_big, big_csv_path)
                dest_csv = os.path.join(folder_root, dest_file)
                _append_row_dict(dest_csv, row_out)
                processed += 1
                try:
                    automation._STATE.set_step(f"{label_for_flash}: processed={processed}, skipped={skipped}", f"last_ok={row_out.get('nom','')}")
                except Exception:
                    pass
            else:

                try:
                    # Remove first row
                    df_rest = df_big.drop(df_big.index[0]).reset_index(drop=True)

                    # Build a one-row DF from the failed row
                    row_df = pd.DataFrame([row])

                    # Align columns both ways: add missing cols to each side
                    for col in df_rest.columns:
                        if col not in row_df.columns:
                            row_df[col] = ""
                    for col in row_df.columns:
                        if col not in df_rest.columns:
                            df_rest[col] = ""

                    # Reorder row_df columns to match df_rest, then append it to the bottom
                    row_df = row_df[df_rest.columns]
                    df_new = pd.concat([df_rest, row_df], ignore_index=True)

                    # Save back to the big CSV
                    df_new.to_csv(big_csv_path, index=False, encoding="utf-8")

                    skipped += 1
                    print("[drain] Row failed; kept in CSV and moved to bottom for retry.")
                    try:
                        automation._STATE.set_step(
                            f"{label_for_flash}: processed={processed}, kept_for_retry={skipped}",
                            f"last_retry={row.get('nom','')}"
                        )
                    except Exception:
                        pass
                except Exception as e:
                 print(f"[drain] Could not rotate failed row to bottom: {e}")

        print(f"[drain] Done. Processed={processed}, Skipped={skipped}")

    except Exception as e:
        print(f"[drain] Fatal error: {e}")
        automation._STATE.set_error(str(e))
    finally:
        # Mark idle
        try:
            automation._STATE.set_running(False)
        except Exception:
            pass


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

@app.route("/start_men/<folder>", methods=["POST"])
def start_men(folder):
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))

    # Read optional count (success target) from form or query string
    count_str = request.form.get("count") or request.args.get("count")
    max_success = None
    try:
        if count_str is not None:
            v = int(count_str)
            if v > 0:
                max_success = v
    except Exception:
        pass

    prioritize = (request.form.get("prioritize_creation") or "0") == "1"

    t = threading.Thread(
        target=_drain_big_csv_for_folder,
        kwargs=dict(
            big_csv_path=config.HOMMES_CSV_PATH,
            dest_folder=folder,
            dest_file="hommes.csv",
            label_for_flash=f"{folder} (+Men)",
            max_success=max_success,                      # <— pass it through
            prioritize_creation=prioritize,
        ),
        daemon=True,
        name=f"drain-men-{folder}",
    )
    t.start()

    target_msg = f", target={max_success}" if max_success is not None else ""
    flash(f"Started: draining HOMMES into {folder}/hommes.csv (date = {parse_target_date_from_folder(folder) or 'n/a'}{target_msg}).")
    return redirect(url_for("index"))

@app.route("/start_women/<folder>", methods=["POST"])
def start_women(folder):
    if automation.get_status().get("running"):
        flash("Another automation is already running. Please Pause/Stop first.", "warning")
        return redirect(url_for("index"))

    # Read optional count (success target) from form or query string
    count_str = request.form.get("count") or request.args.get("count")
    max_success = None
    try:
        if count_str is not None:
            v = int(count_str)
            if v > 0:
                max_success = v
    except Exception:
        pass

    prioritize = (request.form.get("prioritize_creation") or "0") == "1"

    t = threading.Thread(
        target=_drain_big_csv_for_folder,
        kwargs=dict(
            big_csv_path=config.FEMMES_CSV_PATH,
            dest_folder=folder,
            dest_file="femmes.csv",
            label_for_flash=f"{folder} (+Women)",
            max_success=max_success,                      # <— pass it through
            prioritize_creation=prioritize,
        ),
        daemon=True,
        name=f"drain-women-{folder}",
    )
    t.start()

    target_msg = f", target={max_success}" if max_success is not None else ""
    flash(f"Started: draining FEMMES into {folder}/femmes.csv (date = {parse_target_date_from_folder(folder) or 'n/a'}{target_msg}).")
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
