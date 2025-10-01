from __future__ import annotations

import os
import re
import time
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

from mail import get_verification_code
from login import (
    APP_PACKAGE,
    _pregrant_notification_permissions,
    normalize_gender,
    pregrant_location_permissions,
    safe_click,
    safe_send_keys,
    update_fast_settings,
)
from logutil import get_shared_logger
from config import PAYS

PASSWORD = os.getenv("CONFIRMATION_PASSWORD", "Hssouna1105@")
OTP_MAX_POLLS = int(os.getenv("CONFIRMATION_OTP_POLLS", "5"))
OTP_POLL_DELAY = float(os.getenv("CONFIRMATION_OTP_POLL_DELAY", "2.0"))

logger = get_shared_logger("confirmation")


def _load_df(csv_path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame()


def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in [
        "CONFIRMATION",
        "RESERVATION",
        "gender",
        "email",
        "heure",
        "date_reservation",
        "nom",
        "numero_passport",
        "confirmation_note",
        "confirmation_path",
        "confirmation_ts",
    ]:
        if col not in df.columns:
            df[col] = ""
    return df


def _flag(row: dict, key: str) -> str:
    return str(row.get(key, "")).strip()


def _within_confirmation_window(row: dict) -> Tuple[bool, str]:
    date_str = _flag(row, "date_reservation")
    time_str = _flag(row, "heure")
    if not date_str or not time_str:
        return False, "missing reservation datetime"

    try:
        day = int(date_str[0:2])
        month = int(date_str[3:5])
    except (ValueError, IndexError):
        return False, "invalid reservation date"

    try:
        if ":" in time_str:
            parsed = datetime.strptime(time_str, "%I:%M %p")
            hour = parsed.hour
        else:
            hour = int(time_str)
    except ValueError:
        return False, "invalid reservation hour"

    now = datetime.now()
    try:
        target_dt = datetime(year=now.year, month=month, day=day, hour=hour, minute=0)
    except ValueError:
        return False, "unusable reservation datetime"

    diff = target_dt - now
    if diff <= timedelta(hours=0):
        return False, "reservation already expired"
    if diff > timedelta(hours=48):
        return False, "reservation not yet confirmable"
    return True, ""


def _should_skip_confirmation(row: dict) -> Tuple[bool, str]:
    if _flag(row, "RESERVATION") != "1":
        return True, "reservation flag is not 1"

    confirmation_flag = _flag(row, "CONFIRMATION")
    if confirmation_flag == "1":
        return True, "already confirmed"
    if confirmation_flag not in {"", "0"}:
        return True, f"confirmation flag {confirmation_flag!r}"

    ok, reason = _within_confirmation_window(row)
    if not ok:
        return True, reason
    return False, ""

def _safe_filename(*parts: str) -> str:
    joined = "_".join(p for p in (str(part).strip() for part in parts if part) if p)

    # Replace ":" with "_" so Windows accepts it
    joined = joined.replace(":", "_")

    # Keep spaces, dots, dashes, underscores
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "_", joined or "confirmation")

    return cleaned[:80]
def _resolve_screenshot_path(base_folder: str, row: dict, visit_time: str | None) -> str:
    gender_code = normalize_gender(row.get('gender'))
    if gender_code == 'H':
        sub = 'hommes'
    elif gender_code == 'F':
        sub = 'femmes'
    else:
        sub = 'unknown'
    target_dir = os.path.join(base_folder, sub)
    os.makedirs(target_dir, exist_ok=True)

    
    time_component = (visit_time or '').strip() or (_flag(row, 'heure') or '').strip()
    if time_component:
        time_component = time_component.upper()
    if not time_component:
        time_component = (_flag(row, 'heure') or '').strip()
    passport = (row.get('numero_passport') or '').strip() or 'unknown'
    filename = _safe_filename(time_component or 'unknown', passport) + '.png'
    return os.path.join(target_dir, filename)

