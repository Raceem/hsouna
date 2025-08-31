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
from datetime import datetime,date
import streamlit as st
from PIL import Image
import config
st.markdown("""
    <style>
        /* Style applied to a Streamlit button immediately following
           a placeholder div with class 'custom-btn'. */
        .custom-btn + div.stButton > button {
            border: 2px solid transparent;
            background-color: transparent;
            padding: 10px 20px;
            font-weight: bold;
            border-radius: 5px;
            transition: 0.3s ease;
        }
        .red-border + div.stButton > button {
            border-color: #e74c3c;
        }
        .red-border + div.stButton > button:hover {
            background-color: #e74c3c;
            color: white;
        }
        .yellow-border + div.stButton > button {
            border-color: #f1c40f;
            color: black;
        }
        .yellow-border + div.stButton > button:hover {
            background-color: #f1c40f;
            color: black;
        }
        .green-border + div.stButton > button {
            border-color: #27ae60;
        }
        .green-border + div.stButton > button:hover {
            background-color: #27ae60;
            color: white;
        }
    </style>
""", unsafe_allow_html=True)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.py')

def update_config(folder_name, target_date,hijri_day, pays ,  pdf_filename):
    """Update selected variables in config.py."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
        content = file.read()

    replacements = {
        'FOLDER_NAME': f'"{folder_name}"',
        'TARGET_DATE': f'"{target_date}"',
        'HIJRI_DAY': f'"{hijri_day}"',

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
    """Détermine la couleur d’un dossier en fonction de son informations.csv."""
    csv_path = os.path.join(config.BASE_DIR, folder, "informations.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception:
        return None

    # Si pas de colonne CREATION, on ne peut rien dire
    if 'CREATION' not in df.columns:
        return None

    creation    = df['CREATION'].astype(str)
    reservation = df.get('RESERVATION', pd.Series([], dtype=str)).astype(str)
    confirmation= df.get('CONFIRMATION', pd.Series([], dtype=str)).astype(str)

    # Pas encore de création
    if (creation == '0').any():
        return 'red'

    # Création OK, pas encore de résa
    if ((creation == '1') & (reservation == '0')).any():
        return 'yellow'

    # Résa faite, confirmation pas encore faite
    if ((creation == '1') & (reservation == '1') & (confirmation == '0')).any():
        # on tente d'extraire JJ et MM en fin de nom de dossier
        parts = folder.split("_")
        try:
            day, month = int(parts[-2]), int(parts[-1])
            today = datetime.today()
            year = today.year + (1 if month < today.month else 0)
            target_date = date(year, month, day)
            days_to_target = (target_date - today.date()).days
            # si on est encore avant (ou jour même) de la date cible
            if 0 <= days_to_target <= 2:
                return 'purple'
            # sinon, date dépassée → on met “blue” pour “en retard”
            else:
                return 'blue'
        except Exception:
            # si parsing échoue, on retombe sur le bleu standard
            return 'blue'

    # Tout est confirmé
    if ((creation == '1') & (reservation == '1') & (confirmation == '1')).any():
        return 'green'

    return 'green'

def main():
    col_editor, col_preview = st.columns([ 5, 2])
    
        
    with col_editor:
        
        st.markdown("### 🗂️ Folder Color Legend")
        color_meanings = {
             '🟥 Red': 'We have not yet created accounts.',
             '🟨 Yellow': 'We have not yet made reservations',
             '🟪 Purple': 'Reservation made can confirm',
             '🟦 Blue': 'Reservation made .awaiting confirmation date',
             '🟩 Green': 'All steps completed ',
             '• None': 'No informations.csv found or empty'
         }

        for symbol, meaning in color_meanings.items():
            st.markdown(f"<div style='margin-bottom: 8px;'>- {symbol}: {meaning}</div>", unsafe_allow_html=True)
        # Left side: Configuration editor
        st.title("Configuration Editor")
        color_priority = ['purple','red', 'yellow', 'blue', 'green',None]

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
             'red'   : '🟥',
             'yellow': '🟨',
             'purple': '🟪',
             'blue'  : '🟦',
             'green' : '🟩'
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
        hijri_day = st.text_input("Hijri Day", config.HIJRI_DAY)

        pays = st.text_input("Pays", config.PAYS)
        
        # Automatically update session state when a PDF is uploaded
        uploaded_pdf = st.file_uploader("Select PDF", type=["pdf"])
        if uploaded_pdf is not None:
            st.session_state.pdf_filename = uploaded_pdf.name

        # Show the PDF filename input (auto-filled if uploaded)
        pdf_filename = st.text_input("PDF File Name", value=st.session_state.get("pdf_filename", ""), key="pdf_filename")

        if st.button("Save config"):
            update_config(folder_name, target_date, hijri_day, pays, pdf_filename)
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
                hijri_day,
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
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.markdown("<div class='custom-btn red-border'></div>", unsafe_allow_html=True)
            if st.button("Create + Reserve", key="create_reserve"):
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                result = subprocess.run(
                    ["python", "CreationReservation.py"], capture_output=True, text=True, env=env
                )
                st.text(result.stdout)
                if result.stderr:
                    st.error(result.stderr)

        with col_b:
            st.markdown("<div class='custom-btn yellow-border'></div>", unsafe_allow_html=True)
            if st.button("Reserve", key="reserve"):
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                result = subprocess.run(
                    ["python", "login.py"], capture_output=True, text=True, env=env
                )
                st.text(result.stdout)
                if result.stderr:
                    st.error(result.stderr)


        with col_c:
            st.markdown("<div class='custom-btn green-border'></div>", unsafe_allow_html=True)
            if st.button("Confirmer", key="confirmer"):
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                result = subprocess.run(
                    ["python", "confirmation.py"], capture_output=True, text=True, env=env
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