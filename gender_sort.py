# gender_sort.py
from __future__ import annotations

import time
from typing import Dict, Tuple

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from Creation import _click_error_yes
from rowstore import load_df as _load_df, save_df as _save_df
from login import update_fast_settings  # reuse your fast driver settings
from CreationReservation import (
    _ensure_common_columns as _ensure_common_columns_cr,  # keep consistent columns
    _wait_for_error_text as _wait_for_error_text_cr,
    _pregrant_location_permissions as _pregrant_loc,
    _pregrant_notification_permissions as _pregrant_notif,
)
from login import (
    accept_privacy_if_present,
    safe_click,
    safe_send_keys,
)
from mail import get_verification_code
from pdf import pop_first_variant
from config import EMAIL_JSON_FILE as _EMAIL_JSON_FILE, NUMBER_JSON_FILE as _NUMBER_JSON_FILE, APP_PACKAGE

EMAIL_JSON_FILE = _EMAIL_JSON_FILE
NUMBER_JSON_FILE = _NUMBER_JSON_FILE


def _append_then_delete(all_csv: str, dest_csv: str, row_dict: Dict[str, str]) -> bool:
    """
    Append row_dict to dest_csv (dedupe by numero_passport), then delete the
    claimed row from ALL by returning True so the worker finalizes-and-deletes.
    This function itself only returns True/False (append success).
    """
    from rowstore import with_csv_lock, load_df, save_df, append_row_dict

    numero = (row_dict.get("numero_passport") or "").strip().lower()
    with with_csv_lock(dest_csv):
        df_dest = load_df(dest_csv)
        if not df_dest.empty and "numero_passport" in df_dest.columns:
            existing = df_dest["numero_passport"].astype(str).str.strip().str.lower()
            if numero and numero in set(existing):
                # Already routed previously -> treat as success (no duplicate append)
                return True
        # Append
        append_row_dict(dest_csv, row_dict)
        return True


def _determine_gender_via_permit(driver) -> str | None:
    """
    From the home screen after creation+privacy, open Rawdah and try to click permit.
    Returns 'H' or 'F' (or None if not determinable).
    """
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/iv_close"), timeout=3, retries=1):
            raise RuntimeError("bonus tile not available")
    # Open Rawdah
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"), name="nobleRawdahLL"):
        return None

    # Try Woman first (like your reservation fallback), then Men
    if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv", timeout=2):
        return "F"
    if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=2):
        return "H"
    # Try alternate order in case of visual readiness
    if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv_2", timeout=2):
        return "H"
    if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv_2", timeout=2):
        return "F"
    return None


