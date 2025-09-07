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
from pathlib import Path
from threading import RLock

from config import (
    ALL_CSV_PATH,
    CSV_FILE,
    EMAIL_JSON_FILE,
    FEMMES_CSV_PATH,
    HOMMES_CSV_PATH,
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

logger.addHandler(ch)
logger.addHandler(fh)

# -----------------------------------------------------------------------------
APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")

# Accept overrides from the web app so we don't edit config.py
csv_file = ALL_CSV_PATH
hommes_csv = HOMMES_CSV_PATH
femmes_csv = FEMMES_CSV_PATH
base_dir_override = os.getenv("BASE_DIR_OVERRIDE")  # optional

filename_email_json = EMAIL_JSON_FILE
filename_number_json = NUMBER_JSON_FILE

start_date = START_DATE
target_date = TARGET_DATE

ERROR_DESC_ID = "com.moh.nusukapp:id/tv_error_desc"
ERROR_OK_ID   = "com.moh.nusukapp:id/tvYes"
BACK_BTN_ID   = "com.moh.nusukapp:id/imgBack"

# -----------------------------------------------------------------------------
# Disk I/O helpers (atomic-ish) + lock to avoid self-overwrites
_FILE_LOCK = RLock()

def _save_df_hard(df: pd.DataFrame, path: str):
    p = Path(path).resolve()
    with open(p, "w", newline="", encoding="utf-8") as f:
        df.to_csv(f, index=False)
        f.flush()
        os.fsync(f.fileno())
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))
    logger.info(f"[SAVE] wrote → {p} (mtime={ts})")

def _append_row_to_csv(dest_csv: str, row_dict: dict):
    os.makedirs(os.path.dirname(dest_csv), exist_ok=True)
    with _FILE_LOCK:
        if not os.path.exists(dest_csv):
            pd.DataFrame([row_dict]).to_csv(dest_csv, index=False, encoding="utf-8")
            return
        existing = pd.read_csv(dest_csv, dtype=str, keep_default_na=False)
        for c in row_dict.keys():
            if c not in existing.columns:
                existing[c] = ""
        for c in existing.columns:
            row_dict.setdefault(c, "")
        existing = pd.concat([existing, pd.DataFrame([row_dict])[existing.columns]], ignore_index=True)
        _save_df_hard(existing, dest_csv)

# -----------------------------------------------------------------------------
# Ensure required columns exist (read→modify→save)
def _ensure_counter_columns():
    with _FILE_LOCK:
        try:
            d = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
        except Exception:
            d = pd.DataFrame()
        modified = False
        if "gender" not in d.columns:
            d["gender"] = ""
            modified = True
        if "reserved_men" not in d.columns:
            d["reserved_men"] = "0"
            modified = True
        if "reserved_women" not in d.columns:
            d["reserved_women"] = "0"
            modified = True
        if modified:
            _save_df_hard(d, csv_file)
            logger.info("Added missing gender/reserved columns.")

_ensure_counter_columns()

def _flush_df():
    # No-op by design: avoid flushing any stale in-memory DataFrame.
    pass

def _set_df(index: int, col: str, value: str, flush: bool = False):
    """Safe point-update by current row INDEX (reads file fresh)."""
    with _FILE_LOCK:
        d = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
        if col not in d.columns:
            d[col] = ""
        if 0 <= index < len(d):
            prev = d.at[index, col] if col in d.columns else None
            d.at[index, col] = value
            logger.info("DF Update [row=%s, col=%s]: %r -> %r", index, col, prev, value)
            _save_df_hard(d, csv_file)

def _increment_reserved(gender_code: str) -> None:
    """Increment reserved counters (read→modify→save)."""
    col = "reserved_men" if gender_code == "H" else "reserved_women"
    with _FILE_LOCK:
        d = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
        if col not in d.columns:
            d[col] = "0"
        try:
            current = int(str(d[col].iloc[0]))
        except Exception:
            current = 0
        d[col] = str(current + 1)
        _save_df_hard(d, csv_file)

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
        "You already have an existing booking for", "Vous avez déjà une réservation", "existing"
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

# --- permissions --------------------------------------------------------------
def pregrant_location_permissions(driver, package: str = APP_PACKAGE):
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
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "w": w, "h": h, "cx": x1 + w // 2, "cy": y1 + h // 2, "area": max(w, 1) * max(h, 1)}
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

