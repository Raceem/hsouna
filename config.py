import os
import threading
from venv import logger
from appium import webdriver
from appium.options.android import UiAutomator2Options

# =========================
# Base paths & CSV settings
# =========================
FOLDER_NAME = "09_25__2025"
BASE_DIR = r"C:\Users\SBS\Desktop\Hsouna"
CSV_FILE = 'C:/Users/SBS/Desktop/Hsouna/ALL.csv'
EMAIL_JSON_FILE = os.path.join(BASE_DIR, "email_variants.json")
NUMBER_JSON_FILE = os.path.join(BASE_DIR, "saudi_numbers.json")

# CSV files used by the web UI for statistics
ALL_CSV_PATH = os.path.join(BASE_DIR, "ALL.csv")
HOMMES_CSV_PATH = os.path.join(BASE_DIR, "HOMMES.csv")
FEMMES_CSV_PATH = os.path.join(BASE_DIR, "FEMMES.csv")

TO_DELETE_CSV_PATH = os.path.join(BASE_DIR, "TO_DELETE.csv")
# Default PDF path
PDF_FILE = r"C:/Users/SBS/Desktop/Hsouna/_inbox/merged (4).pdf"
# Directories where confirmation screenshots will be stored
RAWDHA_DIR = os.path.join(BASE_DIR, FOLDER_NAME, "rawdha")
RESERVATION_DIR = os.path.join(BASE_DIR, FOLDER_NAME, "reservations")
ALL_IMPORT_CSV = r"C:/Users/SBS/Desktop/Hsouna/_inbox/latest_import.csv"

# =====================
# Domain configuration
# =====================
PAYS = "egypt"
PAYS_UPPER = PAYS.lower()
TARGET_DATE = "23/09"
HIJRI_DAY = "22"
START_DATE = "02_08_2025"
DURATION_DAYS = 31

# CSV headers
FIELDNAMES = [
    "nom",
    "prenom",
    "date_de_naissance",
    "numero_visa",
    "numero_passport",
    "nationalite",
    "gender",
    "email",
    "numero_tlf",
    "have_a_compte",
    "CREATION",
    "RESERVATION",
    "CONFIRMATION",
    "date_reservation",
    "heure",     # <-- new field
]

# ===================
# Appium configuration
# ===================
APPIUM_SERVER = "http://127.0.0.1:4723"
PLATFORM_NAME = "Android"
PLATFORM_VERSION = "9"

# App under test
APP_PACKAGE = os.getenv("APP_PACKAGE", "com.moh.nusukapp")
# If you really want to force a starting activity, set APP_ACTIVITY in env to a FULLY QUALIFIED class name,
# e.g. "com.app.nusuk.Splashscreen". Otherwise leave empty and let Android/Appium discover the launcher.
APP_ACTIVITY = os.getenv("APP_ACTIVITY", "").strip()

# Device identifiers
# Use a human-readable label for deviceName, and the actual ADB serial for udid
DEVICE_LABEL = "Android"
UDID = "DEF4C19312001213"

# If you scale out to multiple devices, ensure unique systemPort per device
DEVICES = [
            {
        "name": "huawei",
        "udid": "DEF4C19312001213",
        "platformVersion": PLATFORM_VERSION,
        "systemPort": 6546,
        "appiumServer": "http://127.0.0.1:4726",
    },
        {
        "name": "redmi",
        "udid": "R8YY703MJKW",
        "platformVersion": "15",
        "systemPort": 8974,
        "appiumServer": "http://127.0.0.1:4723",
    },
]

