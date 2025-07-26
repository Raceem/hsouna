import traceback
from appium import webdriver
from appium.options.android import UiAutomator2Options  # Nouvelle méthode pour définir les capacités
import time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from mail import get_verification_code
import pandas as pd
from datetime import datetime, timedelta
import cv2
import numpy as np
from selenium.webdriver.common.action_chains import ActionChains
from test import date_available
from datetime import datetime, timedelta

nation = "Iraq"


csv_file = "C:/Users/lenovo/Desktop/riadh/omra/iraq/informations.csv"


def setup_driver():
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.platform_version = "14"  # Remplace par la version exacte de ton appareil
    options.device_name = "RFCW50CH1ND"  # Remplace par l'ID de ton appareil (adb devices)
    options.app_package = "com.moh.nusukapp"
    options.app_activity = "com.moh.nusukapp/com.app.nusuk.LoginRegistrationActivity"
    options.automation_name = "uiautomator2"
    options.set_capability("platformName", "Android")
    options.set_capability("automationName", "UiAutomator2")
    options.set_capability("deviceName", "Android Device")
    options.set_capability("noReset", True)
    options.set_capability("newCommandTimeout", 300)
    options.set_capability("ignoreHiddenApiPolicyError", True)
    options.set_capability("disableWindowAnimation", True)
    options.set_capability("autoGrantPermissions", True)
    return webdriver.Remote("http://127.0.0.1:4723", options=options)

