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

from mail import get_verification_code

APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")

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
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after visa")

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
            pickers[2].click(); pickers[2].clear(); pickers[2].send_keys(yyyy)
            pickers[0].click()
            try: driver.hide_keyboard()
            except Exception: pass
        except Exception:
            pass

        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
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

        # Handle quick error popups post email/mobile
        while True:
            err = _wait_for_error_text(driver, timeout=2)
            if not err:
                break
            low = err.lower()
            _click_error_yes(wait)

            # email already used → you can rotate email here (e.g., pop_first_variant)
            if "email" in low and "already" in low:
                # mark row so your outer pipeline can retry with a new email later
                _set(df, row_index, "CREATION", "-1")
                _save_df(df, csv_path)
                return df

            # mobile already registered → same story
            if "mobile" in low or "phone" in low:
                _set(df, row_index, "CREATION", "")
                _save_df(df, csv_path)
                return df

            # account/visa/duplicate → mark and bail
            if any(k in low for k in ("your account", "the user", "visa")):
                _set(df, row_index, "CREATION", "-1")
                _save_df(df, csv_path)
                return df

        # OTP for creation
        time.sleep(1)
        _pregrant_location_permissions(driver, APP_PACKAGE)
        code = get_verification_code(email_current)
        if code:
            otp_field = wait.until(EC.presence_of_element_located(
                (AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text"))
            )
            otp_field.send_keys(code)
            # quick otp error probe
            otp_err = _wait_for_error_text(driver, timeout=4)
            if otp_err:
                _click_error_yes(wait)
                # if this is fatal, mark and return (kept simple)
                _set(df, row_index, "CREATION", "1")
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
        login_make_reservation(driver, row_index, dict_row, df, target_ddmm, dd, dd)
        _save_df(df, csv_path)
        return df

    except Exception as e:
        traceback.print_exc()
        # don’t crash the loop; persist what we have
        _save_df(df, csv_path)
        return df
