# login_and_reservation.py
"""
Login and reservation automation with detailed logging.

Highlights:
- Stale-proof interactions via safe_click / safe_send_keys (refind & retry).
- Fast existing-booking detection (textContains probe).
- Robust OTP handling: detect invalid/expired; auto-dismiss; retry once.
- Native calendar click (no OCR): find smallest parent cell for (greg,hijri),
  with reliable fallback to the midpoint between the two child labels.
- Pre-book safety check: verify the visible date label matches the target.
- Explicit waits everywhere; implicit wait kept tiny (1s) to avoid compounding.
"""

from __future__ import annotations

import math
import os
import re
import time
import logging
from datetime import datetime
from typing import Optional, Union

import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    WebDriverException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from mail import get_verification_code
from config import START_DATE, hard_reset_app  # e.g. "DD_MM_YYYY"
from logutil import get_shared_logger

# -----------------------------------------------------------------------------
logger = get_shared_logger("reservation")

# -----------------------------------------------------------------------------
# Config / Data helpers (runtime-scoped; NO module-level CSV/DATE)

def _load_df(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return df.reset_index(drop=True)

def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")

def _ensure_counter_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "gender" not in df.columns:
        df["gender"] = ""
    if "reserved_men" not in df.columns:
        df["reserved_men"] = "0"
    if "reserved_women" not in df.columns:
        df["reserved_women"] = "0"
    return df

def _set_df(df: pd.DataFrame, index: int, col: str, value: str) -> None:
    if col not in df.columns:
        df[col] = ""
    prev = df.at[index, col] if 0 <= index < len(df) else None
    df.at[index, col] = value
    logger.info("DF Update [row=%s, col=%s]: %r -> %r", index, col, prev, value)

def _increment_reserved(df: pd.DataFrame, gender_code: str) -> None:
    col = "reserved_men" if gender_code == "H" else "reserved_women"
    if col not in df.columns:
        df[col] = "0"
    try:
        current = int(df[col].iloc[0])
    except Exception:
        current = 0
    df[col] = str(current + 1)

def get_nationality_from_row(row_dict: dict):
    """
    Return (search_text, match_key_lower) for nationality.
    """
    val = row_dict.get("nationalite")
    try:
        is_missing = val is None or (pd.isna(val)) or (str(val).strip() == "")
    except Exception:
        is_missing = True
    if is_missing:
        return None, None
    s = str(val).strip()
    return s, s.lower()

APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")

# -----------------------------------------------------------------------------
# Helpers

def row_requires_app(row: pd.Series) -> bool:
    c = (row.get("CREATION") or "").strip()
    r = (row.get("RESERVATION") or "").strip()
    return c not in {"0", "-1"} and r != "1"

def update_fast_settings(driver):
    try:
        driver.update_settings({
            "waitForIdleTimeout": 0,
            "ignoreUnimportantViews": True,
        })
        logger.info("Driver settings updated: waitForIdleTimeout=0, ignoreUnimportantViews=True")
    except Exception as e:
        logger.info("Could not update driver settings: %s", e)

def normalize_gender(raw) -> str:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return "Unknown"
    try:
        s = str(raw).strip().lower()
    except Exception:
        return "Unknown"

    if s in {"", "nan", "none"}:
        return "Unknown"
    if s in {"f", "female", "femme", "woman", "w", "femelle"}:
        return "F"
    if s in {"h", "homme", "m", "male", "man", "mâle"}:
        return "H"
    return "Unknown"

def has_existing_booking(driver) -> bool:
    needles = [
        "La confirmation de", "existing booking", "have an active permit",
        "You already have an existing booking for", "Vous avez déjà une réservation",
        "existing"
    ]
    for t in needles:
        try:
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{t}")')
            return True
        except Exception:
            pass
    return False

def safe_click(driver, locator, name="element", timeout=10, retries=2, poll=0.25, clickable=True):
    by, value = locator
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            wait = WebDriverWait(driver, timeout, poll)
            el = wait.until(EC.element_to_be_clickable((by, value))) if clickable \
                 else wait.until(EC.presence_of_element_located((by, value)))
            time.sleep(0.05)
            el.click()
            logger.debug("[safe_click] %s clicked (attempt %s)", name, attempt)
            return True
        except (StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException) as e:
            last_err = e
            logger.warning("[safe_click] retry %s for %s due to %s", attempt, name, type(e).__name__)
            time.sleep(0.15)
        except TimeoutException as e:
            last_err = e
            logger.warning("[safe_click] timeout waiting for %s (attempt %s)", name, attempt)
        except WebDriverException as e:
            last_err = e
            logger.warning("[safe_click] driver error for %s: %s", name, e)
            break
    logger.error("[safe_click] failed to click %s after %s attempts: %s", name, retries, last_err)
    return False

def safe_send_keys(driver, locator, text, name="field", timeout=3, retries=1, poll=0.25, clear_first=False):
    by, value = locator
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            el = WebDriverWait(driver, timeout, poll).until(EC.visibility_of_element_located((by, value)))
            if clear_first:
                el.clear()
                time.sleep(0.03)
            el.send_keys(text)
            logger.debug("[safe_send_keys] %s typed on attempt %s", name, attempt)
            return True
        except (StaleElementReferenceException, ElementNotInteractableException) as e:
            last_err = e
            logger.warning("[safe_send_keys] retry %s for %s due to %s", attempt, name, type(e).__name__)
            time.sleep(0.15)
        except TimeoutException as e:
            last_err = e
            logger.warning("[safe_send_keys] timeout waiting for %s (attempt %s)", name, attempt)
        except WebDriverException as e:
            last_err = e
            logger.warning("[safe_send_keys] driver error for %s: %s", name, e)
            break
    logger.error("[safe_send_keys] failed to type into %s: %s", name, last_err)
    return False

# --- permissions --------------------------------------------------------------
def _pregrant_notification_permissions(driver, package: str = APP_PACKAGE):
    """Best‑effort: pre‑grant app notification permission (Android 13+).

    Attempts both pm grant and appops fallback. Silently ignores errors on
    platforms where the permission/op is not recognized.
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

# --- calendar helpers ---------------------------------------------------------

def _parse_bounds(bstr: str):
    try:
        pts = re.findall(r"\[(\d+),(\d+)\]", bstr)
        (x1, y1), (x2, y2) = [(int(a), int(b)) for (a, b) in pts]
        w, h = x2 - x1, y2 - y1
        return {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "w": w, "h": h, "cx": x1 + w // 2, "cy": y1 + h // 2,
            "area": max(w, 1) * max(h, 1)
        }
    except Exception:
        return None

def _confirmer_is_interactable(driver) -> bool:
    try:
        parent = driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='Confirmer']/..")
        if str(parent.get_attribute("clickable")).lower() == "true":
            return True
    except Exception:
        pass
    try:
        tv = driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='Confirmer']")
        return str(tv.get_attribute("enabled")).lower() == "true"
    except Exception:
        return False

def ensure_date_picker_visible(driver, wait):
    try:
        wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date")))
        return True
    except TimeoutException:
        logger.error("Date field not visible; cannot proceed to date picker.")
        return False

def tap_xy(driver, x: int, y: int, label: str = "tap_xy", retries: int = 2) -> bool:
    try:
        if driver.current_context != "NATIVE_APP":
            driver.switch_to.context("NATIVE_APP")
    except Exception:
        pass

    size = driver.get_window_size()
    x = max(1, min(int(x), int(size["width"]) - 2))
    y = max(1, min(int(y), int(size["height"]) - 2))

    try:
        driver.hide_keyboard()
    except Exception:
        pass

    last_err = None
    for _ in range(retries):
        try:
            TouchAction(driver).tap(x=x, y=y).perform()
            time.sleep(0.1)
            return True
        except Exception as e2:
            last_err = e2
        try:
            from appium.webdriver.common.actions.pointer_input import PointerInput
            from appium.webdriver.common.actions.action_builder import ActionBuilder
            finger = PointerInput(PointerInput.TOUCH, "finger")
            action = ActionBuilder(driver, mouse=finger)
            action.pointer_action.move_to_location(x, y)
            action.pointer_action.pointer_down()
            action.pointer_action.pause(0.03)
            action.pointer_action.pointer_up()
            action.perform()
            time.sleep(0.1)
            return True
        except Exception as e1:
            last_err = e1
        try:
            driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
            time.sleep(0.1)
            driver.execute_script("mobile: clickGesture", {"x": x+10, "y": y})
            driver.execute_script("mobile: clickGesture", {"x": x, "y": y+10})
            driver.execute_script("mobile: clickGesture", {"x": x+10, "y": y+10})
            driver.execute_script("mobile: clickGesture", {"x": x-10, "y": y-10})
            driver.execute_script("mobile: clickGesture", {"x": x-10, "y":y })
            driver.execute_script("mobile: clickGesture", {"x": x, "y": y+250})
            return True
        except Exception as e0:
            last_err = e0
       
       
        time.sleep(0.1)
    logger.error("[%s] All tap methods failed at (%s,%s): %s", label, x, y, last_err)
    return False


def _area(b):
    return max(0, b["x2"] - b["x1"]) * max(0, b["y2"] - b["y1"])

def _find_big_digit(driver, text: str):
    try:
        cal = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/composeableView")
        candidates = cal.find_elements(AppiumBy.XPATH, f".//android.widget.TextView[@text='{text}']")
    except Exception:
        candidates = driver.find_elements(AppiumBy.XPATH, f"//android.widget.TextView[@text='{text}']")

    best = None
    best_bounds = None
    best_area = -1

    for el in candidates:
        try:
            if not el.is_displayed():
                continue
        except Exception:
            pass
        b = _parse_bounds(el.get_attribute("bounds"))
        if not b:
            continue
        a = _area(b)
        if a > best_area:
            best, best_bounds, best_area = el, b, a

    return best, best_bounds

def click_calendar_pair_cell_precise(driver, greg_day: str, hijri_day: str, timeout=15) -> bool:
    h = (hijri_day or "").lstrip("0") or "0"
    end = time.time() + timeout

    while time.time() < end:
        try:
            logger.info(f"Trying to find element with text '{h}'")
            lbl_g, bounds = _find_big_digit(driver, h)
            if lbl_g and bounds:
                cx, cy = bounds["cx"], bounds["cy"]
                logger.info(f"Tapping '{h}' at ({cx}, {cy})")
                if tap_xy(driver, cx, cy, label=f"{h}_tap", retries=1):
                    time.sleep(1)
                    if _confirmer_is_interactable(driver):
                        logger.info(f"Successfully selected '{h}'")
                        return True
            else:
                logger.warning(f"No valid bounds for element '{h}'")
        except Exception:
            pass
        time.sleep(0.2)

    return False

def accept_privacy_if_present(driver, timeout: int = 3) -> bool:
    box_id = "com.moh.nusukapp:id/check_message"
    confirm_id = "com.moh.nusukapp:id/btn_confirm"

    try:
        sheet_present = False
        end = time.time() + timeout
        while time.time() < end:
            if driver.find_elements(AppiumBy.ID, box_id) or driver.find_elements(AppiumBy.ID, confirm_id):
                sheet_present = True
                break
            time.sleep(0.2)

        if not sheet_present:
            logger.info("[privacy] Consent sheet not present.")
            return True

        logger.info("[privacy] Consent sheet detected; accepting…")

        try:
            cb = WebDriverWait(driver, 4, 0.2).until(
                EC.presence_of_element_located((AppiumBy.ID, box_id))
            )
            checked = (cb.get_attribute("checked") or "").lower() == "true"
            if not checked:
                try:
                    cb.click()
                except Exception:
                    b = _parse_bounds(cb.get_attribute("bounds"))
                    if b:
                        tap_xy(driver, b["cx"], b["cy"], label="privacy_checkbox")
                time.sleep(0.1)
            else:
                logger.info("[privacy] Checkbox already checked.")
        except Exception as e:
            logger.info("[privacy] Checkbox not found or not required: %s", e)

        if not safe_click(driver, (AppiumBy.ID, confirm_id), name="privacy_confirm", timeout=5, retries=3):
            safe_click(driver, (AppiumBy.ANDROID_UIAUTOMATOR,
                                'new UiSelector().textContains("Confirmer")'),
                       name="privacy_confirm_text", timeout=3, retries=2)

        time.sleep(0.3)
        logger.info("[privacy] Consent accepted.")
        return True

    except Exception as e:
        logger.warning("[privacy] Could not handle consent sheet: %s", e)
        return False

# --- pre-book visible date verification --------------------------------------

import unicodedata

FR_MONTHS = {
    "01": "janvier", "02": "février", "03": "mars", "04": "avril",
    "05": "mai", "06": "juin", "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def verify_selected_date_label(driver, target_ddmm: str, timeout: int = 5) -> bool:
    try:
        dd, mm = target_ddmm.split("/")  # "06/09"
    except Exception:
        logger.error("verify_selected_date_label: bad target format: %r", target_ddmm)
        return False

    month = FR_MONTHS.get(mm, mm)
    day_tokens = {dd, dd.lstrip("0")}

    el = WebDriverWait(driver, timeout, 0.2).until(
        EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date"))
    )
    raw = (el.text or "")
    text = _strip_accents(raw).lower()
    month_norm = _strip_accents(month).lower()

    ok_month = month_norm in text
    ok_day   = any(tok in text for tok in day_tokens)

    logger.info("Pre-book check: label=%r | expect day in %s and month=%r -> %s/%s",
                raw, sorted(day_tokens), month, ok_day, ok_month)
    return ok_month and ok_day

# -----------------------------------------------------------------------------
# Reservation Flow (runtime-scoped I/O)

def make_reservation(
    driver,
    index: int,
    dict_row: dict,
    df: pd.DataFrame,
    target_ddmm: str,
    greg_day: str,
    hijri_day: str,
) -> None:
    accept_privacy_if_present(driver, timeout=1)
    driver.implicitly_wait(1)
    logger.info("[make_reservation] Start for row %s (passport=%s)", index, dict_row.get("numero_passport"))
    wait = WebDriverWait(driver, 10)

    # Open Rawdah
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"), name="nobleRawdahLL"):
        logger.error("Could not open Noble Rawdah screen.")
        return

    # Gender
    gender_hint = normalize_gender(dict_row.get("gender", "Unknown"))
    logger.info("[make_reservation] Gender normalized: %s", gender_hint)
    clicked_gender = None

    # Existing booking?
    if has_existing_booking(driver):
        logger.info("Existing booking detected; marking RESERVATION=1 and updating date/time/counters.")
        _set_df(df, index, "CREATION", "1")
        _set_df(df, index, "RESERVATION", "1")

        year = datetime.strptime(START_DATE, "%d_%m_%Y").year
        _set_df(df, index, "date_reservation", f"{target_ddmm}/{year}")
        _set_df(df, index, "heure", "10:00 AM")

        if gender_hint == "H":
            _increment_reserved(df, "H")
        elif gender_hint == "F":
            _increment_reserved(df, "F")
        return

    # Permit selection by gender
    if gender_hint == "F":
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                           name="permit_woman_tv", timeout=1):
                clicked_gender = "F"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                           name="permit_men_tv", timeout=1)
                clicked_gender = "H"
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                       name="permit_men_tv", timeout=1)
            clicked_gender = "H"

    elif gender_hint == "H":
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                           name="permit_men_tv", timeout=1):
                clicked_gender = "H"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                           name="permit_woman_tv", timeout=1)
                clicked_gender = "F"
        except Exception as e:
            logger.warning("permit_men_tv failed, trying woman: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                       name="permit_woman_tv", timeout=1)
            clicked_gender = "F"

    else:
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                           name="permit_woman_tv", timeout=1):
                clicked_gender = "F"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                           name="permit_men_tv", timeout=1)
                clicked_gender = "H"
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                       name="permit_men_tv", timeout=1)
            clicked_gender = "H"

    actual_gender = clicked_gender or gender_hint
    if actual_gender in {"F", "H"}:
        _set_df(df, index, "CREATION", "1")
        _set_df(df, index, "gender", actual_gender)
        dict_row["gender"] = actual_gender

    # Date field
    if not ensure_date_picker_visible(driver, wait):
        return

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date"), name="ed_selected_date"):
        return
    time.sleep(1)
    # Nudge the screen a bit to stabilize calendar rendering (robust scrolling)
   
    screen_size = driver.get_window_size()
    start_x = screen_size['width'] // 2
    start_y = int(screen_size['height'] * 0.6)
    end_y = int(screen_size['height'] * 0.4)
    driver.swipe(start_x, start_y, start_x, end_y, 500)
    time.sleep(1)
    # Date selection (native)
    if not click_calendar_pair_cell_precise(driver, greg_day=greg_day, hijri_day=hijri_day):
        logger.error("❌ Target %s/%s cell not found. Moving to next person.", greg_day, hijri_day)

    if not safe_click(driver, (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Confirmer")'), name="Confirmer"):
        logger.error("Could not click Confirmer.")
        return

    # Timeslots
    try:
        slots = WebDriverWait(driver, 10, 0.25).until(
            lambda d: [el for el in d.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")
                       if (el.text or "").strip()]
        )
        logger.info("Timeslots found: %s", [el.text for el in slots])
    except TimeoutException:
        logger.warning("No timeslots available within timeout.")
        return "NO_SLOTS"

    preferred = "06:00 PM" if actual_gender == "H" else "10:00 AM"
    picked = False
    for el in slots:
        if el.text == preferred:
            try:
                el.click()
                picked = True
                break
            except Exception:
                pass
    if not picked and slots:
        try:
            slots[-1].click()
        except Exception:
            logger.warning("Failed to click any timeslot.")

    # Safety: ensure visible date matches target
    if not verify_selected_date_label(driver, target_ddmm):
        logger.error("Date label mismatch; aborting booking.")
        return

    # Continue + approve
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/continue_button"), name="continue_button"):
        logger.error("Failed to click continue_button.")
        return
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/btn_approve_continue"), name="btn_approve_continue"):
        logger.error("Failed to click btn_approve_continue.")
        return

    # Success check
    time.sleep(0.3)
    elements = []
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_rating_3")
            if elements:
                txt = (elements[0].text or "").strip()
                if "Neutre" in txt:
                    break
        except Exception:
            pass
        time.sleep(0.25)

    if elements and "Neutre" in ((elements[0].text or "").strip()):
        year = datetime.strptime(START_DATE, "%d_%m_%Y").year
        _set_df(df, index, "CREATION", "1")
        _set_df(df, index, "RESERVATION", "1")
        _set_df(df, index, "heure", preferred)
        _set_df(df, index, "date_reservation", f"{target_ddmm}/{year}")
    else:
        sample = ((elements[0].text or "").strip()) if elements else "<none>"
        logger.error("Reservation success not confirmed. rating_3 text=%r", sample)

# -----------------------------------------------------------------------------
# Login Flow (runtime-scoped I/O)

def _wait_for_post_otp_state(driver, timeout=25) -> str:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"):
                return "SUCCESS"
        except Exception:
            pass
        try:
            if driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/check_message"):
                return "SUCCESS"
        except Exception:
            pass
        try:
            errs = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc")
            if errs:
                msg = (errs[0].text or "").lower()
                if any(k in msg for k in ["invalid", "incorrect", "wrong", "expired", "otp", "code"]):
                    try:
                        btn = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/tvYes")
                        btn.click()
                        logger.info("Dismissed OTP error dialog (OK).")
                    except Exception:
                        logger.warning("OTP error dialog present but could not dismiss.")
                    return "OTP_ERROR"
        except Exception:
            pass
        time.sleep(0.2)
    return "UNKNOWN"

def login_user(
    driver,
    index: int,
    row: Union[pd.Series, dict],
    df: pd.DataFrame,
    target_ddmm: str,
    greg_day: str,
    hijri_day: str,
) -> None:
    dict_row = row if isinstance(row, dict) else row.to_dict()
    logger.info(
        "[login_user] Row %s: %s %s | type_voyage=%s | CREATION=%s | RESERVATION=%s",
        index,
        dict_row.get("nom"),
        dict_row.get("prenom"),
        dict_row.get("type_voyage"),
        dict_row.get("CREATION"),
        dict_row.get("RESERVATION"),
    )

    if dict_row.get("CREATION") in ["0", "-1"]:
        logger.info("[login_user] No account; skipping.")
        return
    if dict_row.get("RESERVATION") == "1":
        logger.info("[login_user] Already reserved; skipping.")
        return
    if dict_row.get("RESERVATION") == "-1":
        logger.info("[login_user] Marked not ready; skipping.")
        return

    driver.implicitly_wait(1)
    wait = WebDriverWait(driver, 10)

    # Landing → Sign In
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), name="tvSignIn"):
        return
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), name="tvVisitor"):
        return
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), name="tvNationality"):
        return

    # Nationality
    _, PAYS_UPPER = get_nationality_from_row(dict_row)
    needle = (PAYS_UPPER or "").strip().lower()
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtSearch"), needle, name="edtSearch")
    found = False
    for el in driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTitle"):
        if (el.text or "").strip().lower() == needle:
            logger.info("[login_user] Target nationality matched; clicking: %r", el.text)
            try:
                el.click()
            except Exception:
                pass
            found = True
            break
    if not found:
        logger.error("Nationality %r not found in list.", needle)
        return

    # Credentials
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), dict_row.get("numero_passport", ""), name="edtPassport")
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"), "Hssouna1105@", name="edtPassword")
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), name="tvSignIn_submit"):
        return
    time.sleep(0.5)

    # Possible login error popups
    for _ in range(5):
        if driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_error_desc"):
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvYes"), name="tvYes_login_error")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), name="tvSignIn_retry") 
        else:
            break
    else:
        logger.error("Too many login errors; marking CREATION='-1'")
        _set_df(df, index, "CREATION", "1")
        return

    time.sleep(2)
    pregrant_location_permissions(driver, APP_PACKAGE)
    _pregrant_notification_permissions(driver, APP_PACKAGE)
    # OTP
    email = dict_row.get("email", "")
    logger.info("[login_user] Fetching OTP for email: %s", email)
    code = get_verification_code(email)
    if not code:
        logger.error("No OTP received; aborting this user.")
        return
    logger.info("[login_user] OTP received: %s", code)
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"), code, name="login_otp_edit_text")

    # Post-OTP evaluation (auto-dismiss error + one retry)
    state = _wait_for_post_otp_state(driver, timeout=25)
    if state == "OTP_ERROR":
        logger.warning("[login_user] OTP invalid/expired; retrying once with a fresh code...")
        time.sleep(1.0)
        code2 = get_verification_code(email)
        if not code2:
            logger.error("[login_user] Second OTP not available; aborting user.")
            return
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"), "", name="login_otp_edit_text", clear_first=True)
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/login_otp_edit_text"), code2, name="login_otp_edit_text")
        state = _wait_for_post_otp_state(driver, timeout=20)

    if state != "SUCCESS":
        logger.error("[login_user] Post-OTP state not successful: %s", state)
        return

    # Reservation
    make_reservation(driver, index, dict_row, df, target_ddmm, greg_day, hijri_day)
    logger.info("[login_user] Reservation step finished for row %s", index)

# -----------------------------------------------------------------------------
# In-process entry point (what you asked for)

def run_login_on_row(
    driver,
    row_index: int,
    row_series: pd.Series,
    csv_path: str,
    target_ddmm: str,
) -> pd.DataFrame:
    """
    Single-row login+reservation in-process.
    - driver: persistent Appium driver (already started)
    - row_index: index to write back into csv_path
    - row_series: pd.Series with the row data at start
    - csv_path: source CSV we update in place
    - target_ddmm: 'DD/MM' string; DO NOT read config.TARGET_DATE
    """
    # 0) Always re-read CSV to ensure fresh view
    df = _load_df(csv_path)
    df = _ensure_counter_columns(df)

    # 1) Inputs
    data = row_series.to_dict()
    # Day split for calendar
    dd = target_ddmm.split("/")[0]
    greg_day = dd
    hijri_day = greg_day

    # 2) Execute login+reservation (no driver quit here)
    try:
        login_user(
            driver=driver,
            index=row_index,
            row=row_series,
            df=df,
            target_ddmm=target_ddmm,
            greg_day=greg_day,
            hijri_day=hijri_day,
        )
    except Exception as e:
        logger.exception("run_login_on_row fatal: %s", e)

    # 3) Flush once at the end
    _save_df(df, csv_path)
    hard_reset_app(driver, APP_PACKAGE)
    return df
