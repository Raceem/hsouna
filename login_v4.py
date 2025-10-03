# login2.py - Worker-compatible login script
"""
Login automation with workers integration.
Preserves original button clicking logic while adapting to workers framework.
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta
import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from mail import get_verification_code
from config import APP_PACKAGE, hard_reset_app
from logutil import get_shared_logger
from utils_v4 import _set_df, has_booking, has_previous_booking, _save_df,_load_df, has_previous_booking_before_365, pregrant_location_permissions, _pregrant_notification_permissions

# -----------------------------------------------------------------------------/
logger = get_shared_logger("login2")



# -----------------------------------------------------------------------------/
# Worker-compatible entry point

def run_login_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    csv_path: str,
    target_ddmm: str
    ) -> pd.DataFrame:
    """
    Single-row login in-process for workers.
    - driver: persistent Appium driver (already started)
    - row_index: index to write back into csv_path
    - row_series: pd.Series with the row data at start
    - csv_path: source CSV we update in place
    - target_ddmm: 'DD/MM' string for target date
    """
    # 0) Always re-read CSV to ensure fresh view
    df = _load_df(csv_path)

    # 1) Convert to dict for processing
    dict = row_series.to_dict()

    # 2) Execute login logic (original code preserved)
    try:
        _execute_login_logic(driver, dict, df, row_index, target_ddmm)
    except Exception as e:
        logger.exception("run_login_on_row fatal: %s", e)

    # 3) Flush once at the end
    _save_df(df, csv_path)
    hard_reset_app(driver, os.getenv("APP_PACKAGE", "com.moh.nusukapp"))
    return df

def _execute_login_logic(driver, dict, df, index, target_date):
    """Original login logic preserved exactly as requested"""
    wait = WebDriverWait(driver, 10,poll_frequency=0.2)
    

    try:
        # Original login sequence - button clicking logic preserved exactly
        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
        sign_in_button.click()

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor")))
        sign_in_button.click()

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNationality")))
        sign_in_button.click()

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtSearch")))

        nationalite = dict["nationalite"]
        sign_in_button.send_keys(nationalite)
        wait.until(EC.presence_of_element_located((AppiumBy.XPATH, f"//android.widget.TextView[@text='{nationalite}']"))).click()

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword")))
        sign_in_button.send_keys("Hssouna1105@")

        numero_passport=dict["numero_passport"]
        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassport")))
        sign_in_button.send_keys(numero_passport)

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
        sign_in_button.click()

        i=0
        while i<10:
            time.sleep(0.5)
            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc") #adjust
            if elements:  # Si la liste n'est pas vide => élément trouvé
                error_text = elements[0].text
                print(f"Erreur détectée : {error_text}")
                i=i+1
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
                sign_in_button.click()
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
                sign_in_button.click()
                

            else:
                print("Aucune erreur détectée. L'élément n'existe pas.")
                break
        if i>=9:
            _set_df(df, index, "CREATION", "-1")
            return
        # Attendre un peu pour que le bon code soit envoyé
        time.sleep(2)
        pregrant_location_permissions(driver, APP_PACKAGE)
        _pregrant_notification_permissions(driver, APP_PACKAGE)

        # Récupérer le code
        code = get_verification_code(dict['email'])
        if code:
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text")))
            sign_in_button.send_keys(code)
            logger.info(f"✅ Code trouvé : {code}")
        else:
            print("❌ Aucune validation trouvée.")
            return

        # Vérifier les erreurs OTP et réessayer avec un nouveau code si nécessaire
        otp_error_count = 0
        max_otp_retries = 2

        while otp_error_count < max_otp_retries:
            # Vérifier s'il y a une erreur OTP
            time.sleep(1)
            otp_errors = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
            if otp_errors:
                error_msg = (otp_errors[0].text or "").lower()
                if any(k in error_msg for k in ["invalid", "incorrect", "wrong", "expired", "otp", "code"]):
                    print(f"❌ Erreur OTP détectée: {error_msg}")
                    otp_error_count += 1

                    if otp_error_count < max_otp_retries:
                        print(f"🔄 Tentative de récupération d'un nouveau code (essai {otp_error_count + 1})")
                        # Effacer le champ OTP
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
                        sign_in_button.click()
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text")))
                        sign_in_button.clear()

                        # Récupérer un nouveau code
                        time.sleep(1)
                        new_code = get_verification_code(dict['email'])
                        if new_code and new_code != code:
                            #print(f"✅ Nouveau code trouvé: {new_code}")
                            sign_in_button.send_keys(new_code)
                            code = new_code
                            time.sleep(2)
                            continue
                        else:
                            print("❌ Impossible de récupérer un nouveau code")
                            break
                    else:
                        print("❌ Nombre maximum de tentatives OTP atteint")
                        # Cliquer sur OK pour fermer le dialog d'erreur
                        try:
                            btn = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tvYes")
                            btn.click()
                            print("Dialog d'erreur OTP fermé")
                        except Exception:
                            print("Impossible de fermer le dialog d'erreur OTP")
                        break
                else:
                    # Pas une erreur OTP, sortir de la boucle
                    break
            else:
                
                # Pas d'erreur détectée, sortir de la boucle
                break
        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/iv_close")))
        sign_in_button.click()
        screen_size = driver.get_window_size()
        start_x = screen_size['width'] // 2
        start_y = int(screen_size['height'] * 0.6)
        end_y = int(screen_size['height'] * 0.4)
        driver.swipe(start_x, start_y, start_x, end_y, 450)
        time.sleep(2)        

        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNobleRawdahTitle")))
        sign_in_button.click()

        type = 'F'  # initialiser la variable

        gender_element = wait.until(
            EC.any_of(
                EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv")),
                EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv")),
            )
        )

        gender_element.click()

        time.sleep(2)

        
        if has_previous_booking(driver):
            logger.info("Existing previous booking detected; marking RESERVATION=-1 ")
            _set_df(df, index, "RESERVATION", "-1")
            return
        has_booking_boolen, extracted_date = has_booking(driver)
        if has_booking_boolen:
            logger.info("Booking exists for date: {extracted_date}") 
            _set_df(df, index, "RESERVATION", "1")
            _set_df(df, index, "date_reservation", extracted_date)
            _set_df(df, index, "heure", "10:00 AM")

            return

        time.sleep(1)  # Petite pause supplémentaire pour observer
        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date")))
        sign_in_button.click()
        time.sleep(2)

        # Date selection logic (need to get jours from target_date)
        jours = target_date.split('/')[0]
        Scrolable = False  # You might want to determine this dynamically
        
        if not Scrolable :
            date_parent = driver.find_element(
                AppiumBy.XPATH,
                f"//android.view.View[android.widget.TextView[1][@text={jours}]]"
            )
            date_parent.click()
        else :
            screen_size = driver.get_window_size()
            start_x = screen_size['width'] // 2
            start_y = int(screen_size['height'] * 0.6)
            end_y = int(screen_size['height'] * 0.4)
            driver.swipe(start_x, start_y, start_x, end_y, 500)
            time.sleep(1)

            date_parent = driver.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().text("{jours}").instance(2)'
            )
            date_parent.click()

        time.sleep(1)

        button = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Button")
        button.click()

        time.sleep(1)
        
        

        all_texts = set()  # Utiliser un set pour éviter les doublons
        elements_list = []  # Stocker les éléments trouvés (Appium WebElements)
        elements_list_text=[]
        while True:
            # Récupérer les éléments visibles
            all_elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")
            
            new_texts = [element.text for element in all_elements if element.text not in all_texts]
            if not new_texts:  # Si aucun nouvel élément, arrêter la boucle
                break
            for element in all_elements:
                if element.text not in all_texts:
                    all_texts.add(element.text)
                    elements_list.append(element)  # Ajouter l'élément WebElement
                    elements_list_text.append(element.text)

        target_text = elements_list[0].text
        elements_list[0].click()
        
               

        element_to_click = wait.until(
            EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/continue_button"))
        )
        element_to_click.click()

        element_to_click = wait.until(
            EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue"))
        )
        element_to_click.click()
        if has_previous_booking_before_365(driver):
            logger.info("Existing previous booking detected before 365; marking RESERVATION=-1 ")
            _set_df(df, index, "RESERVATION", "-1")

            return
        time.sleep(2)
        # Verify booking
        elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_rating_3")
        if elements :
            logger.info('ALL Done')
            now = datetime.now()
            _set_df(df, index, "RESERVATION", "1")
            _set_df(df, index, "heure", target_text)
            _set_df(df, index, "date_reservation", f"{target_date}/{str(now.year)}")
        else :
            for element in elements:
                element_text = element.text or ""
                if "enough capacity" in element_text:
                    driver.terminate_app('com.moh.nusukapp')
                    break

    except Exception as e:
        print(f"❌ Erreur : {e}")
        print("🔄 Tentative de relance...")
        driver.terminate_app("com.moh.nusukapp")