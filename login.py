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

import os
import re
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

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

from mail import get_verification_code
from config import (
    CSV_FILE,
    setup_driver,
    PAYS_UPPER,
    TARGET_DATE,
    HIJRI_DAY,

    START_DATE,
)

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

logger.addHandler(ch)
logger.addHandler(fh)

# -----------------------------------------------------------------------------
# Config / Data

APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")

csv_file = CSV_FILE
target_date = TARGET_DATE            # "DD/MM"
start_date = START_DATE              # "DD_MM_YYYY"
greg_day = target_date.split("/")[0] if "/" in target_date else target_date
hijri_day = HIJRI_DAY

logger.info("Loading CSV: %s", csv_file)
df = pd.read_csv(csv_file, dtype=str)
logger.info("CSV loaded. Rows: %d, Columns: %d", len(df), len(df.columns))

def _flush_df():
    df.to_csv(csv_file, index=False, encoding="utf-8")
    logger.info("DataFrame flushed to disk.")

def _set_df(index: int, col: str, value: str, flush: bool = False):
    prev = df.at[index, col] if col in df.columns else None
    df.at[index, col] = value
    logger.info("DF Update [row=%s, col=%s]: %r -> %r", index, col, prev, value)
    if flush:
        _flush_df()

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

def normalize_gender(raw: str | None) -> str:
    s = (raw or "").strip().lower()
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

def click_calendar_pair_cell_precise(driver, greg_day: str, hijri_day: str, timeout=8) -> bool:
    """
    Click the smallest android.view.View whose descendants include BOTH text labels:
    TextView[@text=greg_day] AND TextView[@text=hijri_day].
    If parent cell has bad/missing bounds, fall back to tapping the midpoint
    between the two child labels. Verifies selection by checking 'Confirmer'.
    """
    g = (greg_day or "").lstrip("0") or "0"
    h = (hijri_day or "").lstrip("0") or "0"

    # Nudge sheet and allow layout to settle
    #screen_size = driver.get_window_size()
    #start_x = screen_size["width"] // 2
    #start_y = int(screen_size["height"] * 0.7)
    #end_y = int(screen_size["height"] * 0.3)
    #time.sleep(0.5)
    #driver.swipe(start_x, start_y, start_x, end_y, 500)
    #time.sleep(1.5)
    xp = f"//android.view.View[.//android.widget.TextView[@text='{g}'] and .//android.widget.TextView[@text='{h}']]"
    logger.info("Looking for calendar cell with XPath: %s", xp)

    end = time.time() + timeout
    while time.time() < end:
        try:
            parents = driver.find_elements(AppiumBy.XPATH, xp)
        except Exception:
            parents = []

        scored = []
        for el in parents:
            try:
                b = _parse_bounds(el.get_attribute("bounds"))
                if b and b["area"] > 0:
                    scored.append((b["area"], b, el))
            except Exception:
                continue

        if scored:
            scored.sort(key=lambda t: t[0])  # smallest cell first
            area, bounds, elem = scored[0]
            logger.info("Chosen cell for %s/%s: bounds=%s area=%s (of %d candidates)", g, h, bounds, area, len(scored))

            # Prefer a bounds tap; it's fast and avoids interception
            if tap_xy(driver, bounds["cx"], bounds["cy"], label=f"pair_{g}_{h}", retries=1):
                time.sleep(0.12)
                if _confirmer_is_interactable(driver):
                    logger.info("Selected %s/%s via bounds tap.", g, h)
                    return True

            # Last resort direct click
            try:
                elem.click()
                time.sleep(0.12)
                if _confirmer_is_interactable(driver):
                    logger.info("Selected %s/%s via element.click().", g, h)
                    return True
            except Exception as e:
                logger.debug("Direct click fallback failed on chosen cell: %s", e)

        # Fallback: compute and tap the midpoint between the two labels
        try:
            lbl_g = driver.find_element(AppiumBy.XPATH, f"//android.widget.TextView[@text='{g}']")
            lbl_h = driver.find_element(AppiumBy.XPATH, f"//android.widget.TextView[@text='{h}']")
            bg = _parse_bounds(lbl_g.get_attribute("bounds"))
            bh = _parse_bounds(lbl_h.get_attribute("bounds"))
            if bg and bh:
                cx = (bg["cx"] + bh["cx"]) // 2
                cy = (bg["cy"] + bh["cy"]) // 2
                if tap_xy(driver, cx, cy, label=f"pair_{g}_{h}_childfallback", retries=1):
                    time.sleep(0.15)
                    if _confirmer_is_interactable(driver):
                        logger.info("Selected %s/%s via child-center fallback.", g, h)
                        return True
        except Exception:
            pass

        time.sleep(0.2)  # let Compose settle and retry

    logger.info("No parent cell with valid bounds for %s/%s after wait.", g, h)
    return False
