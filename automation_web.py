import os
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

import automation
import config

app = Flask(__name__)
app.secret_key = "changeme"


def get_runs():
    """Collect information about previously imported PDF folders."""
    runs = []
    base_dir = config.BASE_DIR

    if not os.path.isdir(base_dir):
        return runs

    for folder in sorted(os.listdir(base_dir)):
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
            "reservations": reservations,
        })

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

    runs = get_runs()
    return render_template("index.html", runs=runs)


@app.route("/files/<path:filename>")
def serve_file(filename):
    """Serve files from the configured BASE_DIR."""
    return send_from_directory(config.BASE_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True)