# CreationReservation.py
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
)

# Reuse helpers you built in step 2
from login import (
    make_reservation as login_make_reservation,
    accept_privacy_if_present,
    safe_click,
    safe_send_keys,
    update_fast_settings,
)

from login_v4 import _perform_login_step, _perform_reservation_step
from mail import get_verification_code
from pdf import pop_first_variant
from config import EMAIL_JSON_FILE as _EMAIL_JSON_FILE, NUMBER_JSON_FILE as _NUMBER_JSON_FILE

APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")
EMAIL_JSON_FILE = os.getenv("EMAIL_JSON_FILE_OVERRIDE", _EMAIL_JSON_FILE)
NUMBER_JSON_FILE = os.getenv("NUMBER_JSON_FILE_OVERRIDE", _NUMBER_JSON_FILE)
BACK_BTN_ID = "com.moh.nusukapp:id/imgBack"

# -----------------------------------------------------------------------------
# Small local helpers (runtime-scoped; NO module-level df/csv)

def _load_df(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return df.reset_index(drop=True)

def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")

def _ensure_common_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col, default in [
        ("CREATION", ""),
        ("RESERVATION", ""),
        ("gender", ""),
        ("reserved_men", "0"),
        ("reserved_women", "0"),
        ("email", ""),
        ("numero_tlf", ""),
        ("numero_passport", ""),
        ("numero_visa", ""),
        ("nationalite", ""),
        ("date_reservation", ""),
        ("heure", ""),
    ]:
        if col not in df.columns:
            df[col] = default
    return df

def _set(df: pd.DataFrame, row_index: int, col: str, value: str) -> None:
    if col not in df.columns:
        df[col] = ""
    df.at[row_index, col] = "" if value is None else str(value)

def _normalize_gender(raw) -> str:
    s = ("" if raw is None else str(raw)).strip().lower()
    if s in {"f", "female", "femme", "woman", "w", "femelle"}:
        return "F"
    if s in {"h", "homme", "m", "male", "man", "mâle"}:
        return "H"
    return ""

def _get_nationality(row_dict: Dict[str, str]) -> Tuple[str | None, str | None]:
    val = row_dict.get("nationalite")
    s = None if val is None else str(val).strip()
    if not s:
        return None, None
    return s, s.lower()

def _wait_for_error_text(driver, timeout=1.5, poll=0.2):
    end = time.time() + timeout
    while time.time() < end:
        try:
            els = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
            if els:
                txt = (els[0].text or "").strip()
                if txt:
                    return txt
        except StaleElementReferenceException:
            pass
        time.sleep(poll)
    return None

def _click_error_yes(wait: WebDriverWait):
    btn = wait.until(EC.element_to_be_clickable((AppiumBy.ID, "com.moh.nusukapp:id/tvYes")))
    btn.click()

def _pregrant_location_permissions(driver, package: str = APP_PACKAGE):
    cmds = [
        ("pm", ["grant", package, "android.permission.ACCESS_FINE_LOCATION"]),
        ("pm", ["grant", package, "android.permission.ACCESS_COARSE_LOCATION"]),
    ]
    for cmd, args in cmds:
        try:
            driver.execute_script(
                "mobile: shell",
                {"command": cmd, "args": args, "includeStderr": True, "timeout": 5000},
            )
        except Exception:
            pass

def _pregrant_notification_permissions(driver, package: str = APP_PACKAGE):
    """Best‑effort: pre‑grant app notification permission (Android 13+).

    Tries both runtime permission via `pm grant` and app‑ops toggle, and ignores
    failures on older Android versions where the permission doesn't exist.
    """
    cmds = [
        ("pm", ["grant", package, "android.permission.POST_NOTIFICATIONS"]),
        ("appops", ["set", package, "POST_NOTIFICATION", "allow"]),
        ("appops", ["set", package, "POST_NOTIFICATIONS", "allow"]),
    ]
    for cmd, args in cmds:
        try:
            driver.execute_script(
                "mobile: shell",
                {"command": cmd, "args": args, "includeStderr": True, "timeout": 5000},
            )
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Public entry point (mirrors run_login_on_row)

def run_creation_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    csv_path: str,
    target_ddmm: str,  # "DD/MM"
) -> pd.DataFrame:
    """
    Single-row account creation (+ reservation) in-process.

    - driver: persistent Appium driver (already started, NOT closed here)
    - row_index: index to update inside csv_path
    - row_series: pd.Series of the row as seen by the caller
    - csv_path: CSV to read/modify/write
    - target_ddmm: chosen date "DD/MM" for reservation (NO config.TARGET_DATE usage)
    """
    df = _ensure_common_columns(_load_df(csv_path))
    data = row_series.to_dict()  # input values (mutable copy is fine)
    wait = WebDriverWait(driver, 10, poll_frequency=0.25)

    # quick driver tuning (no heavy resets here)
    try:
        driver.implicitly_wait(1)
    except Exception:
        pass
    update_fast_settings(driver)
    _pregrant_location_permissions(driver, APP_PACKAGE)
    _pregrant_notification_permissions(driver, APP_PACKAGE)

    # If row already has a final status, noop
    if str(data.get("CREATION", "")).strip() in {"1", "-1"}:
        _save_df(df, csv_path)
        return df

    # -----------------------------------------------------------------------------
    # 1) Start "Create Account" flow
    try:
        # Landing → Create Account → Visitor
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount"):
            _save_df(df, csv_path); return df
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType"):
            _save_df(df, csv_path); return df

        # Nationality
        try:
            wait.until(EC.invisibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/pbNationality")))
        except Exception:
            pass

        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), "Nationality"):
            _save_df(df, csv_path); return df

        pays, pays_lower = _get_nationality(data)
        if pays_lower:
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"), pays, "Search nationality")
            found = False
            for el in driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle"):
                if (el.text or "").strip().lower() == pays_lower:
                    try:
                        el.click()
                    except Exception:
                        pass
                    found = True
                    break
            if not found:
                # can't proceed
                _save_df(df, csv_path); return df

        # Passport
        numero_passport = str(data.get("numero_passport", "")).strip()
        if not numero_passport or numero_passport.lower() == "non trouvé":
            _save_df(df, csv_path); return df
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), numero_passport, "Passport number")
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after passport")

        # Visa
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo"), str(data.get("numero_visa", "")), "Visa number")
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/btn_continue"), "Continue after visa")

        # DOB
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvDOB"), "DOB field"):
            _save_df(df, csv_path); return df
        try:
            wait.until(lambda d: len(d.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")
        except TimeoutException:
            _save_df(df, csv_path); return df

        # Expect "DD/MM/YYYY" in CSV
        dob = str(data.get("date_de_naissance", "01/01/1990"))
        dd, mm, yyyy = dob[:2], dob[3:5], dob[6:]
        try:
            pickers[2].click(); pickers[2].clear(); pickers[2].send_keys("1981")
            driver.press_keycode(66)
            driver.press_keycode(66)
        except Exception:
            pass
        #safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
        
        
        # Rare popup: "Veuillez sélectionner une date valide." -> dismiss and retry once
        try:
            dob_err = _wait_for_error_text(driver, timeout=1.5)
            if dob_err and ("date" in dob_err.lower() or "valide" in dob_err.lower() or "valid" in dob_err.lower()):
                try:
                    _click_error_yes(wait)
                except Exception:
                    pass
                # Re-open DOB and re-enter quickly
                WebDriverWait(driver, 5, 0.25).until(lambda d: len(d.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
                pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")
                pickers[2].click(); pickers[2].clear(); pickers[2].send_keys("1991")
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

        # Mobile number
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), str(data.get("numero_tlf", "")), "Mobile number")
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile")

        # Email
        email_current = str(data.get("email", "")).strip()
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email")
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email")

        # Handle error popups after Email → Continue (rotate email/phone if needed)
        while True:
            err = _wait_for_error_text(driver, timeout=2)
            if not err:
                break  # no popup → proceed

            _click_error_yes(wait)
            low = err.lower()

            # Email already used: rotate email and retry
            if ("adresse" in low) or ("email" in low and ("already" in low or "used" in low or "use" in low)):
                new_email = pop_first_variant(EMAIL_JSON_FILE) or ""
                if new_email:
                    email_current = new_email
                    _set(df, row_index, "email", email_current)
                    safe_send_keys(
                        driver,
                        (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"),
                        email_current,
                        "Email retry",
                        clear_first=True,
                    )
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
                    _save_df(df, csv_path)
                    continue
                else:
                    # No variants available; let the outer flow handle later
                    _save_df(df, csv_path)
                    break

            # Mobile/phone issues: go back, rotate number, re-enter both
            if ("mobile" in low) or ("phone" in low):
                safe_click(driver, (AppiumBy.ID, BACK_BTN_ID), "Back from mobile error")
                new_number = pop_first_variant(NUMBER_JSON_FILE) or ""
                if new_number:
                    _set(df, row_index, "numero_tlf", new_number)
                    safe_send_keys(
                        driver,
                        (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"),
                        new_number,
                        "Mobile retry",
                        clear_first=True,
                    )
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
                    # Re-enter (possibly updated) email and continue again
                    safe_send_keys(
                        driver,
                        (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"),
                        email_current,
                        "Email after mobile retry",
                        clear_first=True,
                    )
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
                    _save_df(df, csv_path)
                    continue
                else:
                    _save_df(df, csv_path)
                    break

            # Account already exists / visa issues: mark and bail
            if any(k in low for k in (
                "compte",
                "your account",
                "the user",
                "visa",
                "already exists",
                "already exist",
                "account already",
                "existing account",
                "already have an account",
            )):
                _set(df, row_index, "CREATION", "-1")
                _save_df(df, csv_path)
                return df

            # Unknown/other error: persist and break
            _save_df(df, csv_path)
            break

        # OTP for creation (with retry on error, similar to login.py)
        time.sleep(1)
        _pregrant_location_permissions(driver, APP_PACKAGE)
        code = get_verification_code(email_current)
        if code:
            # First attempt
            safe_send_keys(
                driver,
                (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"),
                code,
                "nafath_otp_edit_text",
            )
            # Probe for OTP error and retry once if needed
            otp_err = _wait_for_error_text(driver, timeout=2)
            if otp_err:
                low = (otp_err or "").lower()
                if any(k in low for k in (
                    "compte",
                    "your account",
                    "the user",
                    "visa",
                    "already exists",
                    "already exist",
                    "account already",
                    "existing account",
                    "already have an account",
                )):
                    _set(df, row_index, "CREATION", "-1")
                    _save_df(df, csv_path)
                    return df

                if any(k in low for k in ("invalid", "incorrect", "wrong", "expired", "otp", "code")):
                    try:
                        _click_error_yes(wait)
                    except Exception:
                        pass
                    # Retry once with a fresh code
                    time.sleep(0.2)
                    code2 = get_verification_code(email_current)
                    if code2:
                        safe_send_keys(
                            driver,
                            (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"),
                            "",
                            "nafath_otp_edit_text",
                            clear_first=True,
                        )
                        safe_send_keys(
                            driver,
                            (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"),
                            code2,
                            "nafath_otp_edit_text",
                        )
                        # Check again; if still error, bail (keep existing behavior minimal)
                        otp_err2 = _wait_for_error_text(driver, timeout=4)
                        if otp_err2:
                            try:
                                _click_error_yes(wait)
                            except Exception:
                                pass
                            _set(df, row_index, "CREATION", "0")
                            _save_df(df, csv_path)
                            return df
                    else:
                        # No second code available; bail like before
                        _set(df, row_index, "CREATION", "0")
                        _save_df(df, csv_path)
                        return df
        else:
            # No code available; bail like before
            _set(df, row_index, "CREATION", "0")
            _save_df(df, csv_path)
            return df

        # Creation succeeded (we’ll still confirm downstream by reservation step)
        _set(df, row_index, "CREATION", "1")

        # Post-creation privacy sheet sometimes appears
        accept_privacy_if_present(driver, timeout=2)

        # -----------------------------------------------------------------------------
        # 2) Reservation immediately (same driver session)
        # Derive day tokens from target_ddmm (used by your calendar helpers inside login.make_reservation)
        dd = target_ddmm.split("/")[0]
        # Make a mutable row dict for reservation helper
        dict_row = df.iloc[row_index].to_dict()

        # Reservation (login_make_reservation writes back via _set in login.py; here we pass df)
        # We call the same helper you used in step 2 but adjusted to receive df/target info there.
        _perform_reservation_step(driver,dict_row,df,row_index,target_ddmm)
        _save_df(df, csv_path)
        return df

    except Exception as e:
        traceback.print_exc()
        # don’t crash the loop; persist what we have
        _save_df(df, csv_path)
        return df
