import os
from appium import webdriver
from appium.options.android import UiAutomator2Options

# Base paths
FOLDER_NAME = "193_15_09"
BASE_DIR = "C:/Users/SBS/Desktop/Hsouna"
CSV_FILE = os.path.join(BASE_DIR, FOLDER_NAME, "informations.csv")
EMAIL_JSON_FILE = os.path.join(BASE_DIR, "email_variants.json")
NUMBER_JSON_FILE = os.path.join(BASE_DIR, "saudi_numbers.json")

# Appium configuration
APPIUM_SERVER = "http://127.0.0.1:4723"
DEVICE_NAME = "DEF4C19312001213"
PLATFORM_VERSION = "9"
APP_PACKAGE = "com.moh.nusukapp"
APP_ACTIVITY = "com.app.nusuk.LoginRegistrationActivity"

# Additional configuration
PAYS = "egypt"
PAYS_UPPER = PAYS.lower()
TARGET_DATE = "17/09"
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
PDF_FILE = os.path.join(BASE_DIR, FOLDER_NAME, "merged_3.pdf")
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
    return webdriver.Remote(APPIUM_SERVER, options=options)