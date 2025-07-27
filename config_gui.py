import os
import re
import streamlit as st
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


def main():
    st.title("Configuration Editor")

    folder_name = st.text_input("Folder Name", config.FOLDER_NAME)
    target_date = st.text_input("Target Date", config.TARGET_DATE)
    pays = st.text_input("Pays", config.PAYS)
    start_date = st.text_input("Start Date", config.START_DATE)
    pdf_filename = st.text_input(
        "PDF File Name", os.path.basename(config.PDF_FILE)
    )

    if st.button("Save"):
        update_config(folder_name, target_date, pays, start_date, pdf_filename)
        st.success("Configuration saved")


if __name__ == "__main__":
    main()