def _capture_screenshot(driver, base_folder: str, row: dict, visit_time: str | None) -> str:
    # 0) Wait until the "date title" (top crop bound) is visible.
    try:
        WebDriverWait(driver, 8, 0.2).until(
            EC.visibility_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tv_visit_date_title"))
        )
    except Exception:
        # If it never becomes visible, we’ll proceed and let the later logic fall back to a full screenshot.
        pass

    # 1) If both top & bottom elements are present, DO NOT scroll.
    need_scroll = True
    try:
        _top_probe = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tv_visit_date_title")
        _bot_probe = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tv_identity_number")
        if _top_probe.is_displayed() and _bot_probe.is_displayed():
            need_scroll = False
    except Exception:
        need_scroll = True

    # 2) Only scroll if needed.
    if need_scroll:
        try:
            size = driver.get_window_size()
            start_x = size.get("width", 0) // 2
            start_y = int(size.get("height", 0) * 0.6)
            end_y = int(size.get("height", 0) * 0.55)
            if start_x and start_y and end_y:
                try:
                    driver.swipe(start_x, start_y, start_x, end_y, 500)
                except Exception:
                    driver.execute_script(
                        "mobile: swipe",
                        {
                            "startX": start_x,
                            "startY": start_y,
                            "endX": start_x,
                            "endY": end_y,
                            "speed": 500,
                        },
                    )
        except Exception:
            pass

    path = _resolve_screenshot_path(base_folder, row, visit_time)

    try:
        screenshot_bytes = driver.get_screenshot_as_png()
    except Exception as exc:
        logger.warning("[confirmation] raw screenshot capture failed; fallback to file: %s", exc)
        driver.get_screenshot_as_file(path)
        return path

    if not screenshot_bytes:
        driver.get_screenshot_as_file(path)
        return path

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        logger.warning("[confirmation] pillow not available; saved full screenshot")
        with open(path, "wb") as handle:
            handle.write(screenshot_bytes)
        return path

    try:
        base_image = Image.open(BytesIO(screenshot_bytes))
    except Exception as exc:
        logger.warning("[confirmation] unable to load screenshot for cropping: %s", exc)
        with open(path, "wb") as handle:
            handle.write(screenshot_bytes)
        return path

    # Crop screenshot to the reservation details block bounded by the divider and identity field.
    try:
        top_el = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tv_visit_date_title")
        bottom_el = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tv_identity_number")
    except Exception as exc:
        logger.warning("[confirmation] cropping bounds missing; saved full screenshot: %s", exc)
        base_image.save(path)
        return path

    top_rect = top_el.rect or {}
    bottom_rect = bottom_el.rect or {}

    top_y = max(int(top_rect.get("y", 0)), 0)
    bottom_y = int(bottom_rect.get("y", 0) + bottom_rect.get("height", 0))

    if bottom_y <= top_y:
        logger.warning(
            "[confirmation] invalid crop bounds (top=%s bottom=%s); saved full screenshot",
            top_y,
            bottom_y,
        )
        base_image.save(path)
        return path

    crop_box = (
        0,
        max(top_y, 0),
        base_image.width,
        min(bottom_y, base_image.height),
    )

    if crop_box[3] <= crop_box[1]:
        base_image.save(path)
        return path

    cropped_image = base_image.crop(crop_box)
    cropped_image.save(path)
    return path



def _choose_nationality(driver, wait: WebDriverWait, nationality: str) -> None:
    search_value = (nationality or "").strip().lower()
    fallback_value = (PAYS or "").strip().lower()

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), "NationalityPicker", timeout=6):
        raise RuntimeError("unable to open nationality picker")

    target_value = search_value or fallback_value
    if not target_value:
        raise RuntimeError("missing nationality value")

    if not safe_send_keys(
        driver,
        (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"),
        target_value,
        name="NationalitySearch",
        clear_first=True,
        timeout=6,
    ):
        raise RuntimeError("unable to search nationality")

    desired_values = {target_value}
    if fallback_value:
        desired_values.add(fallback_value)

    for _ in range(3):
        try:
            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle")
        except Exception as exc:
            logger.debug("[confirmation] nationality lookup failed: %s", exc)
            elements = []
        for element in elements:
            try:
                label = (element.text or "").strip().lower()
            except Exception:
                continue
            if label in desired_values:
                try:
                    element.click()
                    logger.info("[confirmation] nationality selected: %s", label)
                    return
                except StaleElementReferenceException:
                    logger.debug("[confirmation] nationality option became stale; retrying")
                    break
                except Exception as exc:
                    logger.warning("[confirmation] failed to click nationality %s: %s", label, exc)
                    break
        time.sleep(0.3)

    raise RuntimeError(f"nationality {target_value!r} not found in picker")


def _handle_login_errors(driver, max_attempts: int = 5) -> None:
    for attempt in range(max_attempts):
        try:
            errors = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
        except Exception as exc:
            logger.debug("[confirmation] login error probe failed: %s", exc)
            return
        if not errors:
            return

        message = (errors[0].text or "").strip()
        logger.warning(
            "[confirmation] login error detected (%s/%s): %s",
            attempt + 1,
            max_attempts,
            message,
        )
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), "LoginErrorOk", timeout=4)
        time.sleep(0.25)
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "RetrySubmitLogin", timeout=6):
            raise RuntimeError("unable to retry login after error")
        time.sleep(0.8)

    raise RuntimeError("login blocked by repeated errors")


