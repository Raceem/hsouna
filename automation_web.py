import os
import re
import tempfile
import zipfile
from datetime import datetime
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

import automation
import config

app = Flask(__name__)
app.secret_key = "changeme"


def _extract_date(name: str) -> datetime:
    """Extract a date from a folder name.

    Supports patterns like ``DD_MM_YYYY`` or ``YYYY-MM-DD``. If no
    recognizable date is found, ``datetime.min`` is returned so such
    folders fall to the end of the sorted list.
    """

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


def get_runs(sort_by: str = "date"):
    """Collect information about previously imported PDF folders."""
    runs = []
    base_dir = config.BASE_DIR

    if not os.path.isdir(base_dir):
        return runs

    for folder in os.listdir(base_dir):
        folder_path = os.path.join(base_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        pdf_entries = []
        for name in sorted(os.listdir(folder_path)):
            if name.lower().endswith(".pdf"):
                pdf_entries.append({
                    "name": name,
                    "path": os.path.join(folder, name),
                })

        csv_name = "informations.csv"
        csv_rel = os.path.join(folder, csv_name)
        csv_abs = os.path.join(base_dir, csv_rel)
        csv_path = csv_rel if os.path.exists(csv_abs) else None

        has_rawdha = os.path.isdir(os.path.join(folder_path, "rawdha"))

        reservations = []
        res_dir = os.path.join(folder_path, "reservations")
        if os.path.isdir(res_dir):
            for img in sorted(os.listdir(res_dir)):
                if img.lower().endswith((".png", ".jpg", ".jpeg")):
                    reservations.append(os.path.join(folder, "reservations", img))

        runs.append({
            "folder": folder,
            "pdfs": pdf_entries,
            "csv": csv_path,
            "has_rawdha": has_rawdha,
            "reservations": reservations,
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
        pdf = request.files.get("pdf")
        target_date = request.form.get("target_date")
        hijri_day = request.form.get("hijri_day")
        country = request.form.get("country")

        if not pdf or pdf.filename == "":
            flash("No file selected.")
            return redirect(request.url)

        tmp_path = os.path.join("/tmp", pdf.filename)
        pdf.save(tmp_path)

        try:
            automation.run_pipeline(
                pdf=tmp_path,
                target_date=target_date,
                hijri_day=hijri_day,
                country=country,
            )
            flash("All steps completed successfully.")
        except Exception as exc:  # pragma: no cover - runtime feedback
            flash(str(exc))
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        return redirect(url_for("index"))

    sort_by = request.args.get("sort", "date")
    runs = get_runs(sort_by=sort_by)
    return render_template("index.html", runs=runs, sort=sort_by)


@app.route("/files/<path:filename>")
def serve_file(filename):
    """Serve files from the configured BASE_DIR."""
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
    app.run(debug=True)