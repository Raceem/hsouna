from pdfminer.high_level import extract_text
import re
import pandas as pd
import json


folder_name = "indonesia5"
email_base = "hsounakobbi@enis.tn"
filename_email_json = "C:/Users/lenovo/Desktop/riadh/omra/email_variants.json"
filename_number_json = "C:/Users/lenovo/Desktop/riadh/omra/saudi_numbers.json"

# Nom du fichier CSV à créer
csv_file = f"C:/Users/lenovo/Desktop/riadh/omra/{folder_name}/informations.csv"
# Définition des colonnes (avec la nouvelle colonne 'creation')
fieldnames = ["id","nom", "prenom", "date_de_naissance", "numero_visa","email","numero_tlf", "numero_passport","type_voyage","date_entree_madinah","duree_jours","have_a_compte","CREATION","RESERVATION","CONFIRMATION","date_reservation","heure"]
pdf_path = f"C:/Users/lenovo/Desktop/riadh/omra/{folder_name}/VISA 23_07_2025.pdf"
def pop_first_variant(filename_email_json):
    
    # Charger le contenu du fichier JSON
    with open(filename_email_json, 'r', encoding='utf-8') as f:
        variants = json.load(f)
    
    # Vérifier qu'il y a au moins un élément et le supprimer
    if variants:
        first_variant = variants.pop(0)  # Récupérer et supprimer le premier élément
        print(f"Élément récupéré : {first_variant}")
    else:
        print("La liste est vide, rien à récupérer.")
        return None
    
    # Réécrire le fichier JSON avec la liste mise à jour
    with open(filename_email_json, 'w', encoding='utf-8') as f:
        json.dump(variants, f, ensure_ascii=False, indent=4)
    print(f"Le fichier {filename_email_json} a été mis à jour.")
    
    return first_variant

def extract_text_by_page(file_path):
    with open(file_path, "rb") as file:
        # Extraire tout le texte et le diviser par page
        text = extract_text(file)
        pages = text.split("\f")  # "\f" est le séparateur de page dans pdfminer
        pages.remove('')
        print("hh")
        return pages
    
import pdfplumber

def extract_text_by_pages(file_path):
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            print(text)
            if text:
                pages.append(text)
    return pages


if __name__ == "__main__":
    print("ss")
    pages = extract_text_by_pages(pdf_path)

    print("ss")
    if pdf_path.find("visa_libre")== -1 :
        type_voyage="Groupe"
        date = re.findall(r'(\d{2}_\d{2}_\d{4})', pdf_path)
        date_entree_madinah="22_07_2025"
        duree_jours=1
    else :
        type_voyage="libre"
        date_entree_madinah=False
        duree_jours=False
    print(pages)
    # Affichage page par page
    for i, texte in enumerate(pages, start=1):
        print("s")
        print(f"📄 Page {i} :\n")
        print("=" * 50)  # Séparateur entre les pages
        dates = re.findall(r'(\d{2}/\d{2}/\d{4})', texte)
        # Filtrer les dates dont l'année est entre 1800 et 2025
        dates_naissances = []
        for date in dates:
            jour, mois, annee = date.split('/')
            annee = int(annee)
            if 1800 < annee < 2025:
                dates_naissances.append(date)
        date_de_naissance=dates_naissances[0]
        print(texte)
        # Extraction du numéro visa (supposons qu'il soit composé de 10 chiffres)
        match_visa = re.search(r'(\d{10})', texte)
        print(match_visa)
        numero_visa = match_visa.group(1) if match_visa else "Non trouvé"

        # Extraction du numéro de passport (supposons qu'il commence par une lettre suivie de chiffres)
        patterns = {
            "IRQ": r'([A-Z]\d{8})\d?IRQ',              # Iraq
            "IDN": r'([A-Z][0-9]{7})<\d?IDN',          # Indonesia
            "IND": r'([A-Z][0-9]{7})<\d?IND',          # India
            "MAR": r'([A-Z][0-9]{7})<\d?MAR',          # Maroc
            "GEN": r'([A-Z]\d{7})',                    # Générique
        }

        match_passport = None
        country_code = None

        # Recherche du pattern de passeport
        for code, pattern in patterns.items():
            match = re.search(pattern, texte)
            if match:
                match_passport = match
                country_code = code
                break

        # Résultat final
        numero_passport = match_passport.group(1) if match_passport else "Non trouvé"
        print(numero_passport)
        # Expression régulière pour capturer les deux noms après "TUN"
        pattern = rf"{country_code}([A-Z]+)<<([A-Z]+)"
        match = re.search(pattern, texte)
        print(match)
        email=pop_first_variant(filename_email_json)
        numero_tlf=pop_first_variant(filename_number_json)
        if match:
            nom = match.group(1) 
            prenom = match.group(2) 
        else:
            print("Aucune correspondance trouvée.")

        df = pd.read_csv(csv_file, encoding="utf-8")
        new_muatamer = {
        "id": len(df)+1,  # sera écrasé par l'ID généré si besoin
        "nom": nom,
        "prenom": prenom,
        "date_de_naissance": date_de_naissance,
        "numero_visa": numero_visa,
        "email":email,
        "numero_tlf":numero_tlf,
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
        if numero_passport in df["numero_passport"].values:
            print(f"Le numéro de passport {numero_passport} existe déjà dans le CSV.")
        else:
            # Convertir le dictionnaire en DataFrame (avec une seule ligne)
            df_new = pd.DataFrame([new_muatamer])
            # Ajout en mode append sans réécrire l'en-tête
            df_new.to_csv(csv_file, mode="a", index=False, header=False)