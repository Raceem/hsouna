# -*- coding: utf-8 -*-
from pdfminer.high_level import extract_text  # still available if you need it later
import re
import pandas as pd
import json
from datetime import datetime
import os
import pdfplumber

from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    FIELDNAMES,
    PDF_FILE,
)

# ---------------------------
# Helpers: pop first variant
# ---------------------------
def pop_first_variant(filename_json):
    # Ensure file exists and is a JSON list
    if not os.path.exists(filename_json):
        with open(filename_json, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(filename_json, "r", encoding="utf-8") as f:
        try:
            variants = json.load(f)
            if not isinstance(variants, list):
                variants = []
        except json.JSONDecodeError:
            variants = []

    if variants:
        first_variant = variants.pop(0)
        print(f"Élément récupéré : {first_variant}")
    else:
        print("La liste est vide, rien à récupérer.")
        first_variant = None

    with open(filename_json, "w", encoding="utf-8") as f:
        json.dump(variants, f, ensure_ascii=False, indent=4)
    print(f"Le fichier {filename_json} a été mis à jour.")
    return first_variant

# ---------------------------
# PDF text extraction
# ---------------------------
def extract_text_by_pages(file_path):
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # pdfplumber can return None on image-only pages -> guard with ""
            pages.append(text)
    return pages

# ---------------------------
# Date parsing utilities
# ---------------------------
DATE_TOKEN = r'\b(?:\d{2}[\/\-]\d{2}[\/\-]\d{4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})\b'

def normalize_to_dd_mm_yyyy(s: str) -> str:
    parts = re.split(r'[\/\-]', s)
    if len(parts[0]) == 4:
        # YYYY-MM-DD or YYYY/MM/DD
        y, m, d = map(int, parts)
    else:
        # DD-MM-YYYY or DD/MM/YYYY
        d, m, y = map(int, parts)
    return f"{d:02d}/{m:02d}/{y:04d}"

def extract_birth_date(text: str) -> str:
    """
    1) Prefer date right after the label "Birth Date" or "تاريخ الميلاد"
    2) Fallback: scan all date tokens; keep plausible years for DoB
    Returns normalized DD/MM/YYYY or "Non trouvé"
    """
    # Try labeled (English/Arabic), optional ":" or "-" and optional spaces
    m_bd = re.search(
        r'(?:Birth\s*Date|تاريخ\s*الميلاد)\s*[:\-]?\s*(\d{2}[\/\-]\d{2}[\/\-]\d{4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})',
        text,
        flags=re.IGNORECASE
    )
    if m_bd:
        try:
            return normalize_to_dd_mm_yyyy(m_bd.group(1))
        except Exception:
            pass  # fall back if something weird

    # Fallback: collect all date-like tokens and filter by likely birth years
    tokens = re.findall(DATE_TOKEN, text)
    candidates = []
    for tok in tokens:
        p = re.split(r'[\/\-]', tok)
        try:
            if len(p[0]) == 4:
                y, m, d = map(int, p)
            else:
                d, m, y = map(int, p)
        except ValueError:
            continue
        # Heuristic: exclude visa validity (2025, etc.) and absurd years
        if 1900 <= y <= 2016:
            candidates.append(tok)

    if candidates:
        try:
            return normalize_to_dd_mm_yyyy(candidates[0])
        except Exception:
            pass

    return "Non trouvé"

# ---------------------------
# Passport & Visa extraction
# ---------------------------
def extract_visa_number(text: str) -> str:
    # Some PDFs may have "Visa No." then number on next line; make it tolerant
    m = re.search(r'(?:Visa\s*No\.?\s*:?\s*)(\d{9,10})', text, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    # Fallback: standalone 9-10 digit number near the "Visa No." label in text
    # Very loose fallback; you can tighten if needed
    m2 = re.search(r'Visa\s*No\.[^\d]*(\d{9,10})', text, flags=re.IGNORECASE)
    return m2.group(1) if m2 else "Non trouvé"

def extract_passport_and_name(text: str):
    """
    Your original patterns were MRZ-like fragments.
    We'll keep the same approach + country detection.
    Returns (numero_passport, nom, prenom, detected_country_code)
    """
    patterns = {
        "IRQ": r'([A-Z]\d{8})\d?IRQ',     # Iraq
        "IDN": r'([A-Z][0-9]{7})<\d?IDN', # Indonesia
        "IND": r'([A-Z][0-9]{7})<\d?IND', # India
        "MAR": r'([A-Z][0-9]{7})<\d?MAR', # Morocco
        "GEN": r'([A-Z]\d{8})',           # Generic
        "EGY": r'([A-Z]{1}[0-9]{8})\d?EGY', # Egypt
    }

    country_code = None
    numero_passport = "Non trouvé"

    for code, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            numero_passport = m.group(1)
            country_code = code
            break

    # Try to extract name from MRZ-like pattern: COUNTRYCODESURNAME<<GIVENNAME
    nom, prenom = "nom", "prenom"
    if country_code:
        mname = re.search(rf"{country_code}([A-Z]+)<<([A-Z]+)", text)
        if mname:
            nom, prenom = mname.group(1), mname.group(2)

    return numero_passport, nom, prenom, country_code or "GEN"

# ---------------------------
# Main
# ---------------------------
if __name__ == "__main__":
    print("== Démarrage ==")
    pages = extract_text_by_pages(PDF_FILE)
    print(f"{len(pages)} page(s) chargée(s).")

    # Determine voyage type & dates from filename if needed
    if "visa_libre" in PDF_FILE:
        type_voyage = "libre"
        date_entree_madinah = False
        duree_jours = False
    else:
        type_voyage = "Groupe"
        # If you want to parse from filename, you can keep your logic here:
        # date = re.findall(r'(\d{2}_\d{2}_\d{4})', PDF_FILE)
        date_entree_madinah = "22_07_2025"
        duree_jours = 1

    # Ensure CSV exists with headers
    if not os.path.exists(CSV_FILE):
        pd.DataFrame(columns=FIELDNAMES).to_csv(CSV_FILE, index=False, encoding="utf-8")

    # Collect birth dates for the Excel one-column export
    all_birth_dates = []

    # Process page by page
    for i, texte in enumerate(pages, start=1):
        print(f"\n📄 Page {i} :")
        print("=" * 50)
        # Useful debug trace (optional; can be noisy)
        # print(texte)

        # --- Birth Date ---
        date_de_naissance = extract_birth_date(texte)
        if date_de_naissance == "Non trouvé":
            print("Aucune date de naissance trouvée.")
        else:
            print(f"Birth Date {date_de_naissance}")
            all_birth_dates.append(date_de_naissance)

        # --- Visa Number ---
        numero_visa = extract_visa_number(texte)
        print(f"Visa No. {numero_visa}")

        # --- Passport + Name ---
        numero_passport, nom, prenom, country_code = extract_passport_and_name(texte)
        print(f"Passport No. {numero_passport}")
        # If no name found via MRZ, keep defaults but you can try other heuristics here

        # --- Email / Number from JSON variant pools ---
        email = pop_first_variant(EMAIL_JSON_FILE)
        numero_tlf = pop_first_variant(NUMBER_JSON_FILE)
        if not email:
            email = ""
        if not numero_tlf:
            numero_tlf = ""

        # --- Append to CSV if not duplicate passport ---
        df = pd.read_csv(CSV_FILE, encoding="utf-8")
        if numero_passport in df.get("numero_passport", pd.Series(dtype=str)).astype(str).values:
            print(f"Le numéro de passport {numero_passport} existe déjà dans le CSV.")
        else:
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
                "heure": "",
            }
            df_new = pd.DataFrame([new_muatamer])
            df_new.to_csv(CSV_FILE, mode="a", index=False, header=False, encoding="utf-8")
            print("Ligne ajoutée au CSV.")

