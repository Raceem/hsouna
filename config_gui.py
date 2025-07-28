import os
import re
import subprocess
from tempfile import NamedTemporaryFile
import base64
from PyPDF2 import PdfReader
import streamlit as st
import io
import time
import pandas as pd

from PIL import Image
import config

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.py')

def update_config(folder_name, target_date, pays,  pdf_filename):
    """Update selected variables in config.py."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
        content = file.read()

    replacements = {
        'FOLDER_NAME': f'"{folder_name}"',
        'TARGET_DATE': f'"{target_date}"',
        'PAYS': f'"{pays}"',
        
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
def get_folder_color(folder):
    """Determine color for a folder based on its informations.csv."""
    csv_path = os.path.join(config.BASE_DIR, folder, "informations.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception:
        return None
    if df.empty or len(df.columns) == 0:
        return None
    if 'CREATION' not in df.columns:
        return None

    creation = df['CREATION'].astype(str)
    if (creation == '0').any():
        return 'red'

    if 'RESERVATION' not in df.columns:
        return 'green'
    reservation = df['RESERVATION'].astype(str)

    if ((creation == '1') & (reservation == '0')).any():
        return 'yellow'

    if 'CONFIRMATION' in df.columns:
        confirmation = df['CONFIRMATION'].astype(str)
        if ((creation == '1') & (reservation == '1') & (confirmation == '0')).any():
            return 'blue'

    return 'green'

def main():
    col_editor, col_preview = st.columns([ 5, 2])
    
        
    with col_editor:
        st.markdown("### 🗂️ Folder Color Legend")
        color_meanings = {
            '🟥 Red': 'We have not yet created accounts.',
            '🟨 Yellow': 'We have not yet made reservations',
            '🟦 Blue': 'Reservation made, confirmation not yet done',
            '🟩 Green': 'All steps completed ',
            '• None': 'No informations.csv found or empty'
        }

        for symbol, meaning in color_meanings.items():
            st.markdown(f"<div style='margin-bottom: 8px;'>- {symbol}: {meaning}</div>", unsafe_allow_html=True)
        # Left side: Configuration editor
        st.title("Configuration Editor")
        color_priority = ['red', 'yellow', 'blue', 'green',None]

        all_folders = [d for d in os.listdir(config.BASE_DIR)
                    if os.path.isdir(os.path.join(config.BASE_DIR, d))]

        # Get color for each folder
        folder_colors = {folder: get_folder_color(folder) for folder in all_folders}

        # Sort folders by color priority
        folder_options = sorted(
            all_folders,
            key=lambda f: (color_priority.index(folder_colors.get(f, 'green')), f)
        )

        default_index = folder_options.index(config.FOLDER_NAME) if config.FOLDER_NAME in folder_options else 0

        color_symbols = {
            'yellow': '🟨',
            'red': '🟥',
            'blue': '🟦',
            'green': '🟩'
        }
        def format_folder(folder):
            color = folder_colors.get(folder)
            symbol = color_symbols.get(color, '')
            return f"{symbol} {folder}" if symbol else folder

        folder_name = st.selectbox(
            "Select Folder",
            folder_options,
            index=default_index,
            format_func=format_folder  # 🟨🟥🟦🟩 folder label formatter
        )



       
        target_date = st.text_input("Target Date", config.TARGET_DATE)
        pays = st.text_input("Pays", config.PAYS)
        
        pdf_filename = st.text_input("PDF File Name", os.path.basename(config.PDF_FILE))

        uploaded_pdf = st.file_uploader("Select PDF", type=["pdf"])

        if st.button("Save config"):
            update_config(folder_name, target_date, pays, pdf_filename)
            st.success("Configuration saved")

        if uploaded_pdf is not None and st.button("Prepare folder"):
            with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_pdf.getvalue())
                tmp_path = tmp.name

            try:
                

                reader = PdfReader(tmp_path)
                num_people = len(reader.pages)
            except Exception as e:
                st.error(f"Failed to read PDF: {e}")
                return

            safe_target_date = target_date.replace("/", "_")
            folder_name_generated = f"{pays}_{num_people}_{safe_target_date}"

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

    with col_preview:
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