def _area(b):  # unused helper kept for reference
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
        a = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
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
    box_id = "com.moh.nusukapp:id/check_message"
    confirm_id = "com.moh.nusukapp:id/btn_confirm"

    DETECT_WAIT = min(timeout, 0.8)  
    CLICK_WAIT  = 1.0                
    GONE_WAIT   = 1.5                 
    POLL        = 0.1                 
    RETRIES     = 1                   

    try:
        # 1) Détection rapide de la feuille (présence du bouton)
        try:
            btn = WebDriverWait(driver, DETECT_WAIT, poll_frequency=POLL).until(
                EC.presence_of_element_located((AppiumBy.ID, confirm_id))
            )
        except TimeoutException:
            # Pas de consent sheet => on avance
            logger.info("[privacy] Consent sheet not present (fast).")
            return True

        logger.info("[privacy] Consent sheet detected; enforcing checkbox…")

        # (Optionnel) accélérer temporairement l'UIA2 pour cette action très courte
        old_settings = None
        try:
            old_settings = driver.get_settings()
            driver.update_settings({"waitForIdleTimeout": 0, "actionAcknowledgmentTimeout": 0})
        except Exception:
            pass

        # 2) Case obligatoire : on la trouve et on la coche (ou on échoue)
        try:
            cb = WebDriverWait(driver, CLICK_WAIT, poll_frequency=POLL).until(
                EC.presence_of_element_located((AppiumBy.ID, box_id))
            )
        except TimeoutException:
            # Si pas de case mais bouton déjà activé, on peut tolérer (rare UX) — sinon, fail-closed
            try:
                enabled = (btn.get_attribute("enabled") or "").lower() == "true"
            except Exception:
                enabled = False
            if not enabled:
                logger.warning("[privacy] Checkbox missing and confirm disabled -> fail-closed.")
                # restore settings avant de sortir
                try:
                    if old_settings: driver.update_settings(old_settings)
                except Exception:
                    pass
                return False
            cb = None  # pas de case requise (fallback toléré)

        if cb is not None:
            # On tente de cocher + re-lecture de l'état
            ok_checked = False
            for _ in range(RETRIES + 1):
                try:
                    if (cb.get_attribute("checked") or "").lower() == "true":
                        ok_checked = True
                        break
                except Exception:
                    pass
                try:
                    cb.click()
                except Exception:
                    # tap XY en secours
                    try:
                        b = _parse_bounds(cb.get_attribute("bounds"))
                        if b:
                            tap_xy(driver, b["cx"], b["cy"], label="privacy_checkbox")
                    except Exception:
                        pass
                time.sleep(0.05)

            # Re-lecture finale
            try:
                ok_checked = (cb.get_attribute("checked") or "").lower() == "true"
            except Exception:
                pass

            if not ok_checked:
                logger.warning("[privacy] Checkbox could not be verified as checked -> fail-closed.")
                try:
                    if old_settings: driver.update_settings(old_settings)
                except Exception:
                    pass
                return False

        # 3) Cliquer 'Confirmer' vite (clic direct + fallbacks courts)
        clicked = False
        try:
            btn = WebDriverWait(driver, CLICK_WAIT, poll_frequency=POLL).until(
                EC.element_to_be_clickable((AppiumBy.ID, confirm_id))
            )
            btn.click()
            clicked = True
        except Exception:
            # Fallback 1: par texte
            try:
                driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().textContains("Confirmer")'
                ).click()
                clicked = True
            except Exception:
                # Fallback 2: tap XY
                try:
                    b = _parse_bounds(btn.get_attribute("bounds"))
                    if b:
                        tap_xy(driver, b["cx"], b["cy"], label="privacy_confirm_xy")
                        clicked = True
                except Exception:
                    pass

        if not clicked:
            logger.warning("[privacy] Could not click confirm.")
            try:
                if old_settings: driver.update_settings(old_settings)
            except Exception:
                pass
            return False

        # 4) Vérifier disparition de la feuille (sinon, échec)
        end = time.time() + GONE_WAIT
        dismissed = False
        while time.time() < end:
            still_here = bool(
                driver.find_elements(AppiumBy.ID, confirm_id) or
                driver.find_elements(AppiumBy.ID, box_id)
            )
            if not still_here:
                dismissed = True
                break
            time.sleep(0.1)

        # Restore settings
        try:
            if old_settings: driver.update_settings(old_settings)
        except Exception:
            pass

        if not dismissed:
            logger.warning("[privacy] Sheet still visible after confirm -> failure.")
            return False

        logger.info("[privacy] Consent accepted swiftly.")
        return True

    except Exception as e:
        logger.warning("[privacy] Exception: %s", e)
        return False

