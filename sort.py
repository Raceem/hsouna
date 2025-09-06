from __future__ import annotations

import math
import os
import re
import time
import traceback
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from mail import get_verification_code
from utils import mois_en_lettres
from pdf import pop_first_variant
import pandas as pd
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from mail import get_verification_code
from config import (
    CSV_FILE,
    EMAIL_JSON_FILE,
    NUMBER_JSON_FILE,
    setup_driver,
    PAYS_UPPER,
    TARGET_DATE,
    HIJRI_DAY,
    START_DATE,
)
CSV_FILE         = os.getenv("CSV_FILE_OVERRIDE", CSV_FILE)
EMAIL_JSON_FILE  = os.getenv("EMAIL_JSON_FILE_OVERRIDE", EMAIL_JSON_FILE)
NUMBER_JSON_FILE = os.getenv("NUMBER_JSON_FILE_OVERRIDE", NUMBER_JSON_FILE)
# -----------------------------------------------------------------------------
# Logging

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "automation.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("reservation")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))
logger.propagate = False
logger.handlers.clear()

ch = logging.StreamHandler()
ch.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))

fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
fh.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
    "%Y-%m-%d %H:%M:%S",
))

#####
APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")
csv_file = CSV_FILE
filename_email_json = EMAIL_JSON_FILE
filename_number_json = NUMBER_JSON_FILE

ERROR_DESC_ID = "com.moh.nusukapp:id/tv_error_desc"
ERROR_OK_ID   = "com.moh.nusukapp:id/tvYes"
BACK_BTN_ID   = "com.moh.nusukapp:id/imgBack"

df = pd.read_csv(csv_file, dtype=str)
###


logger.addHandler(ch)
logger.addHandler(fh)

# -----------------------------------------------------------------------------
# Config / Data
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


# Ensure gender and reservation counters exist
def _ensure_counter_columns():
    modified = False
    if "gender" not in df.columns:
        df["gender"] = ""
        modified = True
    if "reserved_men" not in df.columns:
        df["reserved_men"] = "0"
        modified = True
    if "reserved_women" not in df.columns:
        df["reserved_women"] = "0"
        modified = True
    if modified:
        df.to_csv(csv_file, index=False, encoding="utf-8")
        logger.info("Added missing gender/reserved columns and flushed to disk.")

_ensure_counter_columns()

def _flush_df():
    df.to_csv(csv_file, index=False, encoding="utf-8")
    logger.info("DataFrame flushed to disk.")

def _set_df(index: int, col: str, value: str, flush: bool = False):
    prev = df.at[index, col] if col in df.columns else None
    df.at[index, col] = value
    logger.info("DF Update [row=%s, col=%s]: %r -> %r", index, col, prev, value)
    if flush:
        _flush_df()


def _increment_reserved(gender_code: str) -> None:
    """Increment reserved counters in dataframe (no flush)."""
    col = "reserved_men" if gender_code == "H" else "reserved_women"
    try:
        current = int(df[col].iloc[0])
    except Exception:
        current = 0
    df[col] = str(current + 1)
# -----------------------------------------------------------------------------
# Helpers
def row_requires_app(row: pd.Series) -> bool:
    c = (row.get("CREATION") or "").strip()
    r = (row.get("RESERVATION") or "").strip()
    # Needs the app only if account exists AND not already reserved
    return c not in {"0","-1"} and r != "1"

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
    # Treat None/NaN/blank uniformly
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
        "La confirmation de","existing booking", "have an active permit",
        "You already have an existing booking for", "Vous avez déjà une réservation",
        'existing'
    ]
    for t in needles:
        try:
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{t}")')
            return True
        except Exception:
            pass
    return False

def safe_click(driver, locator, name="element", timeout=7, retries=2, poll=0.25, clickable=True):
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
    logger.error("[safe_send_keys] failed to type into %s: %s", name, last_err)
    return False


# --- permissions (only the one you actually call) ----------------------------

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

def _Confirm_is_interactable(driver) -> bool:
    try:
        parent = driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='Confirm']/..")
        if str(parent.get_attribute("clickable")).lower() == "true":
            return True
    except Exception:
        pass
    try:
        tv = driver.find_element(AppiumBy.XPATH, "//android.widget.TextView[@text='Confirm']")
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
            driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
            time.sleep(0.1)
            return True
        except Exception as e0:
            last_err = e0
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
            TouchAction(driver).tap(x=x, y=y).perform()
            time.sleep(0.1)
            return True
        except Exception as e2:
            last_err = e2
        time.sleep(0.1)
    logger.error("[%s] All tap methods failed at (%s,%s): %s", label, x, y, last_err)
    return False

def _area(b):
    # b = {"x1":..,"y1":..,"x2":..,"y2":..,"cx":..,"cy":..}
    return max(0, b["x2"] - b["x1"]) * max(0, b["y2"] - b["y1"])

