import argparse
import os
import re
import shutil
import subprocess
import sys

# Path to config.py for inline update
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.py')

def update_config(folder_name, target_date, hijri_day, pays, pdf_filename):
    """Update selected variables in config.py."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = {
        'FOLDER_NAME': f'"{folder_name}"',
        'TARGET_DATE': f'"{target_date}"',
        'HIJRI_DAY': f'"{hijri_day}"',
        'PAYS': f'"{pays}"',
        'PDF_FILE': f'os.path.join(BASE_DIR, FOLDER_NAME, "{pdf_filename}")',
    }

    for var, value in replacements.items():
        pattern = rf'^{var}\s*=.*$'
        content = re.sub(pattern, f'{var} = {value}', content, flags=re.MULTILINE)

    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

def run_step(script, description):
    print(f"\n=== {description} ===")
    subprocess.run([sys.executable, script], check=True)


def run_pipeline(pdf, folder=None, target_date=None, hijri_day=None, country=None):
    """Run the full reservation pipeline."""
    import config

    folder = folder or config.FOLDER_NAME
    target_date = target_date or config.TARGET_DATE
    hijri_day = hijri_day or config.HIJRI_DAY
    pays = country or config.PAYS

    folder_path = os.path.join(config.BASE_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)

    pdf_filename = os.path.basename(pdf)
    destination_pdf = os.path.join(folder_path, pdf_filename)
    shutil.copy2(pdf, destination_pdf)

    update_config(folder, target_date, hijri_day, pays, pdf_filename)

    run_step('utils.py', 'Preparing CSV and merging PDFs')
    run_step('pdf.py', 'Extracting data from PDF')
    run_step('CreationReservation.py', 'Creating accounts and making reservations')
    run_step('login.py', 'Retrying reservations for remaining users')

def main():
    parser = argparse.ArgumentParser(description="Full reservation pipeline runner.")
    parser.add_argument('pdf', help='Path to the PDF file to process.')
    parser.add_argument('--folder', default=None, help='Folder name under BASE_DIR to use.')
    parser.add_argument('--target-date', default=None, help='Target reservation date (DD/MM).')
    parser.add_argument('--hijri-day', default=None, help='Hijri day value.')
    parser.add_argument('--country', default=None, help='Country name.')
    args = parser.parse_args()

    run_pipeline(
        pdf=args.pdf,
        folder=args.folder,
        target_date=args.target_date,
        hijri_day=args.hijri_day,
        country=args.country,
    )

if __name__ == '__main__':
    main()