# -----------------------------------------------------------------------------
# Nationality
def get_nationality_from_row(row_dict):
    """
    Return (search_text, match_key_lower) for nationality.
    Falls back to config when empty.
    """
    val = row_dict.get("nationalite")
    try:
        is_missing = val is None or (pd.isna(val)) or (str(val).strip() == "")
    except Exception:
        is_missing = True
    if is_missing:
        s = PAYS_UPPER  # use configured country text
        return s, str(s).lower()
    s = str(val).strip()
    return s, s.lower()

# -----------------------------------------------------------------------------
# Fast popup checks used before/around email step (write via _set_df)
def wait_for_error_text(driver, timeout=1, poll=0.2):
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
    yes = wait.until(EC.element_to_be_clickable((AppiumBy.ID, ERROR_OK_ID)))
    yes.click()

def handle_possible_error_after_mobile_or_pre_email(driver, wait, index, email_holder):
    err = wait_for_error_text(driver, timeout=4)
    if not err:
        return "none"
    print(f"Erreur détectée : {err}")
    click_error_yes(wait)
    low = err.lower()

    if "email is already used" in low or ("email" in low and "already" in low and "use" in low):
        new_email = pop_first_variant(filename_email_json)
        _set_df(index, "email", new_email, flush=True)
        email_holder["email"] = new_email
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), new_email, "Email retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
        return "handled"

    if ("mobile" in low or "phone" in low) and ("already" in low or "used" in low or "registered" in low or "exists" in low):
        safe_click(driver, (AppiumBy.ID, BACK_BTN_ID), "Back from mobile error")
        new_number = pop_first_variant(filename_number_json)
        _set_df(index, "numero_tlf", new_number, flush=True)
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), new_number, "Mobile retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
        safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_holder["email"], "Email after mobile retry", clear_first=True)
        safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
        return "handled"

    if any(k in low for k in ("your account", "the user", "visa")):
        _set_df(index, "CREATION", "-1", flush=True)
        return "have_account"

    if "otp" in low or "invalid" in low:
        return "handled"

    return "handled"

# -----------------------------------------------------------------------------
# Reservation Flow
def determine_gender(driver, index: int, dict_row: dict) -> None:
    
    try:
        driver.implicitly_wait(1)
    except Exception:
        pass
    logger.info("[make_reservation] Start for row %s (passport=%s)", index, dict_row.get("numero_passport"))
    wait = WebDriverWait(driver, 10)

    if not safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/nobleRawdahLL"), name="nobleRawdahLL"):
        logger.error("Could not open Noble Rawdah screen.")
        return

    gender_hint = normalize_gender(dict_row.get("gender", "Unknown"))
    logger.info("[make_reservation] Gender normalized: %s", gender_hint)
    clicked_gender = None

    if has_existing_booking(driver):
        logger.info("Existing booking detected; marking RESERVATION=1 and updating date/time/counters.")
        _set_df(index, "CREATION", "1")
        _set_df(index, "RESERVATION", "1")
        year = datetime.strptime(start_date, "%d_%m_%Y").year
        _set_df(index, "date_reservation", f"{target_date}/{year}")
        _set_df(index, "heure", "10:00 AM")
        if gender_hint == "H":
            _increment_reserved("H")
        elif gender_hint == "F":
            _increment_reserved("F")
        _flush_df()
        return

    if gender_hint == "F":
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv", timeout=1):
                clicked_gender = "F"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=1)
                clicked_gender = "H"
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=1)
            clicked_gender = "H"

    elif gender_hint == "H":
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=1):
                clicked_gender = "H"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv", timeout=1)
                clicked_gender = "F"
        except Exception as e:
            logger.warning("permit_men_tv failed, trying woman: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv", timeout=1)
            clicked_gender = "F"

    else:
        try:
            if safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_woman_tv"), name="permit_woman_tv", timeout=1):
                clicked_gender = "F"
            else:
                safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=1)
                clicked_gender = "H"
        except Exception as e:
            logger.warning("permit_woman_tv failed, trying men: %s", e)
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/permit_men_tv"), name="permit_men_tv", timeout=1)
            clicked_gender = "H"

    actual_gender = clicked_gender or gender_hint
    if actual_gender in {"F", "H"}:
        _set_df(index, "CREATION", "1")
        _set_df(index, "gender", actual_gender)
        dict_row["gender"] = actual_gender

