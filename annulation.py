from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from login import (
    APP_PACKAGE,
    _pregrant_notification_permissions,
    _wait_for_post_otp_state,
    get_nationality_from_row,
    pregrant_location_permissions,
    safe_click,
    safe_send_keys,
    update_fast_settings,
)
from logutil import get_shared_logger
from mail import get_verification_code

logger = get_shared_logger("cancellation")

PASSWORD = os.getenv("CANCELLATION_PASSWORD", os.getenv("CONFIRMATION_PASSWORD", "Hssouna1105@"))
OTP_MAX_POLLS = int(os.getenv("CANCELLATION_OTP_POLLS", "5"))
OTP_POLL_DELAY = float(os.getenv("CANCELLATION_OTP_DELAY", "2.0"))


def _load_df(csv_path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in [
        "RESERVATION",
        "CONFIRMATION",
        "cancellation_note",
        "cancellation_ts",
    ]:
        if col not in df.columns:
            df[col] = ""
    return df


def _poll_otp(email: str | None) -> str | None:
    addr = (email or "").strip()
    if not addr:
        return None
    for _ in range(max(1, OTP_MAX_POLLS)):
        code = get_verification_code(addr)
        if code:
            return code
        time.sleep(OTP_POLL_DELAY)
    return None


def _handle_login_errors(driver, attempts: int = 5) -> None:
    for _ in range(attempts):
        errors = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
        if not errors:
            return
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), "LoginErrorOk", timeout=4)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "RetrySignIn", timeout=6)
        time.sleep(0.3)
    raise RuntimeError("too many login errors")


def run_cancellation_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    csv_path: str,
) -> pd.DataFrame:
    _ = row_series
    df = _ensure_columns(_load_df(csv_path))
    if df.empty or not (0 <= row_index < len(df)):
        _save_df(df, csv_path)
        return df

    row_dict: dict[str, Any] = df.iloc[row_index].to_dict()
    display_name = f"{row_dict.get('nom', '')} {row_dict.get('prenom', '')}".strip()

    def _abort(reason: str) -> pd.DataFrame:
        logger.warning("[cancellation] %s: %s", display_name, reason)
        df.at[row_index, "cancellation_note"] = reason
        _save_df(df, csv_path)
        return df

    def _mark_success(note: str) -> pd.DataFrame:
        logger.info("[cancellation] success for %s: %s", display_name, note)
        df.at[row_index, "RESERVATION"] = "0"
        df.at[row_index, "CONFIRMATION"] = "0"
        df.at[row_index, "date_reservation"] = ""
        df.at[row_index, "heure"] = ""
        df.at[row_index, "cancellation_note"] = note
        df.at[row_index, "cancellation_ts"] = datetime.utcnow().isoformat(timespec="seconds")
        _save_df(df, csv_path)
        return df

    if str(row_dict.get("RESERVATION", "")).strip() != "1":
        return _abort("reservation flag != 1")

    try:
        driver.implicitly_wait(1)
    except Exception:
        pass
    update_fast_settings(driver)

    driver.activate_app(APP_PACKAGE)
    pregrant_location_permissions(driver, APP_PACKAGE)
    _pregrant_notification_permissions(driver, APP_PACKAGE)

    wait = WebDriverWait(driver, 12, poll_frequency=0.25)

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "LandingSignIn", timeout=8):
        return _abort("sign-in button unavailable")
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType", timeout=6):
        return _abort("visitor selector missing")
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), "Nationality", timeout=6):
        return _abort("nationality picker missing")

    nationality_value, nationality_key = get_nationality_from_row(row_dict)
    search_term = (nationality_value or row_dict.get("country") or "").strip()
    if not search_term:
        return _abort("missing nationality")

    safe_send_keys(
        driver,
        (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"),
        nationality_key or search_term.lower(),
        name="NationalitySearch",
        clear_first=True,
    )

    matched = False
    try:
        for el in driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle"):
            label = (el.text or "").strip().lower()
            if label == (nationality_key or search_term.lower()):
                el.click()
                matched = True
                break
    except Exception:
        pass
    if not matched:
        return _abort(f"nationality not found: {search_term}")

    passport = str(row_dict.get("numero_passport", "")).strip()
    if not passport:
        return _abort("missing passport")

    if not safe_send_keys(
        driver,
        (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"),
        passport,
        name="Passport",
        clear_first=True,
    ):
        return _abort("unable to type passport")

    if not safe_send_keys(
        driver,
        (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"),
        PASSWORD,
        name="Password",
        clear_first=True,
    ):
        return _abort("unable to type password")

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "SubmitLogin", timeout=8):
        return _abort("login submit failed")

    _handle_login_errors(driver)

    email = str(row_dict.get("email", "")).strip()
    code = _poll_otp(email)
    if not code:
        return _abort("no OTP received")

    if not safe_send_keys(
        driver,
        (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"),
        code,
        name="OTP",
        clear_first=True,
    ):
        return _abort("unable to type OTP")

    state = _wait_for_post_otp_state(driver, timeout=25)
    if state == "OTP_ERROR":
        time.sleep(1.5)
        retry_code = _poll_otp(email)
        if not retry_code:
            return _abort("otp invalid")
        safe_send_keys(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"),
            "",
            name="OTP",
            clear_first=True,
        )
        safe_send_keys(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"),
            retry_code,
            name="OTP",
            clear_first=False,
        )
        state = _wait_for_post_otp_state(driver, timeout=20)
    if state != "SUCCESS":
        return _abort(f"post-otp state {state}")
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/iv_close"), timeout=3, retries=2):
            raise RuntimeError("bonus tile not available")
        
    screen_size = driver.get_window_size()
    start_x = screen_size['width'] // 2
    start_y = int(screen_size['height'] * 0.6)
    end_y = int(screen_size['height'] * 0.4)
    driver.swipe(start_x, start_y, start_x, end_y, 500)
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNobleRawdahTitle"), "RawdahTile", timeout=12):
        return _abort("rawdah tile missing")
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvStatusBadge"), "PermitStatus", timeout=8):
        return _abort("status badge missing")

    try:
        driver.find_element(
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().resourceId("com.moh.nusukapp:id/btn_contact_us"))'
        )
        time.sleep(0.2)
    except Exception:
        pass

    try:
        buttons = wait.until(
            EC.presence_of_all_elements_located((AppiumBy.ID, "com.moh.nusukapp:id/btn_contact_us"))
        )
        buttons[-1].click()
    except Exception:
        return _abort("contact button unavailable")

    try:
        reasons = wait.until(
            EC.presence_of_all_elements_located((AppiumBy.ID, "com.moh.nusukapp:id/purpose_text"))
        )
        reasons[-1].click()
    except Exception:
        return _abort("cancellation reason list missing")

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/cancelButton"), "CancelButton", timeout=6):
        return _abort("cancel button missing")
    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), "ConfirmCancel", timeout=4, retries=1)

    note = ""
    success = False
    try:
        desc = WebDriverWait(driver, 12, 0.25).until(
            EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/permit_mamag_desc"))
        )
        note = (desc.text or "").strip()
        success = True
    except TimeoutException:
        try:
            badge = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tvStatusBadge")
            if "cancel" in (badge.text or "").lower():
                note = (badge.text or "").strip()
                success = True
        except Exception:
            success = False

    if not success:
        return _abort("could not confirm cancellation")

    return _mark_success(note or "reservation cancelled")


__all__ = ["run_cancellation_on_row"]
