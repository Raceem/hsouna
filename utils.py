import json
from csv import DictWriter
from itertools import product
import csv
import pandas as pd
import cv2
import numpy as np

def remove_dots(email):
    local_part, domain = email.split("@")
    # Supprimer tous les points de la partie locale
    local_part_no_dots = local_part.replace(".", "")
    # Reconstituer l'email
    return f"{local_part_no_dots}@{domain}"
    
def generate_all_saudi_numbers():
    """
    Génère toutes les possibilités de numéros mobiles saoudiens commençant par '058'
    et suivis de 7 chiffres (de 0000000 à 9999999).
    """
    prefix = "59"
    for i in range(10**7):
        yield prefix + f"{i:07d}"

def save_saudi_numbers_to_json(filename_json, count=10028):
    """
    Génère les 'count' premiers numéros mobiles saoudiens et les enregistre dans un fichier JSON.
    
    Args:
        filename_json (str): Nom du fichier JSON de destination.
        count (int): Nombre de numéros à générer (par défaut 1028).
    """
    generator = generate_all_saudi_numbers()
    numbers = [next(generator) for _ in range(count)]
    
    with open(filename_json, 'w', encoding='utf-8') as f:
        json.dump(numbers, f, ensure_ascii=False, indent=4)
    print(f"{len(numbers)} numéros enregistrés dans {filename_json}")

def generate_dot_variants_mails(email, max_variants=10000):
    local_part, domain = email.split("@")
    n = len(local_part) - 1
    variants = []
    
    for pattern in product([False, True], repeat=n):
        if len(variants) >= max_variants:
            break
        variant_local = "".join(local_part[i] + ("." if pattern[i] else "") for i in range(n)) + local_part[-1]
        variants.append(variant_local + "@" + domain)

    return variants


def save_variants_to_json(email, filename_email_json):
    
    variants = generate_dot_variants_mails(email)
    with open(filename_email_json, 'w', encoding='utf-8') as f:
        json.dump(variants, f, ensure_ascii=False, indent=4)
    print(f"{len(variants)} variantes enregistrées dans {filename_email_json}")


def create_csv(csv_file,fieldnames):
    with open(csv_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        
        # Écrire l'en-tête
        writer.writeheader()
    print(f"Fichier CSV '{csv_file}' créé avec la colonne 'creation'.")
def mois_en_lettres(numero_mois):
    mois_dict = {
        "01": "janvier", "02": "février", "03": "mars", "04": "avril",
        "05": "mai", "06": "juin", "07": "juillet", "08": "août",
        "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre"
    }
    return mois_dict.get(numero_mois, "Mois invalide")

def img_to(path):
    # Analyser l'image pour détecter les dates disponibles
    image = cv2.imread(path)
    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 50, 50])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv_image, lower_green, upper_green)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Extraire les coordonnées des dates disponibles
    available_dates_coords = []
    for contour in contours:
        (x, y, w, h) = cv2.boundingRect(contour)
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)  # Dessiner un rectangle vert autour des cercles

    # Sauvegarder l'image avec les contours détectés
    output_path = "calendar_with_contours.png"
    cv2.imwrite(output_path, image)

    print(f"Image avec contours sauvegardée à : {output_path}")
    for contour in contours:
        (x, y, w, h) = cv2.boundingRect(contour)
        center_x = x + w // 2
        center_y = y + h // 2
        available_dates_coords.append((center_x, center_y))
    available_dates_coords.pop(0)
    print("Coordonnées des dates disponibles :", available_dates_coords)
def corriger_id(df, id_col="id"):
    """
    Vérifie et corrige les sauts dans la colonne des ID en les réassignant séquentiellement.
    
    :param df: DataFrame contenant la colonne d'ID
    :param id_col: Nom de la colonne contenant les ID
    :return: DataFrame avec les ID corrigés
    """
    df = df.sort_values(by=id_col).reset_index(drop=True)  # Trier et réindexer
    df[id_col] = range(1, len(df) + 1)  # Réassigner les ID séquentiels
    return df
import os
from PyPDF2 import PdfMerger
def merge_pdfs_in_folder(folder_path, output_file):
    merger = PdfMerger()
    
    # Lister et trier les fichiers PDF
    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]
    pdf_files.sort()  # Trie par nom (modifiable)

    if not pdf_files:
        print("Aucun fichier PDF trouvé dans le dossier.")
        return

    for pdf in pdf_files:
        full_path = os.path.join(folder_path, pdf)
        print(f"Ajout de : {pdf}")
        merger.append(full_path)

    # Sauvegarde du PDF fusionné
    merger.write(output_file)
    merger.close()
    print(f"\nTous les fichiers PDF ont été fusionnés dans : {output_file}")

# Exemple d'utilisation
from config import FOLDER_NAME, BASE_DIR, CSV_FILE, EMAIL_JSON_FILE, NUMBER_JSON_FILE

if __name__ == "__main__":
    
    csv_file = CSV_FILE

    fieldnames = ["id","nom", "prenom", "date_de_naissance", "numero_visa","email","numero_tlf", "numero_passport","type_voyage","date_entree_madinah","duree_jours","have_a_compte","CREATION","RESERVATION","CONFIRMATION","date_reservation","heure"]

    create_csv(csv_file, fieldnames)
    dossier = os.path.join(BASE_DIR, "PDFs")
    fichier_sortie = os.path.join(BASE_DIR, FOLDER_NAME, "VISA 23_07_2025.pdf")

    merge_pdfs_in_folder(dossier, fichier_sortie)


    """
    # Exemple de génération de numéros et d'e-mails
    save_saudi_numbers_to_json(NUMBER_JSON_FILE, count=10280)
    email_base = "mailboybanana@gmail.com"
    save_variants_to_json(email_base, EMAIL_JSON_FILE)
    

    
        df = pd.read_csv(csv_file, dtype=str)
    for i in range(159,165):
        df.at[i,"RESERVATION"]="1"
        df.at[i,"CONFIRMATION"]="1"


    df = pd.read_csv(csv_file, dtype=str)
    for i in range(0,70):
        df.at[i,"CREATION"]="1"
    df.to_csv(csv_file, index=False, encoding="utf-8")
    
    

        
    df.drop(i, inplace=True)  

    df.reset_index(drop=True, inplace=True)  # Réinitialise l'index après suppression
    """