def _poll_verification_code(email: str) -> Optional[str]:
    address = (email or "").strip()
    if not address:
        logger.warning("[confirmation] missing email address for OTP retrieval")
        return None

    for attempt in range(1, OTP_MAX_POLLS + 1):
        try:
            code = get_verification_code(address)
        except Exception as exc:
            logger.error("[confirmation] OTP fetch failed on attempt %s: %s", attempt, exc)
            code = None
        if code:
            code_str = str(code).strip()
            logger.info("[confirmation] OTP retrieved on attempt %s", attempt)
            return code_str
        time.sleep(OTP_POLL_DELAY)

    logger.error("[confirmation] OTP not received for %s after %s attempts", address, OTP_MAX_POLLS)
    return None


def _peek_error_text(driver) -> str:
    try:
        errors = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
    except Exception as exc:
        logger.debug("[confirmation] error label lookup failed: %s", exc)
        return ""
    if not errors:
        return ""
    return (errors[0].text or "").strip()


def _handle_post_login_popups(driver, wait: WebDriverWait) -> None:
    def tap_if_present(locator: Tuple[str, str], name: str, timeout: int = 5) -> bool:
        poll = getattr(wait, 'poll_frequency', 0.25)
        try:
            WebDriverWait(driver, timeout, poll_frequency=poll).until(
                EC.presence_of_element_located(locator)
            )
        except TimeoutException:
            return False
        except Exception as exc:
            logger.debug("[confirmation] probe for %s failed: %s", name, exc)
            return False

        safe_click(driver, locator, name, timeout=timeout)
        time.sleep(0.2)
        return True

    tap_if_present((AppiumBy.ID, "com.moh.nusukapp:id/check_message"), "OtpCheckMessage", timeout=6)
    tap_if_present((AppiumBy.ID, "com.moh.nusukapp:id/btn_confirm"), "OtpCheckConfirm", timeout=6)
    tap_if_present((AppiumBy.ID, "com.moh.nusukapp:id/btn_confirm_button"), "OtpCheckConfirmAlt", timeout=6)

    permission_ids = [
        "com.android.permissioncontroller:id/permission_allow_button",
        "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
        "com.android.packageinstaller:id/permission_allow_button",
    ]
    for perm_id in permission_ids:
        tap_if_present((AppiumBy.ID, perm_id), f"PermissionAllow[{perm_id}]", timeout=4)



def _perform_confirmation_actions(driver) -> None:
    confirm_locator = (AppiumBy.ID, "com.moh.nusukapp:id/btnConfirm")
    try:
        has_confirm = bool(driver.find_elements(*confirm_locator))
    except Exception as exc:
        logger.debug("[confirmation] confirm button probe failed: %s", exc)
        has_confirm = False

    if has_confirm:
        if not safe_click(driver, confirm_locator, "ConfirmReservation", timeout=10):
            raise RuntimeError("unable to tap confirm reservation button")
        safe_click(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue"),
            "ConfirmApproveContinue",
            timeout=6,
        )
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), "ConfirmDialogYes", timeout=4)
    else:
        logger.info("[confirmation] confirmation button not visible; assuming already confirmed")



def _open_reservation_details(driver) -> None:
    candidates = [
        ((AppiumBy.ID, "com.moh.nusukapp:id/btnAction"), "ReservationAction"),
        ((AppiumBy.ID, "com.moh.nusukapp:id/btnViewDetail"), "ReservationViewDetail"),
        ((AppiumBy.ID, "com.moh.nusukapp:id/btnViewDetails"), "ReservationViewDetails"),
    ]
    for locator, name in candidates:
        try:
            if not driver.find_elements(*locator):
                continue
        except Exception as exc:
            logger.debug("[confirmation] reservation detail probe %s failed: %s", name, exc)
            continue
        if safe_click(driver, locator, name, timeout=8):
            return
    raise RuntimeError("reservation details button not available")