def accept_privacy_if_present(driver, timeout: int = 3) -> bool:
    """
    If the post-OTP 'policy/privacy' sheet appears, tick the checkbox
    and press 'Confirmer et continuer'. Returns True if handled or not present.
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

def make_reservation(driver, index: int, dict_row: dict) -> None:
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
    gender = normalize_gender(dict_row.get("gender", "Unknown"))
    logger.info("[make_reservation] Gender normalized: %s", gender)
    # Existing booking?
    if has_existing_booking(driver):
        logger.info("Existing booking detected; marking RESERVATION=1.")
        _set_df(index, "CREATION", "1",flush=True)     
        _set_df(index, "RESERVATION", "1", flush=True)
        return
    if gender == "F":
        try:
            if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                            name="permit_woman_tv", timeout=5):
                # fallback if first fails
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                        name="permit_men_tv", timeout=3)
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                    name="permit_men_tv", timeout=3)

    elif gender == "H":
        try:
            if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                            name="permit_men_tv", timeout=5):
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                        name="permit_woman_tv", timeout=3)
        except Exception as e:
            logger.warning("permit_men_tv failed, trying woman: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                    name="permit_woman_tv", timeout=3)

    else:
        try:
            if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"),
                            name="permit_woman_tv", timeout=3):
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                        name="permit_men_tv", timeout=3)
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"),
                    name="permit_men_tv", timeout=3)




    # Date field
    if not ensure_date_picker_visible(driver, wait):
        return

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/ed_selected_date"), name="ed_selected_date"):
        return
    time.sleep(0.08)

    # Date selection (native)
    if not click_calendar_pair_cell_precise(driver, greg_day=greg_day, hijri_day=hijri_day):
        logger.error("❌ Target %s/%s cell not found. Moving to next person.", greg_day, hijri_day)
    # Confirm the day selection in the calendar sheet
    if not safe_click(driver, (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Confirmer")'), name="Confirmer"):
        logger.error("Could not click Confirmer.")
        return

    # Timeslots (explicit wait for non-empty labels)
    try:
        slots = WebDriverWait(driver, 10, 0.25).until(
            lambda d: [el for el in d.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tvTime")
                       if (el.text or "").strip()]
        )
        logger.info("Timeslots found: %s", [el.text for el in slots])
    except TimeoutException:
        logger.warning("No timeslots available within timeout.")
        return "NO_SLOTS"

    preferred = "06:00 PM" if normalize_gender(dict_row.get("gender")) == "H" else "10:00 AM"
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

    # Safety: ensure visible date matches TARGET_DATE before booking
    if not verify_selected_date_label(driver, target_date):
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
    elements = driver.find_elements(AppiumBy.ID, "com.moh.nusukapp:id/tv_rating_3")
    if elements and "Neutre" in (elements[0].text or ""):
        year = datetime.strptime(start_date, "%d_%m_%Y").year
        _set_df(index, "CREATION", "1")     
        _set_df(index, "RESERVATION", "1")
        _set_df(index, "heure", preferred)
        _set_df(index, "date_reservation", f"{target_date}/{year}", flush=True)
    else:
        logger.error("Reservation success element not found or does not contain 'Neutre'.")
    

# -----------------------------------------------------------------------------
# Login Flow

def _wait_for_post_otp_state(driver, timeout=25) -> str:
    """
    After typing OTP, wait for:
      - SUCCESS: landing on home (Rawdah tile) or check/confirm modal
      - OTP_ERROR: dialog text mentions invalid/incorrect/expired otp/code
      - UNKNOWN: timeout
    If OTP_ERROR, attempt to dismiss the dialog.
    """
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

def login_user(driver, index: int, row: pd.Series) -> None:
    dict_row = row.to_dict()
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
    pregrant_location_permissions(driver, APP_PACKAGE)
    # Landing → Sign In
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvSignIn"), name="tvSignIn"):
        return
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), name="tvVisitor"):
        return
    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNationality"), name="tvNationality"):
        return

    # Nationality
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
    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), dict_row["numero_passport"], name="edtPassport")
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
        _set_df(index, "CREATION", "-1", flush=True)
        return
    time.sleep(2)
    # OTP
    email = dict_row["email"]
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
    make_reservation(driver, index, dict_row)
    logger.info("[login_user] Reservation step finished for row %s", index)

# -----------------------------------------------------------------------------
# Main
if __name__ == "__main__":
    logger.info("=== Session start ===")
    driver = None
    try:
        # Filter the dataframe so we iterate ONLY over rows that actually need work
        df_valid = df[df.apply(row_requires_app, axis=1)]
        total = len(df_valid)
        logger.info("Planned rows (need app): %s of %s total", total, len(df))

        for i, (index, row_series) in enumerate(df_valid.iterrows(), start=1):
            logger.info("---- Processing row %s/%s (orig index=%s) ----", i, total, index)

            # Cold restart: quit any previous session, then create a fresh driver
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
                finally:
                    driver = None

            try:
                driver = setup_driver()
                driver.implicitly_wait(1)  # keep tiny
                update_fast_settings(driver)
                # Pre-grant per fresh session (fast; avoids permission UI)
                pregrant_location_permissions(driver, APP_PACKAGE)

                # Do the work
                login_user(driver, index, row_series)

            except Exception as e:
                logger.exception("❌ Fatal error for row %s (orig index=%s): %s", i, index, e)

            finally:
                # Always end this row with a cold shutdown to guarantee a clean next start
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    finally:
                        driver = None

        logger.info("All planned rows processed.")
    except Exception as e:
        logger.exception("Top-level error: %s", e)
    finally:
        # Double safety
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        logger.info("=== Session end ===")