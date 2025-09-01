from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import pandas as pd
import traceback  # Added for error logging
from mail import get_verification_code
from utils import mois_en_lettres
from pdf import pop_first_variant
from login import make_reservation as login_make_reservation
from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    setup_driver,
    PAYS,
    PAYS_UPPER,
)

pays = PAYS
paysUpper = PAYS_UPPER

csv_file = CSV_FILE
filename_email_json = EMAIL_JSON_FILE
filename_number_json = NUMBER_JSON_FILE


# Load CSV
df = pd.read_csv(csv_file, dtype=str)

def process_user(driver, index, row):
    dict_row = row.to_dict()
    print(f"Ligne {index+1}: {dict_row['nom']} {dict_row['prenom']} || {dict_row['type_voyage']} || {dict_row['date_entree_madinah']}")
    if dict_row['CREATION'] in ["1", "-1"]:
        print("Cet utilisateur a déjà un compte")
        return
    while True:
        try:
            wait = WebDriverWait(driver, 10)
            driver.implicitly_wait(5)
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor")))
            sign_in_button.click()
            wait.until(EC.invisibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/pbNationality")))
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNationality")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtSearch")))
            sign_in_button.send_keys(pays)
            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle")
            found = False
            for el in elements:
                if el.text.strip().lower() == paysUpper:
                    el.click()
                    found = True
                    print("✅ 'Iraq' cliqué avec succès.")
                    break
            if not found:
                print("❌ 'Iraq' introuvable dans la liste.")
                break
            numero_passport = dict_row["numero_passport"]
            if numero_passport == "Non trouvé":
                break
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassport")))
            sign_in_button.send_keys(numero_passport)
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            numero_visa = dict_row["numero_visa"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo")))
            sign_in_button.send_keys(numero_visa)
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvDOB")))
            sign_in_button.click()
            date_pickers = wait.until(lambda d: len(driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            date_pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")
            date_de_naissance = dict_row["date_de_naissance"]
            jours = date_de_naissance[0:2]
            mois = mois_en_lettres(date_de_naissance[3:5])
            annee = date_de_naissance[6:]
            date_pickers[0].click(); date_pickers[0].clear(); date_pickers[0].send_keys(jours)
            date_pickers[1].click(); date_pickers[1].clear(); date_pickers[1].send_keys(mois)
            date_pickers[2].click(); date_pickers[2].clear(); date_pickers[2].send_keys(annee)
            date_pickers[0].click(); driver.hide_keyboard()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvAdd")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNo")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword")))
            sign_in_button.send_keys("Hssouna1105@")
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox")))
            sign_in_button.click()
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()
            numero_tlf = dict_row["numero_tlf"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo")))
            sign_in_button.send_keys(numero_tlf)
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            email = dict_row["email"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
            sign_in_button.send_keys(email)
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            have_a_account = 0
            while True:
                elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                if elements:
                    error_text = elements[0].text
                    print(f"Erreur détectée : {error_text}")
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
                    sign_in_button.click()
                    if "Email is already used" in error_text:
                        email = pop_first_variant(filename_email_json)
                        df.at[index, 'email'] = email
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
                        sign_in_button.send_keys(email)
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                        sign_in_button.click()
                    elif "The mobile number" in error_text:
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgBack")))
                        sign_in_button.click()
                        number = pop_first_variant(filename_number_json)
                        df.at[index, 'numero_tlf'] = number
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo")))
                        sign_in_button.send_keys(number)
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                        sign_in_button.click()
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
                        sign_in_button.send_keys(email)
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                        sign_in_button.click()
                    elif "Your account" in error_text or "Visa" in error_text or "The user" in error_text:
                        df.at[index, 'CREATION'] = "-1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        have_a_account = 1
                        break
                else:
                    break
            if have_a_account:
                break
            time.sleep(1)
            code = get_verification_code(email)
            if code:
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text")))
                sign_in_button.send_keys(code)
                print(f"✅ Code trouvé : {code}")
                while True:
                    elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                    if elements:
                        error_text = elements[0].text
                        print(f"Erreur détectée : {error_text}")
                        if any(keyword in error_text for keyword in ["Your account", "The user", "Visa", "Invalid", "The OTP"]):
                            df.at[index, 'CREATION'] = "-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account = 1
                            break
                    else:
                        break
                if have_a_account:
                    break
            else:
                print("❌ Aucune validation trouvée.")
                break
            df.at[index, 'CREATION'] = "1"
            df.to_csv(csv_file, index=False, encoding="utf-8")
            login_make_reservation(driver, index, dict_row)
            break
        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            traceback.print_exc()

driver = setup_driver()

for index, row in df.iterrows():
    try:
        process_user(driver, index, row)
    except Exception as e:
        print(f"❌ Erreur fatale : {e}")
        traceback.print_exc()
        try:
            driver.quit()
        except Exception:
            pass
        driver = setup_driver()

driver.quit()