import os
import time
import traceback
import pandas as pd

from appium.webdriver.common.appiumby import AppiumBy
from paddleocr import logger
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

from mail import get_verification_code
from utils import mois_en_lettres
from pdf import pop_first_variant
from login import (
    make_reservation as login_make_reservation,
    accept_privacy_if_present,
    safe_click,
    safe_send_keys,
    update_fast_settings,
)
from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    setup_driver,

)

# ====== Constants / Config ======


APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")
csv_file = CSV_FILE
filename_email_json = EMAIL_JSON_FILE
filename_number_json = NUMBER_JSON_FILE

ERROR_DESC_ID = "com.moh.nusukapp:id/tv_error_desc"
ERROR_OK_ID   = "com.moh.nusukapp:id/tvYes"
BACK_BTN_ID   = "com.moh.nusukapp:id/imgBack"

# ====== Utilities ======
def get_nationality_from_row(row_dict):
    """
    Return (search_text, match_key_lower) for nationality.
    Falls back to config PAYS / PAYS_UPPER if the CSV value is missing.
    """
    val = row_dict.get("nationalite")
    try:
        is_missing = val is None or (pd.isna(val)) or (str(val).strip() == "")
    except Exception:
        is_missing = True

    if is_missing:
        # fallback to config if the CSV column is empty for this row
        return 

    s = str(val).strip()
    return s, s.lower()

def pregrant_location_permissions(driver, package: str = APP_PACKAGE):
    """Grant location permissions via adb shell so the popup never appears."""
    cmds = [
        ("pm", ["grant", package, "android.permission.ACCESS_FINE_LOCATION"]),
        ("pm", ["grant", package, "android.permission.ACCESS_COARSE_LOCATION"]),
    ]
    for cmd, args in cmds:
        try:
            logger.info("ADB grant: %s %s", cmd, " ".join(args))
            driver.execute_script(
                "mobile: shell",
                {"command": cmd, "args": args, "includeStderr": True, "timeout": 5000},
            )
        except Exception as e:
            logger.info("ADB grant failed (ok to ignore): %s", e)

def wait_for_error_text(driver, timeout=1, poll=0.2):
    """
    Poll quickly for the error dialog text. Returns the text or None.
    Fast but reliable for transient popups.
    """
    end = time.time() + timeout
    while time.time() < end:
        try:
            els = driver.find_elements(AppiumBy.ID, ERROR_DESC_ID)
            if els:
                txt = (els[0].text or "").strip()
                if txt:
                    return txt
        except StaleElementReferenceException:
            pass
        time.sleep(poll)
    return None

def click_error_yes(wait):
    """Wait for the dialog 'Yes' button to be clickable, then click it."""
    yes = wait.until(EC.element_to_be_clickable((AppiumBy.ID, ERROR_OK_ID)))
    yes.click()

def handle_possible_error_after_mobile_or_pre_email(driver, wait, index, email_holder, df):
    """
    Lightweight handler used **before** the email step to catch early popups
    (e.g., after mobile Continue). Returns:
      - "handled" if it fixed something and advanced to email step
      - "have_account" if user should be marked as existing
      - "none" if no popup detected
    """
    err = wait_for_error_text(driver, timeout=4)
    if not err:
        return "none"

    print(f"Erreur détectée : {err}")
    click_error_yes(wait)
    low = err.lower()

    if "email is already used" in low or ("email" in low and "already" in low and "use" in low):
        new_email = pop_first_variant(filename_email_json)
        df.at[index, 'email'] = new_email
        email_holder["email"] = new_email
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), new_email, "Email retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
        df.to_csv(csv_file, index=False, encoding="utf-8")
        return "handled"

    if ("mobile" in low or "phone" in low) and ("already" in low or "used" in low or "registered" in low or "exists" in low):
        safe_click(driver, (AppiumBy.ID, BACK_BTN_ID), "Back from mobile error")
        new_number = pop_first_variant(filename_number_json)
        df.at[index, 'numero_tlf'] = new_number
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), new_number, "Mobile retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
        # We should now be at email; re-enter tracked email:
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_holder["email"], "Email after mobile retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
        df.to_csv(csv_file, index=False, encoding="utf-8")
        return "handled"

    if any(k in low for k in ("your account", "the user", "visa")):
        df.at[index, 'CREATION'] = "-1"
        df.to_csv(csv_file, index=False, encoding="utf-8")
        return "have_account"

    if "otp" in low or "invalid" in low:
        df.to_csv(csv_file, index=False, encoding="utf-8")
        return "handled"

    df.to_csv(csv_file, index=False, encoding="utf-8")
    return "handled"

