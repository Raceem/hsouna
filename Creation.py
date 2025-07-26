from appium import webdriver
from appium.options.android import UiAutomator2Options  # Nouvelle méthode pour définir les capacités
import time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from mail import get_verification_code
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
import pandas as pd
from utils import mois_en_lettres
from pdf import pop_first_variant

csv_file = "C:/Users/lenovo/Desktop/riadh/omra/iraq/informations.csv"
filename_email_json = "C:/Users/lenovo/Desktop/riadh/omra/email_variants.json"
filename_number_json = "C:/Users/lenovo/Desktop/riadh/omra/saudi_numbers.json"

def setup_driver():
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.platform_version = "14"  # Remplace par la version exacte de ton appareil
    options.device_name = "RFCW50CH1ND"  # Remplace par l'ID de ton appareil (adb devices)
    options.app_package = "com.moh.nusukapp"
    options.app_activity = "com.moh.nusukapp/com.app.nusuk.LoginRegistrationActivity"
    options.automation_name = "uiautomator2"
    return webdriver.Remote("http://127.0.0.1:4723", options=options)

# Attendre un peu que l'application se charge
df = pd.read_csv(csv_file, dtype=str)
for index, row in df.iterrows():
    
    dict=row.to_dict()
    print(f"Ligne {index+1 } : {dict['nom']} {dict['prenom']} || {dict['type_voyage']} || {dict['date_entree_madinah']}"  )
    if dict['CREATION']=="1" or dict['CREATION']=="-1":
        print("cet muatamor a un compte")
        continue
    print(index)
    while True: 
        try:
            driver = setup_driver()
            driver.implicitly_wait(10)
            # Attendre que le bouton soit visible
            wait = WebDriverWait(driver, 10)

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor")))
            sign_in_button.click()
            time.sleep(2)

            element_id = "com.moh.nusukapp:id/pbNationality"
            while True:
                
                try:
                    have_a_account=0
                    create_now=0
                    element_id = "com.moh.nusukapp:id/pbNationality"
                    # Vérifier si l'élément "pbNationality" est affiché
                    loader = driver.find_element(AppiumBy.ID, element_id)
                    if loader.is_displayed():
                        print("L'élément pbNationality est toujours visible, on continue d'attendre...")
                        time.sleep(0.5)
                    else:
                        break
                except NoSuchElementException:
                    print(f"✅ L'élément {element_id} n'a pas été trouvé, on sort de la boucle.")
                    break

                # Si l'élément est affiché, on clique sur le bouton "imgBack"
                try:
                    element_id = "com.moh.nusukapp:id/imgBack"
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, element_id)))
                    sign_in_button.click()
                    print("Retour arrière effectué.")
                except Exception as e:
                    print(f"❌ Erreur : Impossible de cliquer sur {element_id}. Erreur : {e}")
                
                # Réessayer de cliquer sur le bouton "tvVisitor" après retour
                try:
                    element_id = "com.moh.nusukapp:id/tvVisitor"
                    sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, element_id)))
                    sign_in_button.click()
                    print("Retour à l'écran de création de compte.")
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ Erreur : Impossible de trouver {element_id}. Erreur : {e}")
                time.sleep(2)

            # Après avoir quitté la boucle, on clique sur l'élément "tvNationality"
            element_id = "com.moh.nusukapp:id/tvNationality"
            try:
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, element_id)))
                sign_in_button.click()
                print("Clique sur tvNationality effectué.")
            except Exception as e:
                print(f"❌ Erreur : Impossible de trouver {element_id}. Erreur : {e}")

            


            

            
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtSearch")))
            sign_in_button.send_keys("Iraq")
            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle")
            found = False
            for el in elements:
                if el.text.strip().lower() == "iraq":
                    el.click()
                    found = True
                    print("✅ 'Morocco' cliqué avec succès.")
                    break

            if not found:
                print("❌ 'Morocco' introuvable dans la liste.")


            numero_passport=dict["numero_passport"]
            if numero_passport=="Non trouvÃ©":
                break
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassport")))
            sign_in_button.send_keys(numero_passport)

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            numero_visa=dict["numero_visa"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo")))
            sign_in_button.send_keys(numero_visa)

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvDOB")))
            sign_in_button.click()

            def get_date_pickers():
                return driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")

            # Attendre que les pickers soient présents (généralement trois)
            wait.until(lambda d: len(get_date_pickers()) >= 3)

            # Récupérer les pickers
            date_pickers = get_date_pickers()

            # Afficher les valeurs actuelles pour vérifier l'ordre (jour, mois, année)
            print("date de naissance")

            # Supposons que l'ordre est le suivant : [jour, mois, année]
            # Modifier les valeurs en utilisant des valeurs numériques valides
            # Exemple : 21 mars 2024
            date_de_naissance=dict["date_de_naissance"]
            jours=date_de_naissance[0:2]
            wait.until(EC.visibility_of(get_date_pickers()[0]))
            date_pickers[0].click()
            date_pickers[0].clear()
            date_pickers[0].send_keys(jours)  # Jour

            mois=date_de_naissance[3:5]
            mois=mois_en_lettres(mois)
            date_pickers[1].click()
            date_pickers[1].clear()
            date_pickers[1].send_keys(mois)

            annee= date_de_naissance[6:len(dict["date_de_naissance"])]
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

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtPassword")))
            sign_in_button.send_keys("Hssouna1105@")

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox")))
            sign_in_button.click()

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount")))
            sign_in_button.click()
            
            numero_tlf=dict["numero_tlf"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo")))
            sign_in_button.send_keys(numero_tlf)

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()

            email=dict["email"]
            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
            sign_in_button.send_keys(email)

            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
            sign_in_button.click()
            time.sleep(2)
            try:
                while True:
                    elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
                    if elements:  # Si la liste n'est pas vide => élément trouvé
                        error_text = elements[0].text
                        print(f"Erreur détectée : {error_text}")
                        sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
                        sign_in_button.click()
                        if "Email is already used" in error_text:
                            email=pop_first_variant(filename_email_json)
                            df.at[index, 'email'] =email
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
                            sign_in_button.send_keys(email)
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                            sign_in_button.click()
                        if "The mobile number" in error_text:
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/imgBack")))
                            sign_in_button.click()
                            number=pop_first_variant(filename_number_json)
                            df.at[index, 'numero_tlf'] =number
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo")))
                            sign_in_button.send_keys(number)

                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                            sign_in_button.click()

                            email=dict["email"]
                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/edtEmail")))
                            sign_in_button.send_keys(email)

                            sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvContinue")))
                            sign_in_button.click()
                        if "Your account" in error_text:
                            print("hey")
                            df.at[index, 'CREATION'] ="-1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            have_a_account=1
                            break
                            
                            


                    else:
                        print("Aucune erreur détectée. L'élément n'existe pas.")
                        break
                if have_a_account==1:
                    break
            except Exception as e:
                print("Une erreur est survenue :", e)


            if have_a_account==1:
                    continue
            """"""

           
            time.sleep(2)
            # Récupérer le code
            email=dict["email"]
            code = get_verification_code(email)
            if code:
                sign_in_button = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text")))
                sign_in_button.send_keys(code)
                print(f"✅ Code trouvé : {code}")
            else:
                print("❌ Aucune validation trouvée.")
            print("✅ Bouton cliqué avec succès !")
            time.sleep(1)
            try :
                elements = driver.find_elements(AppiumBy.ID, "com.android.permissioncontroller:id/permission_message")
                if elements:  # Si la liste n'est pas vide => élément trouvé
                        print("semh")
                        text = elements[0].text
                        print(text)
                        if "Autoriser" in text:

                            df.at[index, 'CREATION'] ="1"
                            df.to_csv(csv_file, index=False, encoding="utf-8")
                            create_now=1
                            break
                        else:
                            print("chno")
                            break
            except Exception as e:
                print("Une erreur est survenue :", e)
            if create_now==1:
                    continue
            # Attendre un changement dans la page (nouveau texte, nouveau bouton, etc.)
            wait.until(EC.presence_of_element_located((AppiumBy.XPATH, "//*")))  # Attendre que n'importe quel élément change
            time.sleep(2)
            # Récupérer tous les éléments après le clic 
            all_elements = driver.find_elements(AppiumBy.XPATH, "//*")

            print("\n📌 Contenu de la page après le clic :\n")
            for element in all_elements:
                element_id = element.get_attribute("resource-id") or "Aucun ID"
                element_text = element.text or "Aucun texte"
                print(f"🔹 ID: {element_id}, Texte: {element_text}")
            break
        except Exception as e:
            print(f"❌ Erreur : {e, element_id}")
            print("🔄 Tentative de relance...")
            time.sleep(3)  # Attendre avant de relancer pour éviter de surcharger le système

        finally:
            # Fermer le driver dans le cas où il y aurait eu un problème
            driver.quit()