def _find_big_digit(driver, text: str):
    # (Optional) first scope to the calendar container to avoid header/legend matches
    try:
        cal = driver.find_element(
            AppiumBy.ID, "com.moh.nusukapp:id/composeableView"
        )
        candidates = cal.find_elements(AppiumBy.XPATH, f".//android.widget.TextView[@text='{text}']")
    except Exception:
        candidates = driver.find_elements(AppiumBy.XPATH, f"//android.widget.TextView[@text='{text}']")

    best = None
    best_bounds = None
    best_area = -1

    for el in candidates:
        try:
            if not el.is_displayed():  # ignore hidden
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
                if tap_xy(driver, cx, cy, label=f"{h}_tap", retries=1):
                    time.sleep(0.15)
                    if _Confirm_is_interactable(driver):
                        return True

            logger.info(f"Element '{h}' bounds: {bounds}")

            if bounds:
                cx, cy = bounds["cx"], bounds["cy"]
                logger.info(f"Tapping '{h}' at ({cx}, {cy})")
                if tap_xy(driver, cx, cy, label=f"{h}_tap", retries=1):
                    time.sleep(0.15)
                    if _Confirm_is_interactable(driver):
                        logger.info(f"Successfully selected '{h}'")
                        return True
                else:
                    logger.warning(f"Tap on '{h}' failed.")
            else:
                logger.warning(f"No valid bounds for element '{h}'")
        except Exception:
            pass

        time.sleep(0.2)

    return False

def accept_privacy_if_present(driver, timeout: int = 3) -> bool:
    """
    If the post-OTP 'policy/privacy' sheet appears, tick the checkbox
    and press 'Confirm et continuer'. Returns True if handled or not present.
    """
    box_id = "com.moh.nusukapp:id/check_message"
    confirm_id = "com.moh.nusukapp:id/btn_confirm"
    ignore_id = "com.moh.nusukapp:id/btn_ignore"  # unused; we accept

    try:
        # Quick probe: is the sheet present?
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

        # Tick the checkbox if needed
        try:
            cb = WebDriverWait(driver, 4, 0.2).until(
                EC.presence_of_element_located((AppiumBy.ID, box_id))
            )
            checked = (cb.get_attribute("checked") or "").lower() == "true"
            if not checked:
                try:
                    cb.click()
                except Exception:
                    # try tapping its bounds center as fallback
                    b = _parse_bounds(cb.get_attribute("bounds"))
                    if b:
                        tap_xy(driver, b["cx"], b["cy"], label="privacy_checkbox")
                time.sleep(0.1)
            else:
                logger.info("[privacy] Checkbox already checked.")
        except Exception as e:
            logger.info("[privacy] Checkbox not found or not required: %s", e)

        # Press confirm
        if not safe_click(driver, (AppiumBy.ID, confirm_id), name="privacy_confirm", timeout=5, retries=3):
            # try by text as a fallback
            safe_click(driver, (AppiumBy.ANDROID_UIAUTOMATOR,
                                'new UiSelector().textContains("Confirm")'),
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
    """
    Ensure the date field shows the same Gregorian day+month we selected
    (e.g., 'samedi, 06 septembre'). Accepts '06' or '6' for the day.
    """
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
# Reservation Flow

def determine_gender(driver, index: int, dict_row: dict) -> None:
    # New UI: privacy/terms consent after OTP
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
        _set_df(index, "CREATION", "1")
        _set_df(index, "RESERVATION", "1")

        # date_reservation uses TARGET_DATE with the year from START_DATE (like success path)
        year = datetime.strptime(start_date, "%d_%m_%Y").year
        _set_df(index, "date_reservation", f"{target_date}/{year}")

        # force 10 AM as requested
        _set_df(index, "heure", "10:00 AM")

        # bump counters by sex if known
        if gender_hint == "H":
            _increment_reserved("H")
        elif gender_hint == "F":
            _increment_reserved("F")

        # one flush after all updates
        _flush_df()
        return
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
         # write immediately to the CSV as F/H
        _set_df(index, "CREATION", "1")
        _set_df(index, "gender", actual_gender, flush=True)
        # keep the in-memory row consistent for later logic
        dict_row["gender"] = actual_gender











# ====== Constants / Config ======




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
"""if "gender" not in df.columns:
    df["gender"] = ""
if "reserved_men" not in df.columns:
    df["reserved_men"] = "0"
if "reserved_women" not in df.columns:
    df["reserved_women"] = "0"  """
df.to_csv(csv_file, index=False, encoding="utf-8")
# ====== Core flow ======
def process_user(driver, index, row):
    dict_row = row.to_dict()
    logger.info(f"Ligne {index+1}: {dict_row['nom']} {dict_row['prenom']}")
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
            #pregrant_location_permissions(driver, APP_PACKAGE)

            code = get_verification_code(email)
            if code:
                otp_field = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text")))
                otp_field.send_keys(code)
                print(f"✅ Code trouvé : {code}")
                time.sleep(0.5)
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
            #login_make_reservation(driver, index, dict_row)
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
    print(f"Ligne {index+1}: {dict_row.get('nom')} {dict_row.get('prenom')}")
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
        #pregrant_location_permissions(driver, APP_PACKAGE)

        # Do the work for this row
        process_user(driver, index, row)
        determine_gender(driver, index, dict_row)
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