def run_confirmation_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    csv_path: str,
    base_output_folder: str,
) -> pd.DataFrame:
    _ = row_series
    df = _ensure_columns(_load_df(csv_path))
    if df.empty or not (0 <= row_index < len(df)):
        _save_df(df, csv_path)
        return df

    wait = WebDriverWait(driver, 12, poll_frequency=0.25)
    try:
        driver.implicitly_wait(1)
    except Exception:
        pass
    update_fast_settings(driver)

    row_dict = df.iloc[row_index].to_dict()
    skip, reason = _should_skip_confirmation(row_dict)
    if skip:
        logger.info(
            "[confirmation] skip %s %s: %s",
            row_dict.get("nom"),
            row_dict.get("numero_passport"),
            reason,
        )
        df.at[row_index, "confirmation_note"] = reason
        _save_df(df, csv_path)
        return df

    nationality_raw = (_flag(row_dict, "nationalite") or PAYS or "").strip()
    nationality = nationality_raw.lower() if nationality_raw else ""

    try:
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "LandingSignIn", timeout=8):
            raise RuntimeError("sign-in button not available")
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType", timeout=6)
        _choose_nationality(driver, wait, nationality)

        passport = _flag(row_dict, "numero_passport")
        if not passport:
            raise RuntimeError("missing passport number")
        if not safe_send_keys(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"),
            passport,
            name="Passport",
            clear_first=True,
        ):
            raise RuntimeError("unable to type passport")

        if not safe_send_keys(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"),
            PASSWORD,
            name="Password",
            clear_first=True,
        ):
            raise RuntimeError("unable to type password")

        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), "SubmitLogin", timeout=8):
            raise RuntimeError("unable to submit login")

        _handle_login_errors(driver)

        pregrant_location_permissions(driver, APP_PACKAGE)
        _pregrant_notification_permissions(driver, APP_PACKAGE)

        email = _flag(row_dict, "email")
        time.sleep(10)
        code = _poll_verification_code(email)
        
        if not code:
            raise RuntimeError("no OTP received")
        if not safe_send_keys(
            driver,
            (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"),
            code,
            name="OTP",
            clear_first=True,
            timeout=10,
        ):
            raise RuntimeError("unable to type OTP")

        otp_err = _peek_error_text(driver)
        if otp_err and "otp" in otp_err.lower():
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), "OtpErrorOk", timeout=4)
            raise RuntimeError(f"otp rejected: {otp_err}")

        time.sleep(1)  # laisser l'UI dessiner la popup
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/iv_close"), timeout=3, retries=1)
        
        if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"), "RawdahTile", timeout=12):
            raise RuntimeError("rawdah tile not available")

        visit_time_text = ""
        try:
            visit_time_el = wait.until(
                EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/tvVisitTime"))
            )
            visit_time_text = (visit_time_el.text or "").strip()
        except TimeoutException:
            visit_time_text = ""

        _perform_confirmation_actions(driver)
        _open_reservation_details(driver)
        screenshot_path = _capture_screenshot(driver, base_output_folder, row_dict, visit_time_text)

        df.at[row_index, "CONFIRMATION"] = "1"
        df.at[row_index, "confirmation_note"] = "confirmed"
        df.at[row_index, "confirmation_path"] = screenshot_path
        df.at[row_index, "confirmation_ts"] = datetime.utcnow().isoformat()
        logger.info(
            "[confirmation] success %s %s -> %s",
            row_dict.get("nom"),
            row_dict.get("numero_passport"),
            screenshot_path,
        )
    except Exception as exc:
        message = str(exc)
        df.at[row_index, "confirmation_note"] = message
        logger.exception("[confirmation] failure for %s %s: %s", row_dict.get("nom"), row_dict.get("numero_passport"), message)
        _save_df(df, csv_path)
        raise
    else:
        _save_df(df, csv_path)
        return df


def confirm_single_row(csv_path: str, base_output_folder: str, driver_factory=None) -> None:
    """Legacy helper: confirm the first eligible row using a temporary driver."""
    from config import setup_driver  # local import to avoid cycles

    driver = None
    try:
        driver = driver_factory() if driver_factory else setup_driver()
        df = _ensure_columns(_load_df(csv_path))
        if df.empty:
            logger.info("[confirmation] no rows available in %s", csv_path)
            return
        run_confirmation_on_row(driver, 0, df.iloc[0], csv_path, base_output_folder)
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass






