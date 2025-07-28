import os
import re
import subprocess
from tempfile import NamedTemporaryFile
import base64

import streamlit as st
import io
import time

from PIL import Image
import config

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.py')

def update_config(folder_name, target_date, pays, start_date, pdf_filename):
    """Update selected variables in config.py."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
        content = file.read()

    replacements = {
        'FOLDER_NAME': f'"{folder_name}"',
        'TARGET_DATE': f'"{target_date}"',
        'PAYS': f'"{pays}"',
        'START_DATE': f'"{start_date}"',
        'PDF_FILE': f'os.path.join(BASE_DIR, FOLDER_NAME, "{pdf_filename}")',
    }

    for var, value in replacements.items():
        pattern = rf'^{var}\s*=.*$'
        new_line = f'{var} = {value}'
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)

    with open(CONFIG_PATH, 'w', encoding='utf-8') as file:
        file.write(content)


def capture_screenshot():
    result = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    if result.returncode != 0:
        st.error("Failed to capture screenshot.")
        return None

    return result.stdout


def main():
    col1, col2 = st.columns([3, 1])  # Wider left column, narrower right

    with col1:
        # Left side: Configuration editor
        st.title("Configuration Editor")

        folder_options = [d for d in os.listdir(config.BASE_DIR)
                          if os.path.isdir(os.path.join(config.BASE_DIR, d))]
        default_index = folder_options.index(config.FOLDER_NAME) if config.FOLDER_NAME in folder_options else 0
        folder_name = st.selectbox("Select Folder", folder_options, index=default_index)
        target_date = st.text_input("Target Date", config.TARGET_DATE)
        pays = st.text_input("Pays", config.PAYS)
        start_date = st.text_input("Start Date", config.START_DATE)
        pdf_filename = st.text_input("PDF File Name", os.path.basename(config.PDF_FILE))

        uploaded_pdf = st.file_uploader("Select PDF", type=["pdf"])

        if st.button("Save config"):
            update_config(folder_name, target_date, pays, start_date, pdf_filename)
            st.success("Configuration saved")

        if uploaded_pdf is not None and st.button("Prepare folder"):
            with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_pdf.getvalue())
                tmp_path = tmp.name

            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(tmp_path)
                num_people = len(reader.pages)
            except Exception as e:
                st.error(f"Failed to read PDF: {e}")
                return

            folder_name_generated = f"{pays}_{num_people}_{start_date}"
            folder_path = os.path.join(config.BASE_DIR, folder_name_generated)
            os.makedirs(folder_path, exist_ok=True)

            pdfs_dir = os.path.join(config.BASE_DIR, "PDFs")
            os.makedirs(pdfs_dir, exist_ok=True)
            dest_pdf_path = os.path.join(pdfs_dir, uploaded_pdf.name)
            os.replace(tmp_path, dest_pdf_path)

            update_config(
                folder_name_generated,
                target_date,
                pays,
                start_date,
                uploaded_pdf.name,
            )
            st.success(f"Folder prepared: {folder_path}")

        if st.button("Run utils.py"):
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                ["python", "utils.py"], capture_output=True, text=True, env=env
            )
            st.text(result.stdout)
            if result.stderr:
                st.error(result.stderr)

        if st.button("Run pdf.py"):
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                ["python", "pdf.py"], capture_output=True, text=True, env=env
            )
            st.text(result.stdout)
            if result.stderr:
                st.error(result.stderr)

    with col2:
        st.markdown("### 📱 Live Phone Preview")

        show_preview = st.checkbox("Show Phone Screen")
        if show_preview:
            img_placeholder = st.empty()
            refresh_rate = st.slider("Refresh rate (sec)", 0.1, 2.0, 1.0, 0.1)

            while True:
                img_data = capture_screenshot()
                if img_data:
                    img = Image.open(io.BytesIO(img_data))
                    img_placeholder.image(img, caption="Phone", use_container_width=True)

                time.sleep(refresh_rate)

                # Exit loop if checkbox is turned off
                if not st.session_state.get("Show Phone Screen", True):
                    break


if __name__ == "__main__":
    main()