# =================================
# Driver creation (single device API)
# =================================
def setup_driver() -> webdriver.Remote:
    """
    Create and return a configured Appium driver for a single device run.
    Robust to activity transitions (Splash -> LoginRegistration, etc.).
    """
    options = UiAutomator2Options()
    options.platform_name = PLATFORM_NAME
    options.platform_version = PLATFORM_VERSION
    options.device_name = DEVICE_LABEL
    options.automation_name = "uiautomator2"
    options.language = "fr"
    options.locale = "FR"

    # Required app caps
    options.app_package = APP_PACKAGE
    # Only set appActivity if provided and fully-qualified (no 'package/activity' form)
    if APP_ACTIVITY:
        options.app_activity = APP_ACTIVITY

    # Device routing caps
    options.set_capability("udid", UDID)
    options.set_capability("autoGrantPermissions", True)

    # Be tolerant to initial activity hops
    options.set_capability("appWaitPackage", APP_PACKAGE)
    # Accept any activity under the app's own secondary package namespace
    # Observed from logs: com.app.nusuk.Splashscreen -> com.app.nusuk.LoginRegistrationActivity
    options.set_capability("appWaitActivity", "com.app.nusuk.*")
    options.set_capability("appWaitDuration", 30000)

    # Quality-of-life / stability
    options.set_capability("newCommandTimeout", 180)
    options.set_capability("disableWindowAnimation", True)

    drv = webdriver.Remote(APPIUM_SERVER, options=options)

    # Fast UI settings (ignore failures gracefully)
    try:
        drv.update_settings({"waitForIdleTimeout": 0, "ignoreUnimportantViews": True})
    except Exception:
        pass

    return drv

# ==================================
# Driver pool (multi-device helpers)
# ==================================
_pool_lock = threading.Lock()
_driver_by_udid: dict[str, webdriver.Remote] = {}

def _new_driver_for(device: dict) -> webdriver.Remote:
    """
    Internal: create a new driver instance for a specific device dict from DEVICES.
    Ensures unique systemPort and robust waits identical to setup_driver().
    """
    opts = UiAutomator2Options()
    opts.platform_name = PLATFORM_NAME
    opts.platform_version = device["platformVersion"]
    opts.device_name = DEVICE_LABEL
    opts.automation_name = "uiautomator2"
    opts.language = "fr"
    opts.locale = "FR"

    # App caps
    opts.app_package = APP_PACKAGE
    if APP_ACTIVITY:
        opts.app_activity = APP_ACTIVITY  # only if fully-qualified; otherwise omit

    # Device routing caps
    opts.set_capability("udid", device["udid"])
    opts.set_capability("systemPort", device["systemPort"])  # IMPORTANT: unique per device
    opts.set_capability("autoGrantPermissions", True)

    # Robust waits for splash → login transitions
    opts.set_capability("appWaitPackage", APP_PACKAGE)
    opts.set_capability("appWaitActivity", "com.app.nusuk.*")
    opts.set_capability("appWaitDuration", 30000)

    # QoL
    opts.set_capability("newCommandTimeout", 180)
    opts.set_capability("disableWindowAnimation", True)

    # Prefer device-specific server if provided; otherwise APPIUM_SERVER
    server = device.get("appiumServer") or APPIUM_SERVER
    try:
        drv = webdriver.Remote(command_executor=server, options=opts)
    except Exception as e:
        # Fallback: try the global APPIUM_SERVER in case the device mapping points
        # to a server that is not running. This allows running multiple devices on
        # a single Appium server as long as "systemPort" is unique per device.
        if server != APPIUM_SERVER:
            try:
                drv = webdriver.Remote(command_executor=APPIUM_SERVER, options=opts)
            except Exception:
                raise e
        else:
            raise e

    try:
        drv.update_settings({"waitForIdleTimeout": 0, "ignoreUnimportantViews": True})
    except Exception:
        pass

    return drv

def get_driver(udid: str) -> webdriver.Remote:
    """
    Get or create a cached driver for a given udid from DEVICES.
    """
    with _pool_lock:
        drv = _driver_by_udid.get(udid)
        if drv is None:
            device = next(d for d in DEVICES if d["udid"] == udid)
            drv = _new_driver_for(device)
            _driver_by_udid[udid] = drv
        return drv

def reset_driver(udid: str):
    """
    Dispose a cached driver for a given udid, if present.
    """
    with _pool_lock:
        drv = _driver_by_udid.pop(udid, None)
    if drv:
        try:
            drv.quit()
        except Exception:
            pass

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
    except Exception:
        pass

