from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction  # Added for coordinate clicks
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
import os
import time
import pandas as pd
from datetime import datetime, timedelta  # Added for date handling
import traceback  # Added for error logging
from mail import get_verification_code
from test import date_available
from utils import mois_en_lettres
from pdf import pop_first_variant
from selenium.webdriver.common.action_chains import ActionChains
from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    setup_driver,
    PAYS,
    PAYS_UPPER,
    TARGET_DATE,
    START_DATE,
    DURATION_DAYS ,
    RESERVATION_DIR,

)

start_date = START_DATE
duration_days = DURATION_DAYS 
pays = PAYS
paysUpper = PAYS_UPPER

csv_file = CSV_FILE
filename_email_json = EMAIL_JSON_FILE
filename_number_json = NUMBER_JSON_FILE
target_date = TARGET_DATE 


# Load CSV
df = pd.read_csv(csv_file, dtype=str)

for index, row in df.iterrows():
    dict_row = row.to_dict()
    print(f"Ligne {index+1}: {dict_row['nom']} {dict_row['prenom']} || {dict_row['type_voyage']} || {dict_row['date_entree_madinah']}")
    
    if dict_row['CREATION'] in ["1", "-1"]:
        print("Cet utilisateur a déjà un compte")
        continue

    while True:
        try:
            driver = setup_driver()
            wait = WebDriverWait(driver, 10)
            driver.implicitly_wait(5)

            # Navigate to create account
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor")))
            sign_in_button.click()

            # Wait for nationality screen
            wait.until(EC.invisibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/pbNationality")))

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNationality")))
            sign_in_button.click()

            time
            # Select nationality
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

            # Enter passport and visa
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

            # Enter date of birth
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvDOB")))
            sign_in_button.click()

            date_pickers = wait.until(lambda d: len(driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            date_pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")

            date_de_naissance = dict_row["date_de_naissance"]
            jours = date_de_naissance[0:2]
            mois = mois_en_lettres(date_de_naissance[3:5])
            annee = date_de_naissance[6:]

            date_pickers[0].click()
            date_pickers[0].clear()
            date_pickers[0].send_keys(jours)
            date_pickers[1].click()
            date_pickers[1].clear()
            date_pickers[1].send_keys(mois)
            date_pickers[2].click()
            date_pickers[2].clear()
            date_pickers[2].send_keys(annee)
            date_pickers[0].click()
            driver.hide_keyboard()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvAdd")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNo")))
            sign_in_button.click()

            # Enter password and accept terms
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword")))
            sign_in_button.send_keys("Hssouna1105@")

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()

            # Enter phone and email
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

            # Handle errors (email/phone already used)
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
                    elif "Your account" in error_text:
                        df.at[index, 'CREATION'] = "-1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        have_a_account = 1
                        break
                    elif "Visa" in error_text:
                        df.at[index, 'CREATION'] = "-1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        have_a_account = 1
                        break
                    elif "The user" in error_text:
                        df.at[index, 'CREATION'] = "-1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        have_a_account = 1
                        break
                else:
                    break
            if have_a_account:
                break

            time.sleep(1)
            # Enter verification code
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
                        if "Your account" in error_text:
                            df.at[index, 'CREATION'] = "-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account = 1
                            break
                        elif "The user" in error_text:
                            df.at[index, 'CREATION'] = "-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account = 1
                            break
                        elif "Visa" in error_text:
                            df.at[index, 'CREATION'] = "-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account = 1
                            break
                        elif "Invalid" in error_text:
                            df.at[index, 'CREATION'] = "-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account = 1
                            break
                        elif "The OTP" in error_text:
                            have_a_account=1
                            break
                    else:
                        break
                if have_a_account:
                    break
                        
            else:
                print("❌ Aucune validation trouvée.")
                break
            df.at[index, 'CREATION'] = "1"
            # Handle permissions and location
            create_now = 0
            try:
                
                wait = WebDriverWait(driver, 10)
                driver.save_screenshot("before_check.png")
                print(driver.page_source)
                try:
                    sign_in_button = wait.until(
                            EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/check_message"))
                        )
                    sign_in_button.click()
                    sign_in_button = wait.until(
                            EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_confirm"))
                        )
                    sign_in_button.click()
                except TimeoutException:
                        pass  # Element not found, skip
                element = wait.until(
                        EC.presence_of_element_located(
                            (AppiumBy.ID, "com.android.packageinstaller:id/permission_message")
                        )
                    )
                
                print("Autorisation de l'application requise.\n")
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.android.packageinstaller:id/permission_allow_button")))
                sign_in_button.click()
                
                df.to_csv(csv_file, index=False, encoding="utf-8")
                create_now = 1
                # Navigate to Noble Rawdah booking
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL")))
                sign_in_button.click()

                # Select gender
                gender = dict_row.get("gender", "Unknown")  # Assuming 'gender' column in CSV
                if gender == "Unknown":
                    try:
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv")))
                        sign_in_button.click()
                        gender = "F"
                        print("✅ Bouton femme cliqué.")
                    except:
                        try:
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv")))
                            sign_in_button.click()
                            gender = "H"
                            print("✅ Bouton homme cliqué.")
                        except Exception as e:
                            print(f"❌ Aucun bouton de genre trouvé : {e}")
                            break
                
                # Check for existing booking
                all_elements = driver.find_elements(AppiumBy.XPATH, "//*")
                book = 0
                for element in all_elements:
                    element_text = element.text or ""
                    if any(phrase in element_text for phrase in [
                        "You already have an existing booking for",
                        "Vous avez déjà une réservation",
                        "have an active permit"
                    ]):
                        df.at[index, 'RESERVATION'] = "1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        book = 1
                        break

                if book:
                    break

                time.sleep(1.5)
                # Select date
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date")))
                sign_in_button.click()
                time.sleep(1.5)

              #scroller l'ecran un peu
                screen_size = driver.get_window_size()
                start_x = screen_size['width'] // 2
                start_y = int(screen_size['height'] * 0.7)
                end_y = int(screen_size['height'] * 0.56)
                time.sleep(0.5)
                driver.swipe(start_x, start_y, start_x, end_y, 500)
                #time.sleep(1.5)
                screenshot_path = "images/calendar_screenshot.png"
                driver.save_screenshot(screenshot_path)
                print(f"Screenshot sauvegardé à : {screenshot_path}")

                available_dates=date_available(screenshot_path)
                # Définir la date de début (format "JJ_MM_YYYY")
                

                # Convertir `start_date` en format date
                start_dt = datetime.strptime(start_date, "%d_%m_%Y")
                start_dt=start_dt+timedelta(days=1)

                # Calculer la date de fin (start + durée)
                end_dt = start_dt + timedelta(days=duration_days - 1)


                # Reformater les dates sous "JJ/MM" pour la comparaison
                start_str = start_dt.strftime("%d/%m")
                end_str = end_dt.strftime("%d/%m")
                print(available_dates)



                # Filtrer les dates disponibles entre `start_date` et `end_date`
                filtered_dates = []
                for date_str, x, y in available_dates:
                    try:
                        date_obj = datetime.strptime(date_str, "%d/%m")
                        # Replace year so it matches start_dt and end_dt
                        date_obj = date_obj.replace(year=start_dt.year)

                        if start_dt <= date_obj <= end_dt:
                            filtered_dates.append((date_str, x, y))
                    except ValueError:
                        print(f"⚠ Date format error with '{date_str}'")

                # Afficher les résultats
                print(f"\n🔹 Plage de dates : {start_str} → {end_str}")
                print("\n📅 Dates disponibles dans la plage sélectionnée :")
                print(len(filtered_dates))
                # Select target date
                clicked = False
                actions = ActionChains(driver)
                for date, x, y in filtered_dates:
                    if date == target_date:
                        print(f"🎯 Date ciblée trouvée : {date} | 📍 Coordonnées originales: ({x}, {y})")
                        actions.w3c_actions.pointer_action.move_to_location(x, y)
                        time.sleep(0.5)
                        actions.w3c_actions.pointer_action.click()
                        time.sleep(0.5)  # Pause pour s'assurer que le clic est enregistré
                        actions.w3c_actions.perform()
                        time.sleep(0.5)
                        date_reser = date
                       
                        clicked = True
                        break

                if not clicked:
                    print(f"❌ La date {target_date} n'a pas été trouvée.")
                    break

                # Confirm date
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.TextView[@text='Confirmer']")))
                sign_in_button.click()
                
               
                # Select time
                all_texts = set()
                elements_list = []
                while True:
                    all_elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")
                    new_texts = [element.text for element in all_elements if element.text not in all_texts]
                    if not new_texts:
                        break
                    for element in all_elements:
                        if element.text not in all_texts:
                            all_texts.add(element.text)
                            elements_list.append(element)

                target_text = "06:00 PM" if gender == "M" else "10:00 AM"
                trouve = 0
                for element in elements_list:
                    if element.text == target_text:
                        element.click()
                        trouve = 1
                        break
                if not trouve:
                    elements_list[-1].click()
                    print(f"Élément '{target_text}' non trouvé, dernier élément sélectionné.")
                 # Juste avant ta boucle ou au début, définis et crée le dossier :
                os.makedirs(RESERVATION_DIR, exist_ok=True)

                # … puis, juste après ta ligne df.to_csv(...), insère :
                screenshot_filename = f"{dict_row['nom']}_{dict_row['numero_passport']}.png"
                screenshot_path = os.path.join(RESERVATION_DIR, screenshot_filename)
                driver.get_screenshot_as_file(screenshot_path)
                print(f"📷 Capture d'écran de la réservation enregistrée sous : {screenshot_path}")


                # Confirm time and booking
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/continue_button")))
                sign_in_button.click()
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue")))
                sign_in_button.click()

                # Verify booking
                elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_rating_3")
                if elements and "Neutre" in elements[0].text:
                    df.at[index, 'RESERVATION'] = "1"
                    df.at[index, 'heure'] = target_text
                    df.at[index, 'date_reservation'] = f"{date_reser}/{start_dt.year}"
                    reservation_date = pd.to_datetime(df.at[index, "date_reservation"], format="%d/%m/%Y")
                    now = datetime.now()
                    if now - reservation_date > timedelta(hours=48):
                        print("Plus de 48 heures se sont écoulées depuis la réservation.")
                    else:
                        print("Moins de 48 heures se sont écoulées.")
                    df.to_csv(csv_file, index=False, encoding="utf-8")
                    create_now = 1
                    break

            except Exception as e:
                print(f"Une erreur est survenue : {e}")
                traceback.print_exc()

            if create_now:
                break

        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            traceback.print_exc()

        finally:
            try:
                driver.quit()
            except Exception as close_error:
                print(f"Erreur lors de la fermeture du driver : {close_error}")