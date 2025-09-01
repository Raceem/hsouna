import os
from flask import Flask, flash, redirect, render_template_string, request, url_for

import automation

app = Flask(__name__)
app.secret_key = "changeme"

FORM_TEMPLATE = """
<!doctype html>
<title>Reservation Automation</title>
<h1>Upload PDF and Enter Details</h1>
<form method=post enctype=multipart/form-data>
  <label>PDF File: <input type=file name=pdf accept="application/pdf" required></label><br>
  <label>Target date (DD/MM): <input type=text name=target_date required></label><br>
  <label>Hijri day: <input type=text name=hijri_day required></label><br>
  <label>Nationality: <input type=text name=country required></label><br>
  <input type=submit value=Run>
</form>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul>
      {% for message in messages %}
        <li>{{ message }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
"""


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

    return render_template_string(FORM_TEMPLATE)


if __name__ == "__main__":
    app.run(debug=True)