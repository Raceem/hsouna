import os
import traceback
import time
from datetime import datetime, timedelta

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from mail import get_verification_code
from config import (
    CSV_FILE,
    FOLDER_NAME,
    PAYS,
    PAYS_UPPER,
    BASE_DIR,
    RAWDHA_DIR,
    setup_driver,
)


df = pd.read_csv(CSV_FILE, dtype=str)

for index, row in df.iterrows():
    data = row.to_dict()
    print(f"Ligne {index + 1}: {data['nom']} {data['prenom']} || {data['type_voyage']}")
    if data["RESERVATION"] == "0":
        print("cet muatamor n'a pas de reservation")
        continue

    if data["CONFIRMATION"] == "0":
        date_reservation = data["date_reservation"]
        if pd.notna(date_reservation) and pd.notna(data['heure']):
            jours = int(date_reservation[0:2])
            mois = int(date_reservation[3:5])
            heure_str = data['heure']
            try:
                heure = datetime.strptime(heure_str, "%I:%M %p").hour
            except ValueError:
                heure = int(heure_str)
            now = datetime.now()
            date_reservation_full = datetime(
                year=now.year, month=mois, day=jours, hour=heure, minute=0
            )
            time_difference = date_reservation_full - now
            if time_difference <= timedelta(hours=0):
                print("cet reservation est expirée")
                continue
            if time_difference > timedelta(hours=48):
                print("cet reservation n'est pas encore disponible pour confirmer")
                continue
        else:
            print("cet reservation n'est pas d'heures et de dates")
            continue
    else:
        print("cet reservation est confirmé")
        continue

    while True:
        try:
            driver = setup_driver()
            driver.implicitly_wait(3)
            wait = WebDriverWait(driver, 10)

            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"))
            )
            sign_in_button.click()
            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"))
            )
            sign_in_button.click()

            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"))
            )
            sign_in_button.click()
            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"))
            )
            sign_in_button.send_keys(PAYS)
            sign_in_button = wait.until(
                EC.element_to_be_clickable(
                    (
                        AppiumBy.XPATH,
                        f"//android.widget.TextView[@resource-id='com.moh.nusukapp:id/tvTitle' and @text='{PAYS}']",
                    )
                )
            )
            sign_in_button.click()

            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"))
            )
            sign_in_button.send_keys(data['numero_passport'])
            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"))
            )
            sign_in_button.send_keys("Hssouna1105@")
            sign_in_button = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"))
            )
            sign_in_button.click()

            max_login_attempts = 6
            login_attempt = 0
            while login_attempt < max_login_attempts:
                error_elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                if error_elements:
                    print(f"Erreur détectée : {error_elements[0].text}")
                    sign_in_button = wait.until(
                        EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvYes"))
                    )
                    sign_in_button.click()
                    sign_in_button = wait.until(
                        EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"))
                    )
                    sign_in_button.click()
                    login_attempt += 1
                else:
                    break
            if login_attempt >= max_login_attempts:
                df.at[index, 'CREATION'] = "-1"
                df.at[index, 'RESERVATION'] = "0"
                df.at[index, 'heure'] = ""
                df.at[index, 'date_reservation'] = ""
                break

            time.sleep(1)
            code = get_verification_code(data['email'])
            if code:
                sign_in_button = wait.until(
                    EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"))
                )
                sign_in_button.send_keys(code)
                print(f"✅ Code trouvé : {code}")
            else:
                print("❌ Aucune validation trouvée.")
            have_a_account = 0
            while True:
                elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                if elements:
                    error_text = elements[0].text
                    print(f"Erreur détectée : {error_text}")
                    if "The OTP" in error_text:
                        have_a_account = 1
                        break
                else:
                    break
            if have_a_account:
                break

            sign_in_button = wait.until(
                EC.presence_of_element_located((AppiumBy.ID, "com.android.packageinstaller:id/permission_allow_button"))
            )
            sign_in_button.click()

         
            sign_in_button = wait.until(
                EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"))
            )
            sign_in_button.click()
        
           

            try:
                sign_in_button = wait.until(
                    EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btnConfirm"))
                )
                sign_in_button.click()
                print("n'est pas encore confirmé.")
                sign_in_button = wait.until(
                    EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue"))
                )
                sign_in_button.click()
                
                sign_in_button = wait.until(
                    EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes"))
                )
                sign_in_button.click()
            except Exception:
                print("confirmé mais n'a pas fait de screenshot.")

            sign_in_button = wait.until(
                EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btnAction"))
            )
            sign_in_button.click()

            print("✅ Bouton cliqué avec succès !")
            
            time.sleep(1)
            #scroller l'ecran un peu
            screen_size = driver.get_window_size()
            start_x = screen_size['width'] // 2
            start_y = int(screen_size['height'] * 0.6)
            end_y = int(screen_size['height'] * 0.55)
            time.sleep(0.5)
            driver.swipe(start_x, start_y, start_x, end_y, 500)
            time.sleep(1)
            os.makedirs(RAWDHA_DIR, exist_ok=True)
            screenshot_path = os.path.join(
                RAWDHA_DIR, f"{data['nom']}_{data['numero_passport']}.png"
            )
            driver.get_screenshot_as_file(screenshot_path)
            print(f"Capture d'écran enregistrée sous : {screenshot_path}")
            df.at[index, 'CONFIRMATION'] = "1"
            df.to_csv(CSV_FILE, index=False, encoding="utf-8")

            break
        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            traceback.print_exc()
            time.sleep(5)
        finally:
            try:
                driver.quit()
            except Exception as close_error:
                print(f"Erreur lors de la fermeture du driver : {close_error}")