# ====== Load CSV once ======
df = pd.read_csv(csv_file, dtype=str)
if "gender" not in df.columns:
    df["gender"] = ""
if "reserved_men" not in df.columns:
    df["reserved_men"] = "0"
if "reserved_women" not in df.columns:
    df["reserved_women"] = "0"
df.to_csv(csv_file, index=False, encoding="utf-8")
# ====== Core flow ======
def process_user(driver, index, row):
    dict_row = row.to_dict()
    logger.info(f"Ligne {index+1}: {dict_row['nom']} {dict_row['prenom']} || {dict_row['type_voyage']} || {dict_row['date_entree_madinah']}")
    if dict_row.get('CREATION') in ["1", "-1"]:
        logger.info("Cet utilisateur a déjà un compte")
        return

    while True:
        try:
            # fast waits; rely on explicit waits + popup poller
            wait = WebDriverWait(driver, 10)
            try:
                driver.implicitly_wait(1)
            except Exception:
                pass

            # --- Start Create Account flow ---
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType")

            # --- Nationality selection ---
            wait.until(EC.invisibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/pbNationality")))
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), "Nationality")
            pays, paysUpper = get_nationality_from_row(dict_row)

            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"), pays, "Search nationality")

            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle")
            found = False
            for el in elements:
                if (el.text or "").strip().lower() == paysUpper:
                    el.click()
                    found = True
                    print("✅ Nationalité sélectionnée.")
                    break
            if not found:
                print("❌ Nationalité introuvable dans la liste.")
                break

            # --- Passport ---
            numero_passport = dict_row.get("numero_passport", "")
            if numero_passport == "Non trouvé" or not numero_passport:
                print("❌ Numéro de passeport manquant.")
                break
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), numero_passport, "Passport number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after passport")

            # --- Visa ---
            numero_visa = dict_row.get("numero_visa", "")
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo"), numero_visa, "Visa number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after visa")

            # --- Date of Birth ---
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvDOB"), "DOB field")
            wait.until(lambda d: len(driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            date_pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")

            date_de_naissance = dict_row.get("date_de_naissance", "01/01/1990")
            jours = date_de_naissance[0:2]
            mois = mois_en_lettres(date_de_naissance[3:5])
            annee = date_de_naissance[6:]

            date_pickers[0].click(); date_pickers[0].clear(); date_pickers[0].send_keys(jours)
            date_pickers[1].click(); date_pickers[1].clear(); date_pickers[1].send_keys(mois)
            date_pickers[2].click(); date_pickers[2].clear(); date_pickers[2].send_keys(annee)
            date_pickers[0].click(); driver.hide_keyboard()

            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after DOB")

            # --- No mobile prompt (do you have KSA mobile?) ---
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNo"), "No mobile prompt")

            # --- Password + Terms ---
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"), "Hssouna1105@", "Password")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox"), "MuslimTerms")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox"), "Terms")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount submit")

            # --- Mobile number (with quick check for early popup) ---
            numero_tlf = dict_row.get("numero_tlf", "")
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), numero_tlf, "Mobile number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile")

            email_holder = {"email": dict_row.get("email", "")}

           
            # --- Email (ENTER + CONTINUE) ---
            email = email_holder["email"]
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email, "Email")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email")

            # ========= RESTORED OLD BEHAVIOR: handle popups after Email → Continue =========
            email_current = email  # mutable local copy, will be used later (e.g., OTP)
            while True:
                error_text = wait_for_error_text(driver, timeout=2)
                if not error_text:
                    break  # no popup → proceed

                print(f"Erreur détectée : {error_text}")
                click_error_yes(wait)
                low = error_text.lower()

                if "email is already used" in low or ("email" in low and "already" in low and "use" in low):
                    # rotate email
                    email_current = pop_first_variant(filename_email_json)
                    df.at[index, 'email'] = email_current
                    # re-enter email and continue
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
                    df.to_csv(csv_file, index=False, encoding="utf-8")
                    continue  # loop again in case another popup appears

                elif ("mobile" in low or "phone" in low) :
                    # go back to mobile screen
                    safe_click(driver, (AppiumBy.ID, BACK_BTN_ID), "Back from mobile error")
                    # rotate number
                    new_number = pop_first_variant(filename_number_json)
                    df.at[index, 'numero_tlf'] = new_number
                    # re-enter number and continue
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), new_number, "Mobile retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
                    # re-enter the (possibly updated) email and continue
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email after mobile retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
                    df.to_csv(csv_file, index=False, encoding="utf-8")
                    continue  # loop again for any further popups

                elif ("your account" in low) or ("the user" in low) or ("visa" in low):
                    # mark as has account, persist, and bail out of user creation
                    df.at[index, 'CREATION'] = "-1"
                    df.to_csv(csv_file, index=False, encoding="utf-8")
                    return

                else:
                    # Unknown/other error: persist and let outer flow proceed (or add branches)
                    df.to_csv(csv_file, index=False, encoding="utf-8")
                    break
            # ============================================================================
            # Use the possibly-updated email for subsequent steps
            email = email_current

            # --- Pre-grant location and OTP handling ---
            time.sleep(1)
            pregrant_location_permissions(driver, APP_PACKAGE)

            code = get_verification_code(email)
            if code:
                otp_field = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text")))
                otp_field.send_keys(code)
                print(f"✅ Code trouvé : {code}")

                # quick check for OTP-related popups
                otp_err = wait_for_error_text(driver, timeout=4)
                if otp_err:
                    print(f"Erreur détectée : {otp_err}")
                    click_error_yes(wait)
                    low = otp_err.lower()
                    if any(k in low for k in ("your account", "the user", "visa")):
                        df.at[index, 'CREATION'] = "-1"
                        df.to_csv(csv_file, index=False, encoding="utf-8")
                        return
                    df.to_csv(csv_file, index=False, encoding="utf-8")

            # Mark creation successful locally (optional—you may set in reservation)
            dict_row['CREATION'] = "1"
            df.at[index, 'CREATION'] = "1"
            df.to_csv(csv_file, index=False, encoding="utf-8")
            accept_privacy_if_present(driver, wait)
            # --- Proceed to reservation within the same fresh session ---
            login_make_reservation(driver, index, dict_row)
            break

        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            traceback.print_exc()
            # Let the while loop retry (within same row/session) if applicable

# ====== MAIN: cold restart per row ======
for index, row in df.iterrows():
    driver = None
    dict_row = row.to_dict()
    print(f"Ligne {index+1}: {dict_row.get('nom')} {dict_row.get('prenom')} || {dict_row.get('type_voyage')} || {dict_row.get('date_entree_madinah')}")
    if dict_row.get('CREATION') in ["1", "-1"]:
        print("Cet utilisateur a déjà un compte")
        continue
    try:
        print(f"\n---- Processing row (orig index={index}) ----")
        driver = setup_driver()
        update_fast_settings(driver)

        try:
            driver.implicitly_wait(1)  # keep tiny for speed; rely on explicit waits
        except Exception:
            pass

        # Pre-grant right after fresh session
        pregrant_location_permissions(driver, APP_PACKAGE)

        # Do the work for this row
        process_user(driver, index, row)

    except Exception as e:
        print(f"❌ Erreur fatale (row {index}): {e}")
        traceback.print_exc()

    finally:
        # Always end the row with a cold shutdown to guarantee a clean next start
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        driver = None
