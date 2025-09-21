# -*- coding: utf-8 -*-
"""
PDF → CSV extractor for KSA eVisa pages.

Adds:
- Nationality extraction (from 'Nationality / الجنسية' line) with MRZ fallback.
- Safer CSV header management to include 'nationalite'.

Dependencies:
- pdfplumber, pandas
"""

from pdfminer.high_level import extract_text  # kept if you need it elsewhere
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
# Allow overrides via environment variables without editing config.py
CSV_FILE = os.environ.get("CSV_FILE_OVERRIDE", CSV_FILE)
PDF_FILE = os.environ.get("PDF_FILE_OVERRIDE", PDF_FILE)

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
# Passport, Visa, Nationality
# ---------------------------
def extract_visa_number(text: str) -> str:
    # English
    m = re.search(r'(?:Visa\s*No\.?\s*:?\s*)(\d{9,10})', text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # Arabic variant (more permissive)
    m_ar = re.search(r'رقم\s*التأشيرة.*?(\d{9,10})', text)
    if m_ar:
        return m_ar.group(1)
    # Fallback: 9-10 digits near 'Visa No.'
    m2 = re.search(r'Visa\s*No\.[^\d]*(\d{9,10})', text, flags=re.IGNORECASE)
    return m2.group(1) if m2 else "Non trouvé"

def extract_passport_and_name(text: str):
    """
    Try MRZ-like fragments to get passport and country code.
    Returns (numero_passport, nom, prenom, detected_country_code)
    """
    patterns = {
        # Indonesia — 1 letter + 7 digits
        "IDN": r'([A-Z]\d{7})(?:<)?\d?IDN',

        # Morocco — 2 letters + 7 digits
        "MAR": r'([A-Z]{2}\d{7})(?:<)?\d?MAR',

        # Iraq — 1 letter + 8 digits
        "IRQ": r'([A-Z]\d{8})\d?IRQ',

        # Nigeria — 1 letter + 8 digits
        "NGA": r'([A-Z]\d{8})\d?NGA',

        # India — either 1 letter + 7 digits OR 2 letters + 6 digits
        "IND": r'((?:[A-Z]\d{7})|(?:[A-Z]{2}\d{6}))(?:<)?\d?IND',

        # Lebanon — 2 letters + 7 digits
        "LBN": r'([A-Z]{2}\d{7})\d?LBN',

        # Egypt — 1 letter + 8 digits
        "EGY": r'([A-Z]\d{8})\d?EGY',

        # Algeria — 9 digits starting with 3
        "DZA": r'(3\d{8})\d?DZA',

        # Malaysia — 1 letter + 8 digits
        "MYS": r'([A-Z]\d{8})\d?MYS',

        # Generic fallback — 1 letter + 8 digits (no country suffix expected)
        "GEN": r'([A-Z]\d{8})',
    }


    country_code = None
    numero_passport = "Non trouvé"

    for code, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            numero_passport = m.group(1)
            country_code = code if code != "GEN" else None
            break

    # Try to extract name from MRZ-like pattern: COUNTRYCODESURNAME<<GIVENNAME
    nom, prenom = "nom", "prenom"
    if country_code:
        mname = re.search(rf"{country_code}([A-Z]+)<<([A-Z]+)", text)
        if mname:
            nom, prenom = mname.group(1), mname.group(2)

    return numero_passport, nom, prenom, country_code or "GEN"

COUNTRY_CODE_TO_NAT = {
    "IDN": "Indonesia",
    "EGY": "Egypt",
    "IND": "India",
    "IRQ": "Iraq",
    "MAR": "Morocco",
    # extend as needed…
}

def extract_nationality(text: str, fallback_code: str | None = None) -> str:
    """
    Prefer the value on the line after 'Nationality' or 'الجنسية'.
    Example line: 'Indonesia - إندونيسيا' → keep 'Indonesia'.
    Fallback to MRZ country code mapping if label not found.
    """
    # Label-based (EN / AR)
    m = re.search(r'(?:Nationality|الجنسية)\s*[:\-]?\s*([^\r\n]+)', text, flags=re.IGNORECASE)
    if m:
        line = m.group(1).strip()
        # Keep the first Latin chunk (before Arabic or symbols)
        latin_chunks = re.findall(r"[A-Za-z][A-Za-z '\-()]*", line)
        if latin_chunks:
            nat = latin_chunks[0].strip(" -").title()
            return nat

    # MRZ fallback
    if fallback_code and fallback_code in COUNTRY_CODE_TO_NAT:
        return COUNTRY_CODE_TO_NAT[fallback_code]

    return "Non trouvé"

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
        # Put your filename parsing here if needed
        date_entree_madinah = "22_07_2025"
        duree_jours = 1

    # Ensure CSV exists with headers, including 'nationalite'
    header_fields = list(FIELDNAMES)
    if "nationalite" not in header_fields:
        header_fields.append("nationalite")

    if not os.path.exists(CSV_FILE):
        pd.DataFrame(columns=header_fields).to_csv(CSV_FILE, index=False, encoding="utf-8")
    else:
        # If CSV exists but lacks 'nationalite', add it
        _df_existing = pd.read_csv(CSV_FILE, dtype=str, keep_default_na=False, encoding="utf-8")
        if "nationalite" not in _df_existing.columns:
            _df_existing["nationalite"] = ""
            _df_existing.to_csv(CSV_FILE, index=False, encoding="utf-8")

    # Collect birth dates for optional Excel one-column export (if you need it later)
    all_birth_dates = []

    # Process page by page
    for i, texte in enumerate(pages, start=1):
        print(f"\n📄 Page {i} :")
        print("=" * 50)
        # print(texte)  # uncomment for debugging

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

        # --- Passport + Name + Country code ---
        numero_passport, nom, prenom, country_code = extract_passport_and_name(texte)
        print(f"Passport No. {numero_passport}")

        # --- Nationality ---
        nationalite = extract_nationality(texte, fallback_code=country_code)
        print(f"Nationality {nationalite}")

        # --- Email / Number from JSON variant pools ---
        email = pop_first_variant(EMAIL_JSON_FILE) or ""
        numero_tlf = pop_first_variant(NUMBER_JSON_FILE) or ""

        # --- Append to CSV if not duplicate passport ---
        df = pd.read_csv(CSV_FILE, dtype=str, keep_default_na=False, encoding="utf-8")
        existing_passports = df.get("numero_passport", pd.Series(dtype=str)).astype(str).values
        if str(numero_passport) in existing_passports:
            print(f"Le numéro de passport {numero_passport} existe déjà dans le CSV.")
        else:
            new_muatamer = {
                "nom": nom,
                "prenom": prenom,
                "date_de_naissance": date_de_naissance,
                "numero_visa": numero_visa,
                "numero_passport": numero_passport,
                "nationalite": nationalite,
                "gender": "",
                "email": email,
                "numero_tlf": numero_tlf,
                "have_a_compte": 0,
                "CREATION": 0,
                "RESERVATION": 0,
                "CONFIRMATION": 0,
                "date_reservation": "",
                "heure": "",     # <-- new field
            }
            df_new = pd.DataFrame([new_muatamer], columns=header_fields)
            df_new.to_csv(CSV_FILE, mode="a", index=False, header=False, encoding="utf-8")
            print("Ligne ajoutée au CSV.")