# -----------------------------------------------------------------------------
# Core flow
def process_user(driver, index, row):
    dict_row = row.to_dict()
    logger.info(f"Ligne {index+1}: {dict_row.get('nom')} {dict_row.get('prenom')}")
    if dict_row.get('CREATION') in ["1", "-1"]:
        logger.info("Cet utilisateur a déjà un compte")
        return

    while True:
        try:
            wait = WebDriverWait(driver, 10)
            try:
                driver.implicitly_wait(1)
            except Exception:
                pass

            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvVisitor"), "VisitorType")

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

            numero_passport = dict_row.get("numero_passport", "")
            logger.info("numero_passport %s", numero_passport)
            if numero_passport == "Non trouvé" or not numero_passport:
                print("❌ Numéro de passeport manquant.")
                break
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassport"), numero_passport, "Passport number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after passport")

            numero_visa = dict_row.get("numero_visa", "")
            logger.info("visa %s", numero_visa)
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtVisaNo"), numero_visa, "Visa number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after visa")
            pregrant_location_permissions(driver, APP_PACKAGE)

            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvDOB"), "DOB field")
            wait.until(lambda d: len(driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")) >= 3)
            date_pickers = driver.find_elements(AppiumBy.ID, "android:id/numberpicker_input")

            date_de_naissance = dict_row.get("date_de_naissance", "01/01/1990")
            date_pickers[2].click(); date_pickers[2].clear(); time.sleep(0.1); date_pickers[2].send_keys("2000"); time.sleep(0.1)
            date_pickers[0].click(); driver.hide_keyboard()

            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvAdd"), "Add DOB")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after DOB")

            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvNo"), "No mobile prompt")

            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtPassword"), "Hssouna1105@", "Password")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgMuslimTermsCheckbox"), "MuslimTerms")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/imgTermsCheckbox"), "Terms")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvCreateAccount"), "CreateAccount submit")

            numero_tlf = dict_row.get("numero_tlf", "")
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), numero_tlf, "Mobile number")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile")

            email_holder = {"email": dict_row.get("email", "")}

            email = email_holder["email"]
            safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email, "Email")
            safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email")

            # Post-email popups loop
            email_current = email
            while True:
                error_text = wait_for_error_text(driver, timeout=2)
                if not error_text:
                    break
                print(f"Erreur détectée : {error_text}")
                click_error_yes(wait)
                low = error_text.lower()

                if "email is already used" in low or ("email" in low and "already" in low and "use" in low):
                    email_current = pop_first_variant(filename_email_json)
                    _set_df(index, "email", email_current, flush=True)
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email retry")
                    continue

                elif ("mobile" in low or "phone" in low):
                    safe_click(driver, (AppiumBy.ID, BACK_BTN_ID), "Back from mobile error")
                    new_number = pop_first_variant(filename_number_json)
                    _set_df(index, "numero_tlf", new_number, flush=True)
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtMobileNo"), new_number, "Mobile retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after mobile retry")
                    safe_send_keys(driver, (AppiumBy.ID, "com.moh.nusukapp:id/edtEmail"), email_current, "Email after mobile retry", clear_first=True)
                    safe_click(driver, (AppiumBy.ID, "com.moh.nusukapp:id/tvContinue"), "Continue after email re-entry")
                    continue

                elif ("your account" in low) or ("the user" in low) or ("visa" in low):
                    _set_df(index, "CREATION", "-1", flush=True)
                    return
                else:
                    break

            email = email_current

            time.sleep(1)

            code = get_verification_code(email)
            if code:
                otp_field = wait.until(EC.presence_of_element_located((AppiumBy.ID, "com.moh.nusukapp:id/nafath_otp_edit_text")))
                otp_field.send_keys(code)
                print(f"✅ Code trouvé : {code}")
                time.sleep(0.5)
                otp_err = wait_for_error_text(driver, timeout=4)
                if otp_err:
                    print(f"Erreur détectée : {otp_err}")
                    click_error_yes(wait)
                    low = otp_err.lower()
                    if any(k in low for k in ("your account", "the user", "visa")):
                        _set_df(index, "CREATION", "-1", flush=True)
                        return

            dict_row['CREATION'] = "1"
            _set_df(index, "CREATION", "1", flush=True)
            accept_privacy_if_present(driver, timeout=1)
            break

        except Exception as e:
            print(f"❌ Erreur : {e}")
            print("🔄 Tentative de relance...")
            traceback.print_exc()