def run_gender_probe_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    all_csv_path: str,
    target_ddmm: str,  # not used for reservation here, but kept for symmetry
    hommes_csv_path: str,
    femmes_csv_path: str,
) -> Tuple[pd.DataFrame, str]:
    """
    Single-row: create account, determine gender (no reservation), route to HOMMES/FEMMES.
    Returns (updated_df_for_all, outcome)
      outcome in {"ROUTED_H","ROUTED_F","REQUEUED","SKIPPED","DROPPED"}
      DROPPED -> mark CREATION=-1 and drop from ALL
    """

    df = _ensure_common_columns_cr(_load_df(all_csv_path))
    data = row_series.to_dict()
    wait = WebDriverWait(driver, 10, poll_frequency=0.25)

    # Driver quick tune
    try:
        driver.implicitly_wait(1)
    except Exception:
        pass
    update_fast_settings(driver)
    _pregrant_loc(driver, APP_PACKAGE)
    _pregrant_notif(driver, APP_PACKAGE)

    # Skip rows with CREATION in {"1","-1"}
    creation_flag = str(data.get("CREATION", "")).strip()
    if creation_flag in {"1", "-1"}:
        return df, "SKIPPED"

    # If gender is already set, route immediately (append-then-delete handled by caller)
    g_existing = (data.get("gender") or "").strip().upper()
    if g_existing in {"H", "F"}:
        return df, f"ROUTED_{g_existing}"

    # 1) Create account (similar to CreationReservation.run_creation_on_row) up to email/OTP
    # Landing → Create Account → Visitor
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount"):
        return df, "REQUEUED"
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType"):
        return df, "REQUEUED"

    # Nationality
    try:
        wait.until(EC.invisibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/pbNationality")))
    except Exception:
        pass
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), "Nationality"):
        return df, "REQUEUED"

    nat = (data.get("nationalite") or "").strip()
    if nat:
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"), nat, "Search nationality")
        found = False
        for el in driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle"):
            if (el.text or "").strip().lower() == nat.lower():
                try:
                    el.click()
                except Exception:
                    pass
                found = True
                break
        if not found:
            return df, "REQUEUED"

    # Passport
    numero_passport = str(data.get("numero_passport", "")).strip()
    if not numero_passport or numero_passport.lower() == "non trouvé":
        return df, "REQUEUED"
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), numero_passport, "Passport number")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after passport")

    # Visa
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo"), str(data.get("numero_visa", "")), "Visa number")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after visa")

    # DOB quick path: rely on default (or CSV) year; keep minimal logic to pass screen
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvDOB"), "DOB field"):
        return df, "REQUEUED"
    try:
            wait.until(lambda d: len(d.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")
    except TimeoutException:
            return df


    dob = str(data.get("date_de_naissance", "01/01/1990"))
    dd, mm, yyyy = dob[:2], dob[3:5], dob[6:]

    try:
        pickers[2].click(); pickers[2].clear(); pickers[2].send_keys("1985")
        pickers[2].click(); pickers[2].clear(); pickers[2].send_keys("1985")
        
        try: driver.hide_keyboard()
        except Exception: pass
    except Exception:
        pass
    try:
        # Just tap "Add" immediately; your existing flow already handles error-and-retry,
        # but here we keep it short for speed; if popup appears, we retry once with year.
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
        err = _wait_for_error_text_cr(driver, timeout=1.2)
        if err:
            try:
                _click_error_yes(wait)
            except Exception:
                pass
            # Re-open and try again without editing (good enough for fast path)
            WebDriverWait(driver, 5, 0.25).until(lambda d: len(d.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")
            pickers[2].click(); pickers[2].clear(); pickers[2].send_keys('1991')
            driver.hide_keyboard()
            time.sleep(0.2)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
    except Exception:
        pass
        
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after DOB")
    # KSA mobile? → No
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNo"), "No mobile prompt")

    # Password + Terms
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"), "Hssouna1105@", "Password")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox"), "MuslimTerms")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox"), "Terms")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount submit")

    # Mobile number (with rotation on error)
    current_phone = str(data.get("numero_tlf", "")).strip()
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), current_phone, "Mobile number")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile")

    # Email + rotation loop (like your creation flow)
    email_current = str(data.get("email", "")).strip()
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email")
    while True:
        err = _wait_for_error_text_cr(driver, timeout=1.6)
        if not err:
            break
        # dismiss
        try:
            btn = wait.until(EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
            btn.click()
        except Exception:
            pass
        low = (err or "").lower()
        if "email" in low and ("already" in low or "used" in low or "use" in low):
            new_email = pop_first_variant(EMAIL_JSON_FILE) or ""
            if not new_email:
                return df, "REQUEUED"
            email_current = new_email
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email retry", clear_first=True)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
            continue
        if ("mobile" in low) or ("phone" in low):
            # back, rotate phone, re-enter email
            from CreationReservation import BACK_BTN_ID as _BACK
            safe_click(driver, (AppiumBy.ID, _BACK), "Back from mobile error")
            new_number = pop_first_variant(NUMBER_JSON_FILE) or ""
            if not new_number:
                return df, "REQUEUED"
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), new_number, "Mobile retry", clear_first=True)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email after mobile retry", clear_first=True)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
            continue
        # visa/already has account → mark -1 and drop from ALL
        if any(k in low for k in ("compte","your account", "existing account", "already have an account", "already exists", "visa")):
            df.at[row_index, "CREATION"] = "-1"
            return df, "DROPPED"
        # Unknown → bail (requeue)
        return df, "REQUEUED"

    # OTP for creation (retry once on OTP error)
    time.sleep(0.6)
    _pregrant_loc(driver, APP_PACKAGE)
    code = get_verification_code(email_current)
    if not code:
        return df, "REQUEUED"

    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"), code, "nafath_otp_edit_text")
    otp_err = _wait_for_error_text_cr(driver, timeout=1.8)
    if otp_err:
        try:
            btn = wait.until(EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvYes"))); btn.click()
        except Exception:
            pass
        code2 = get_verification_code(email_current)
        if not code2:
            return df, "REQUEUED"
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"), "", "otp_clear", clear_first=True)
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"), code2, "nafath_otp_edit_text_2")
        otp_err2 = _wait_for_error_text_cr(driver, timeout=3.0)
        if otp_err2:
            return df, "REQUEUED"
    df.at[row_index, "CREATION"] = "1"
    # Creation succeeded
    # Post-creation privacy sheet sometimes appears
    accept_privacy_if_present(driver, timeout=2)

    # 2) Determine gender (no reservation)
    gender = _determine_gender_via_permit(driver)
    if gender not in {"H", "F"}:
        # leave row for later
        return df, "REQUEUED"

    # Update DF snapshot for ALL
    if "gender" not in df.columns:
        df["gender"] = ""
    if "CREATION" not in df.columns:
        df["CREATION"] = ""
    df.at[row_index, "gender"] = gender
    df.at[row_index, "CREATION"] = "1"  # account was created

    # Route decision (actual append happens in worker for atomicity with deletion)
    return df, f"ROUTED_{gender}"
