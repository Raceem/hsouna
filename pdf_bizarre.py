from pdfminer.high_level import extract_text
import re
import pandas as pd
import json
from datetime import datetime
import pdfplumber

from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    FIELDNAMES,
    PDF_FILE,
)

def pop_first_variant(filename_email_json):
    with open(filename_email_json, 'r', encoding='utf-8') as f:
        variants = json.load(f)
    if variants:
        first_variant = variants.pop(0)
        print(f"Élément récupéré : {first_variant}")
    else:
        print("La liste est vide, rien à récupérer.")
        return None
    with open(filename_email_json, 'w', encoding='utf-8') as f:
        json.dump(variants, f, ensure_ascii=False, indent=4)
    print(f"Le fichier {filename_email_json} a été mis à jour.")
    return first_variant

def extract_text_by_pages(file_path):
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return pages

if __name__ == "__main__":
    pages = extract_text_by_pages(PDF_FILE)

    # --- Regroupement page 1 + page 2, page 3 + page 4, etc. ---
    records = []
    for i in range(0, len(pages), 2):
        block = pages[i]
        if i + 1 < len(pages):
            block += "\n" + pages[i+1]
        records.append(block)

    # Définition statique si besoin
    if "visa_libre" not in PDF_FILE:
        type_voyage = "Groupe"
        date_entree_madinah = "22_07_2025"
        duree_jours = 1
    else:
        type_voyage = "libre"
        date_entree_madinah = False
        duree_jours = False

    # On parcourt chaque bloc fusionné
    for idx, texte in enumerate(records, start=1):
        print(f"\n--- Traitement du visa #{idx} ---")

        # 1) Extraction des dates (format DD/MM/YYYY ou YYYY-MM-DD)
        raw_dates = re.findall(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})', texte)
        # On convertit YYYY-MM-DD -> DD/MM/YYYY
        dates = [
            datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y") if "-" in d else d
            for d in raw_dates
        ]
        # On garde les années plausibles pour une naissance
        dates_naissances = [
            d for d in dates
            if 1800 < int(d.split('/')[2]) < 2025
        ]
        date_de_naissance = dates_naissances[0] if dates_naissances else ""
        print(f"Date de naissance extraite : {date_de_naissance}")

        # 2) Numéro de visa : 10 chiffres consécutifs
        # Cherche d’abord la ligne qui commence par "Visa No."
        m_label = re.search(r'(?:Visa\s*No\.?\s*:?\s*)(\d{9,10})', texte)
        # Certains visas font 9 chiffres, d’autres 10
        numero_visa = m_label.group(1) if m_label else "Non trouvé"
        print(f"N° Visa : {numero_visa}")

        # 3) Numéro de passeport : on essaye plusieurs patterns selon le pays
        patterns = {
            "IRQ": r'([A-Z]\d{8})\d?IRQ',
            "IDN": r'([A-Z][0-9]{7})<\d?IDN',
            "IND": r'([A-Z][0-9]{7})<\d?IND',
            "MAR": r'([A-Z][0-9]{7})<\d?MAR',
            "GEN": r'([A-Z]\d{7})',
            "EGY": r'([A-Z]{1}[0-9]{8})\d?EGY',
        }
        numero_passport = "Non trouvé"
        country_code = ""
        for code, pat in patterns.items():
            m = re.search(pat, texte)
            if m:
                numero_passport = m.group(1)
                country_code = code
                break
        print(f"N° Passeport ({country_code}) : {numero_passport}")

        # 4) Nom / prénom depuis la MRZ (juste un exemple de pattern)
        nom, prenom = f"nom{idx}", f"prenom{idx}"
        if country_code:
            mrz_pat = rf"{country_code}([A-Z]+)<<([A-Z]+)"
            m2 = re.search(mrz_pat, texte)
            if m2:
                nom, prenom = m2.group(1), m2.group(2)
        print(f"Nom/prénom : {nom} / {prenom}")

        # 5) Email et téléphone depuis vos JSON
        email = pop_first_variant(EMAIL_JSON_FILE) or ""
        numero_tlf = pop_first_variant(NUMBER_JSON_FILE) or ""

        # 6) Écriture dans le CSV
        df = pd.read_csv(CSV_FILE, encoding="utf-8")
        new_muatamer = {
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

        if numero_passport in df["numero_passport"].astype(str).values:
            print(f"Le numéro de passport {numero_passport} existe déjà dans le CSV.")
        else:
            df_new = pd.DataFrame([new_muatamer])
            df_new.to_csv(CSV_FILE, mode="a", index=False, header=False)
            print("Ajout au CSV effectué.")