# -----------------------------------------------------------------------------
def hard_reset_app(driver, package: str):
    try:
        driver.execute_script(
            "mobile: shell",
            {"command": "pm", "args": ["clear", package], "includeStderr": True, "timeout": 20000},
        )
    except Exception as e:
        logger.info(f"[hard_reset_app] pm clear failed (continuing): {e}")
    try:
        driver.terminate_app(package)
    except Exception:
        pass
    driver.activate_app(package)
    try:
        driver.implicitly_wait(1)
        update_fast_settings(driver)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# MAIN
def main():
    driver = None
    try:
        driver = setup_driver()
        update_fast_settings(driver)

        while True:
            try:
                df_current = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
                logger.info(df_current)
            except Exception as e:
                logger.error("Cannot read %s: %s", csv_file, e)
                break

            if df_current.empty:
                logger.info("No more rows in %s.", csv_file)
                break

            picked_idx = None
            for i, row in df_current.iterrows():
                picked_idx = i
                break

            if picked_idx is None:
                logger.info("No rows found.")
                break

            row = df_current.iloc[picked_idx]
            dict_row = row.to_dict()
            logger.info("---- Processing row (index=%s): %s %s ----",
                        picked_idx, dict_row.get('id'), dict_row.get('prenom'))

            try:
                hard_reset_app(driver, APP_PACKAGE)
                update_fast_settings(driver)
            except Exception as e:
                logger.info("reset/fast settings failed (continuing): %s", e)

            creation_flag = (str(dict_row.get('CREATION') or "").strip())
            moved_or_deleted = False

            try:
                if creation_flag not in {"1", "-1"}:
                    process_user(driver, picked_idx, row)
                    # reload just this row
                    df_after = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
                    if 0 <= picked_idx < len(df_after) and str(df_after.iloc[picked_idx].get("CREATION", "")).strip() == "1":
                        determine_gender(driver, picked_idx, dict_row)

                # Reload after potential updates
                df_after = pd.read_csv(csv_file, dtype=str, keep_default_na=False)

                if picked_idx >= len(df_after):
                    updated_row = None
                    passport = (dict_row.get("numero_passport") or "").strip()
                    if passport and "numero_passport" in df_after.columns:
                        m = df_after[df_after["numero_passport"].astype(str).str.strip() == passport]
                        if not m.empty:
                            updated_row = m.iloc[0]
                    if updated_row is None:
                        logger.warning("Cannot locate updated row; skipping move.")
                        continue
                else:
                    updated_row = df_after.iloc[picked_idx]

                updated = {k: str(v) for k, v in updated_row.to_dict().items()}
                creation_flag = (updated.get("CREATION") or "").strip()
                gender = (updated.get("gender") or "").strip().upper()

                if creation_flag == "-1":
                    df_after = df_after.drop(index=picked_idx).reset_index(drop=True)
                    _save_df_hard(df_after, csv_file)
                    logger.info("Marked as has account/invalid → removed from ALL.csv")
                    moved_or_deleted = True

                elif creation_flag == "1":
                    if gender in {"H", "F"} and hommes_csv and femmes_csv:
                        dest_csv = hommes_csv if gender == "H" else femmes_csv
                        _append_row_to_csv(dest_csv, updated)
                        df_after = df_after.drop(index=picked_idx).reset_index(drop=True)
                        _save_df_hard(df_after, csv_file)
                        logger.info("Moved to %s and removed from ALL.csv", "HOMMES" if gender == "H" else "FEMMES")
                        moved_or_deleted = True
                    else:
                        logger.info("CREATION=1 but gender unknown; keeping row in ALL.csv")
                else:
                    logger.info("Row not completed yet; keeping it for retry later.")

            except Exception as e:
                logger.error("Fatal error while processing row %s: %s", picked_idx, e)
                traceback.print_exc()

            time.sleep(0.3)

            if not moved_or_deleted:
                try:
                    df_after = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
                    if 0 <= picked_idx < len(df_after):
                        row_df = df_after.iloc[[picked_idx]].copy()
                        df_rest = df_after.drop(index=picked_idx).reset_index(drop=True)
                        df_new = pd.concat([df_rest, row_df], ignore_index=True)
                        _save_df_hard(df_new, csv_file)
                        logger.info("Row kept and moved to bottom for later retry.")
                except Exception as e:
                    logger.info("Could not rotate row to bottom: %s", e)

        logger.info("All done. Exiting sort loop.")

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

if __name__ == "__main__":
    main()
