# pdf_img.py

import re
import json
import os
from datetime import datetime

import cv2
import numpy as np
import pandas as pd
import pytesseract
from pdf2image import convert_from_path

import config

# === 🔧 Configuration OCR ===
# Utilise les chemins déclarés dans config.py s’ils existent,
# sinon bascule vers des valeurs par défaut.
poppler_path = getattr(config, 'POPPLER_PATH', r"C:/poppler/bin")
pytesseract.pytesseract.tesseract_cmd = getattr(
    config, 'TESSERACT_CMD',
    r'C:\Program Files\Tesseract-OCR\tesseract.exe'
)

# === 🌍 Chargement des patterns pays ===
with open("country_patterns.json", "r", encoding="utf-8") as f:
    country_patterns = json.load(f)

# On prend le pays en minuscules depuis config
country = config.PAYS_UPPER.lower()
if country not in country_patterns:
    raise ValueError(f"Aucun regex pattern pour le pays : {country}")

name_pattern = country_patterns[country]["name_pattern"]
passport_pattern = country_patterns[country]["passport_pattern"]

# === 📄 Chemins de fichiers depuis config.py ===
pdf_path              = config.PDF_FILE
csv_file              = config.CSV_FILE
filename_email_json   = config.EMAIL_JSON_FILE
filename_number_json  = config.NUMBER_JSON_FILE
fieldnames            = config.FIELDNAMES

# === 🔄 Fonctions utilitaires ===
def pop_first_variant(filename):
    """Prend et supprime le premier élément d'une liste JSON."""
    with open(filename, 'r', encoding='utf-8') as f:
        variants = json.load(f)
    if variants:
        first = variants.pop(0)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(variants, f, ensure_ascii=False, indent=4)
        return first
    return None

def extract_text_by_ocr(file_path):
    """Convertit chaque page du PDF en image puis OCR."""
    pages = convert_from_path(file_path, dpi=150, poppler_path=poppler_path)
    texts = []
    for img in pages:
        open_cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray, lang='eng')
        texts.append(text)
    return texts

if __name__ == "__main__":
    pages = extract_text_by_ocr(pdf_path)

    # === 🛂 Détermination du type de voyage et des dates depuis config ===
    basename = os.path.basename(pdf_path).lower()
    if "group" in basename:
        type_voyage = "Groupe"
        date_entree_madinah = config.START_DATE
        duree_jours = config.DURATION_DAYS
    else:
        type_voyage = "libre"
        date_entree_madinah = ""
        duree_jours = ""

    for i, texte in enumerate(pages, start=1):
        print(f"📄 Page {i} :\n{'='*50}\n{texte}\n")

        # ---- Extraction de la date de naissance ----
        date_de_naissance = ""
        for date in re.findall(r'(\d{2}/\d{2}/\d{4})', texte):
            try:
                d, m, y = map(int, date.split('/'))
                if 1800 < y < datetime.now().year:
                    date_de_naissance = date
                    break
            except ValueError:
                continue

        # ---- Numéro de visa (10 chiffres) ----
        m_visa = re.search(r'\b(\d{10})\b', texte)
        numero_visa = m_visa.group(1) if m_visa else "Non trouvé"

        # ---- Numéro de passeport selon le pattern pays ----
        m_pass = re.search(passport_pattern, texte)
        numero_passport = m_pass.group(1) if m_pass else "Non trouvé"

        # ---- Nom et prénom selon le pattern pays ----
        m_name = re.search(name_pattern, texte)
        nom    = m_name.group(1) if m_name else f"nom{i}"
        prenom = m_name.group(2) if m_name else f"prenom{i}"

        # ---- Récupération des variantes d’email et de téléphone ----
        email       = pop_first_variant(filename_email_json)
        numero_tlf  = pop_first_variant(filename_number_json)

        # ---- Chargement (ou création) du CSV ----
        try:
            df = pd.read_csv(csv_file, encoding="utf-8")
        except FileNotFoundError:
            df = pd.DataFrame(columns=fieldnames)

        # ---- Vérification doublon passeport ----
        if numero_passport in df["numero_passport"].values:
            print(f"⛔ Le numéro de passeport {numero_passport} existe déjà.")
            continue

        # ---- Préparation de la nouvelle entrée ----
        new_entry = {
            "id": len(df) + 1,
            "nom": nom,
            "prenom": prenom,
            "date_de_naissance": date_de_naissance,
            "numero_visa": numero_visa,
            "email": email,
            "numero_tlf": numero_tlf,
            "numero_passport": numero_passport,
            "type_voyage": type_voyage,
            "date_entree_madinah": date_entree_madinah,
            "duree_jours": duree_jours,
            "have_a_compte": 0,
            "CREATION": 0,
            "RESERVATION": 0,
            "CONFIRMATION": 0,
            "date_reservation": "",
            "heure": ""
        }

        # ---- Ajout au CSV ----
        df_new = pd.DataFrame([new_entry])
        df_new.to_csv(
            csv_file,
            mode="a",
            index=False,
            header=not os.path.exists(csv_file)
        )
        print(f"✅ Entrée ajoutée pour {nom} {prenom}")