# Attendre un peu que l'application se charge
df = pd.read_csv(csv_file, dtype=str)
for index, row in df.iterrows():
    dict=row.to_dict()
    print(f"Ligne {index+1 } : {dict['nom']} {dict['prenom']} || {dict['type_voyage']}" )
    if dict['CREATION']=="0":
        print("cet muatamor n'a pas de compte")
        continue
    if dict['CREATION']=="-1":
        print("cet muatamor a un compte avant creation.py")
        continue
    if dict['RESERVATION']=="1":
        print("cet muatamor est reservé")
        continue
    if dict['RESERVATION']=="-1":
        print("cet muatamor mch tawa")
        continue
       
    while True:
        try:
                    # Connexion au serveur Appium
                    driver = setup_driver()
                    # Attendre un peu que l'application se charge
                    driver.implicitly_wait(10)
                    # Attendre que le bouton soit visible
                    wait = WebDriverWait(driver, 10)

                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
                    
                    # Cliquer sur le bouton
                    sign_in_button.click()
                    

                    # Utiliser ActionChains pour cliquer sur le bouton
                    actions = ActionChains(driver)
                    
                
                    
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor")))
                    # Cliquer sur le bouton
                    sign_in_button.click()
                    time.sleep(2)


                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNationality")))
                    
                    # Cliquer sur le bouton
                    sign_in_button.click()

                    


                    
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtSearch")))
                    
                    # Cliquer sur le bouton
                    sign_in_button.send_keys(nation)
                    elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle")
                    #for e in elements:
                        #print(f">>> '{e.text}'")
                    element_to_click = wait.until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@resource-id, 'com.moh.nusukapp:id/tvTitle') and @text='Iraq']")))
                    
                    # Cliquer sur l'élément
                    element_to_click.click()
                    numero_passport=dict["numero_passport"]
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassport")))
                    sign_in_button.send_keys(numero_passport)

                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword")))
                    sign_in_button.send_keys("Hssouna1105@")

                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
                    sign_in_button.click()

                    while True:
                            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                            if elements:  # Si la liste n'est pas vide => élément trouvé
                                error_text = elements[0].text
                                print(f"Erreur détectée : {error_text}")
                                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
                                sign_in_button.click()
                                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn")))
                                sign_in_button.click()
                                
                            else:
                                print("Aucune erreur détectée. L'élément n'existe pas.")
                                break

                    
                    # Récupérer le code
                    code = get_verification_code(dict["email"])
                    if code:
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text")))
                        sign_in_button.send_keys(code)
                        print(f"✅ Code trouvé : {code}")
                    else:
                        print("❌ Aucune validation trouvée.")

                    #sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.android.permissioncontroller:id/permission_allow_button")))
                    #sign_in_button.click()

                    #sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvShareLocation")))
                    #sign_in_button.click()

                    #sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.android.permissioncontroller:id/permission_allow_foreground_only_button")))
                    #sign_in_button.click()

                    #sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNo")))
                    #sign_in_button.click()
                    

                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvNobleRawdahTitle")))
                    sign_in_button.click()
                    

                    type = None  # initialiser la variable

                    try:
                        sign_in_button = wait.until(EC.presence_of_element_located(
                            (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv")))
                        sign_in_button.click()
                        type = "M"
                        print("✅ Bouton homme cliqué.")
                    except Exception:
                        try:
                            sign_in_button = wait.until(EC.presence_of_element_located(
                                (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv")))
                            sign_in_button.click()
                            type = "F"
                            print("✅ Bouton femme cliqué.")
                        except Exception as e:
                            print("❌ Aucun des boutons n’a été trouvé.")
                            print("Erreur :", str(e))
                            type = "Unknown"

                        
                    
                    
                    print('hh')
                    time.sleep(1)

                    # Récupérer tous les éléments visibles
                    all_elements = driver.find_elements(AppiumBy.XPATH, "//*")
                    book=0
                    print("/n📌 Contenu complet de l'écran :/n")
                    for element in all_elements:
                            element_id = element.get_attribute("resource-id") or "Aucun ID"
                            element_text = element.text or "Aucun texte"
                            if "You already have an existing booking for" in element_text :
                                        df.at[index, 'RESERVATION'] ="1"
                                        df.to_csv(csv_file, index=False, encoding="utf-8")
                                        book=1
                                        break
                            element_class = element.get_attribute("class") or "Aucune classe"
                            #print(f"🔹 ID: {element_id}, Texte: {element_text}, Classe: {element_class}")
                    if book==1:
                        break
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date")))
                    sign_in_button.click()
                    
                    time.sleep(1.5)

                    #scroller l'ecran un peu
                    screen_size = driver.get_window_size()
                    start_x = screen_size['width'] // 2
                    start_y = int(screen_size['height'] * 0.6)
                    end_y = int(screen_size['height'] * 0.55)

                    driver.swipe(start_x, start_y, start_x, end_y, 500)
                    screenshot_path = "images/calendar_screenshot.png"
                    driver.save_screenshot(screenshot_path)
                    print(f"Screenshot sauvegardé à : {screenshot_path}")

                    available_dates=date_available(screenshot_path)
                    # Définir la date de début (format "JJ_MM_YYYY")
                    start_date = "26_07_2025"
                    duration_days = 1  # Durée en jours

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
                    filtered_dates = [
                        (date, x,y) for date, x,y in available_dates
                        if start_str <= date <= end_str  # Comparaison uniquement sur JJ/MM
                    ]

                    # Afficher les résultats
                    print(f"/n🔹 Plage de dates : {start_str} → {end_str}")
                    print("/n📅 Dates disponibles dans la plage sélectionnée :")
                    print(len(filtered_dates))
                    # Chercher la date 21/07 dans la liste des dates disponibles filtrées
                    #if type=="M":
                    target_date = "27/07"
                    #else :
                        #target_date = "26/07"
                    clicked = False

                    for date, x, y in filtered_dates:
                        if date == target_date:
                            print(f"🎯 Date ciblée trouvée : {date} | 📍 Coordonnées originales: ({x}, {y})")
                            actions.w3c_actions.pointer_action.move_to_location(x, y)
                            actions.w3c_actions.pointer_action.click()
                            actions.w3c_actions.perform()
                            date_reser = date
                            print(f"✅ Cliqué sur la date {date} à : x={x}, y={y}")
                            clicked = True
                            break

                    if not clicked:
                        print(f"❌ La date {target_date} n'a pas été trouvée dans les dates disponibles.")

                    # Continuer si cliqué avec succès
                    if clicked:                        
                        sign_in_button = wait.until(EC.presence_of_element_located((
                            AppiumBy.XPATH, "//android.widget.TextView[@text='Confirm']"
                        )))
                        sign_in_button.click()

                        

                        time.sleep(1)
                        trouve = 0
                        if type=="M":
                            target_text = "11:40 AM"  # Remplace par l'heure ou le texte que tu cherches
                        else :
                            target_text = "09:00 AM"  # Remplace par l'heure ou le texte que tu cherches
                            
                        all_texts = set()  # Utiliser un set pour éviter les doublons
                        elements_list = []  # Stocker les éléments trouvés (Appium WebElements)
                        while True:
                            # Récupérer les éléments visibles
                            all_elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")
                            #print(all_texts)
                            new_texts = [element.text for element in all_elements if element.text not in all_texts]
                            if not new_texts:  # Si aucun nouvel élément, arrêter la boucle
                                break
                            for element in all_elements:
                                if element.text not in all_texts:
                                    all_texts.add(element.text)
                                    elements_list.append(element)  # Ajouter l'élément WebElement
                            
                            for element in elements_list:
                                if element.text == target_text:
                                    element.click()
                                    trouve=1
                                    break
                            
                            if trouve == 1:
                                break
                            try:
                                driver.find_element(
                                    AppiumBy.ANDROID_UIAUTOMATOR,
                                    'new UiScrollable(new UiSelector().scrollable(true))'
                                )
                                print("L'élément est scrollable, on peut scroller.")
                                driver.find_element(
                                    AppiumBy.ANDROID_UIAUTOMATOR,
                                    'new UiScrollable(new UiSelector().scrollable(true)).scrollForward();'
                                )
                            except:
                                print("L'élément n'est pas scrollable.")
                         

                        print(all_texts)
                        
                        # ➜ Sélectionner et cliquer sur un élément spécifique
                        
                            
                        if trouve==0:
                            elements_list[-1].click()
                            print(f"Élément '{target_text}' non trouvé")
                            #target_text = elements_list[-1].text
                    

                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/continue_button")))
                        sign_in_button.click()

                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue")))
                        sign_in_button.click()

                        try :
                            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_rating_3")
                            if elements:  # Si la liste n'est pas vide => élément trouvé
                                    text = elements[0].text
                                    print(text)
                                    if "Neutral" in text:

                                        df.at[index, 'RESERVATION'] ="1"
                                        df.at[index,'heure']=target_text
                                        now = datetime.now()
                                        df.at[index, "date_reservation"] = str(date_reser) + "/" + str(now.month) + "/" + str(now.year)
                                        df.to_csv(csv_file, index=False, encoding="utf-8")
                                        driver.press_keycode(3)  # Home screen button
                                        time.sleep(1)
                                        driver.press_keycode(187)  # Show recent apps
                                        time.sleep(1)
                                        driver.tap([(566, 2154)])
                                        create_now=1

                                        break
                                    
                                        
                                    else:
                                        print("chno")
                                        break
                    
                        except Exception as e:
                            print("Une erreur est survenue :", e)
                            traceback.print_exc()
                        print('hh')
                        time.sleep(1)

                        # Récupérer tous les éléments visibles
                        all_elements = driver.find_elements(AppiumBy.XPATH, "//*")

                        print("/n📌 Contenu complet de l'écran :/n")
                        for element in all_elements:
                            element_id = element.get_attribute("resource-id") or "Aucun ID"
                            element_text = element.text or "Aucun texte"
                            element_class = element.get_attribute("class") or "Aucune classe"
                            print(f"🔹 ID: {element_id}, Texte: {element_text}, Classe: {element_class}")
                        
                        """# Récupérer tous les éléments visibles
                        element = driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().text("Prière de Maghrib"));'
                        )
                        all_elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")

                        for element in all_elements:
                            print(element.text)
                        """
                    else :
                        print("il y a pas de dates disponibles dans cette periode")
                        break

                    
                        
                        
                        
                    




                    


        
                    
                    time.sleep(1005)
        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            driver.press_keycode(3)  # Home screen button
            time.sleep(1)
            driver.press_keycode(187)  # Show recent apps
            time.sleep(1)
            driver.tap([(566, 2154)])
            traceback.print_exc()
            time.sleep(5)  # Attendre avant de relancer pour éviter de surcharger le système

        finally:
            try:
                driver.quit()
            except Exception as close_error:
                print(f"Erreur lors de la fermeture du driver : {close_error}")   