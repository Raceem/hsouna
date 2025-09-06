import os
from appium import webdriver
from appium.options.android import UiAutomator2Options

# Base paths
FOLDER_NAME = "09_25__2025"
BASE_DIR = r"C:\Users\mailb\OneDrive\Desktop\Hsouna"
CSV_FILE = 'C:/Users/mailb/OneDrive/Desktop/Hsouna/DO_NOT_TOUCH.csv'
EMAIL_JSON_FILE = os.path.join(BASE_DIR, "email_variants.json")
NUMBER_JSON_FILE = os.path.join(BASE_DIR, "saudi_numbers.json")
# CSV files used by the web UI for statistics
ALL_CSV_PATH = os.path.join(BASE_DIR, "ALL.csv")
HOMMES_CSV_PATH = os.path.join(BASE_DIR, "HOMMES.csv")
FEMMES_CSV_PATH = os.path.join(BASE_DIR, "FEMMES.csv")

# Appium configuration
APPIUM_SERVER = "http://127.0.0.1:4723"
DEVICE_NAME = "DEF4C19312001213"
PLATFORM_VERSION = "9"
APP_PACKAGE = "com.moh.nusukapp"
APP_ACTIVITY = "com.app.nusuk.LoginRegistrationActivity"

# Additional configuration
PAYS = "egypt"
PAYS_UPPER = PAYS.lower()
TARGET_DATE = "18/09"
HIJRI_DAY = "22"
START_DATE = "02_08_2025"
DURATION_DAYS = 31

# CSV configuration
FIELDNAMES = [
    "id",
    "nom",
    "prenom",
    "date_de_naissance",
    "numero_visa",
    "email",
    "numero_tlf",
    "numero_passport",
    "type_voyage",
    "date_entree_madinah",
    "duree_jours",
    "have_a_compte",
    "CREATION",
    "RESERVATION",
    "CONFIRMATION",
    "date_reservation",
    "heure",
    "nationalite",
]

# Default PDF path
PDF_FILE = 'C:/Users/SBS/Desktop/Hsouna/_inbox/merged (4).pdf'
# Directory where confirmation screenshots will be stored
RAWDHA_DIR = os.path.join(BASE_DIR, FOLDER_NAME, "rawdha")
RESERVATION_DIR = os.path.join(BASE_DIR, FOLDER_NAME, "reservations")

def setup_driver():
    """Create and return a configured Appium driver."""
   
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.platform_version = PLATFORM_VERSION
    options.device_name = DEVICE_NAME
    options.app_package = APP_PACKAGE
    options.app_activity = APP_ACTIVITY
    options.automation_name = "uiautomator2"
    options.set_capability("autoGrantPermissions",True)
    return webdriver.Remote(APPIUM_SERVER, options=options)
ALL_IMPORT_CSV = r"C:/Users/SBS/Desktop/Hsouna\_inbox\latest_import.csv"
