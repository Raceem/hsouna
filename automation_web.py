import os
import re
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO
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
from werkzeug.utils import secure_filename
import pdfplumber
from PyPDF2 import PdfMerger
import automation
import config
import pandas as pd


app = Flask(__name__)
app.secret_key = "changeme"

# Use cross-platform temp upload dir
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "reservation_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _extract_date(name: str) -> datetime:
    """Extract a date from a folder name (DD_MM_YYYY or YYYY-MM-DD)."""
    patterns = [r"(\d{2}_\d{2}_\d{4})", r"(\d{4}-\d{2}-\d{2})"]
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            date_str = match.group(1)
            for fmt in ("%d_%m_%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
    return datetime.min


def _urlpath(*parts: str) -> str:
    """Join path parts and normalize to forward slashes for URLs."""
    return os.path.join(*parts).replace("\\", "/")


def get_runs(sort_by: str = "date"):
    """Collect previous runs (folders under BASE_DIR) for UI listing."""
    runs = []
    base_dir = config.BASE_DIR

    if not os.path.isdir(base_dir):
        return runs

    for folder in os.listdir(base_dir):
        folder_path = os.path.join(base_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        # PDFs in the run folder
        pdf_entries = []
        for name in sorted(os.listdir(folder_path)):
            if name.lower().endswith(".pdf"):
                pdf_entries.append({
                    "name": name,
                    "path": _urlpath(folder, name),  # normalized for URLs
                })

        # CSV (optional)
        csv_name = "informations.csv"
        csv_rel = _urlpath(folder, csv_name)  # normalized for URLs
        csv_abs = os.path.join(base_dir, folder, csv_name)
        csv_path = csv_rel if os.path.exists(csv_abs) else None
        reserved_men = 0
        reserved_women = 0

        if os.path.exists(csv_abs):
            try:
                # avoid NaNs turning into floats
                df = pd.read_csv(csv_abs, dtype=str, keep_default_na=False)

                def read_counter(df, col) -> int:
                    if col in df.columns and len(df) > 0:
                        val = pd.to_numeric(df[col].iloc[0], errors="coerce")
                        return int(val) if pd.notna(val) else 0
                    return 0

                reserved_men = read_counter(df, "reserved_men")
                reserved_women = read_counter(df, "reserved_women")

            except Exception as e:
                # don't silently swallow errors—log them at least
                print(f"Failed to read counters: {e}")



        # Rawdha images (optional)
        rawdha_images = []
        rawdha_dir = os.path.join(folder_path, "rawdha")
        if os.path.isdir(rawdha_dir):
            for img in sorted(os.listdir(rawdha_dir)):
                if img.lower().endswith((".png", ".jpg", ".jpeg")):
                    rawdha_images.append(_urlpath(folder, "rawdha", img))  # normalized

        runs.append({
            "folder": folder,
            "pdfs": pdf_entries,
            "csv": csv_path,
            "rawdha_images": rawdha_images,
            "reserved_men": reserved_men,
            "reserved_women": reserved_women,
            "mtime": os.path.getmtime(folder_path),
        })

    if sort_by == "mtime":
        runs.sort(key=lambda r: r["mtime"], reverse=True)
    else:
        runs.sort(key=lambda r: _extract_date(r["folder"]), reverse=True)

    return runs


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if automation.get_status()["running"]:
            flash("A pipeline is already running.")
            return redirect(url_for("index"))

        pdf = request.files.get("pdf")
        target_date = request.form.get("target_date")
        hijri_day = request.form.get("hijri_day")
        country = request.form.get("country")

        if not pdf or pdf.filename == "":
            flash("No file selected.")
            return redirect(request.url)

        # Safe cross-platform temp file path
        fname = secure_filename(pdf.filename) or "upload.pdf"
        tmp_path = os.path.join(UPLOAD_DIR, fname)
        pdf.save(tmp_path)

       # Determine folder name nationality_pages_targetdate
        try:
            with pdfplumber.open(tmp_path) as pdf_file:
                page_count = len(pdf_file.pages)
        except Exception:
            page_count = 0

        safe_date = (target_date or "").replace("/", "_").replace("-", "_")
        folder_name = secure_filename(f"{country}_{page_count}_{safe_date}")

        try:
            # Start in background so the UI returns immediately
            automation.run_pipeline_async(
                pdf=tmp_path,
                folder=folder_name,
                target_date=target_date,
                hijri_day=hijri_day,
                country=country,
            )
            flash("Pipeline started.")
        except Exception as exc:
            flash(str(exc))
        # Do NOT delete tmp_path here — the child process needs it.

        return redirect(url_for("index"))

    sort_by = request.args.get("sort", "date")
    runs = get_runs(sort_by=sort_by)
    status = automation.get_status()
    return render_template("index.html", runs=runs, sort=sort_by, status=status)


@app.route("/status")
def status():
    """JSON status for polling."""
    return jsonify(automation.get_status())

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

@app.route("/pause", methods=["POST"])
def pause():
    """Kill current running step and abort pipeline."""
    ok = automation.cancel_current()
    if ok:
        flash("Pipeline cancelled.")
    else:
        flash("No running pipeline.")
    return redirect(url_for("index"))


@app.route("/files/<path:filename>")
def serve_file(filename):
    """Serve files from the configured BASE_DIR."""
    # filename is URL-style (forward slashes); send_from_directory handles Windows paths.
    return send_from_directory(config.BASE_DIR, filename)


@app.route("/download_rawdha/<path:folder>")
def download_rawdha(folder):
    """Create a zip of the rawdha directory for download."""
    base_dir = config.BASE_DIR
    rawdha_dir = os.path.join(base_dir, folder, "rawdha")
    if not os.path.isdir(rawdha_dir):
        return "Not Found", 404

    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp_path, "w") as zipf:
        for root, _, files in os.walk(rawdha_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, rawdha_dir)
                zipf.write(abs_path, rel_path)

    response = send_file(
        tmp_path,
        as_attachment=True,
        download_name=f"{folder}_rawdha.zip",
        mimetype="application/zip",
    )

    @response.call_on_close
    def cleanup():
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return response


if __name__ == "__main__":
    app.run(debug=False)
