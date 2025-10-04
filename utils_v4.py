from appium.webdriver.common.appiumby import AppiumBy
import pandas as pd
import unicodedata
from config import APP_PACKAGE
from logutil import get_shared_logger
import re
from datetime import datetime

# -----------------------------------------------------------------------------
logger = get_shared_logger("reservation")
def has_previous_booking(driver) -> bool:
    needles = [
        "You recently visited Rawdah", 
        "récemment"
    ]
    for t in needles:
        try:
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{t}")')
            return True
        except Exception:
            pass
    return False
def has_previous_booking_before_365(driver) -> bool:
    needles = [
        "365"
    ]
    for t in needles:
        try:
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{t}")')
            return True
        except Exception:
            pass
    return False
def has_booking(driver) -> tuple[bool, str]:
    needles = [
        "Vous avez déjà une réservation existante pour",
        "You already have an existing booking for"
    ]
    for t in needles:
        try:
            element = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{t}")')
            full_text = element.text
            print(f"📅 Booking trouvé: {full_text}")

            # Extraire le jour et le mois pour créer une date complète (format: "09 Oct" -> "09/10/2025")
            try:
                # Chercher un nombre de 1 ou 2 chiffres suivi d'un espace et d'un mois abrégé
                match = re.search(r'(\d{1,2})\s+([A-Za-zÀ-ÿ\.]+)', full_text, re.IGNORECASE)
                if match:
                    day = match.group(1).zfill(2)
                    raw_month = match.group(2).strip().strip('.')
                    normalized = unicodedata.normalize('NFKD', raw_month).encode('ascii', 'ignore').decode('ascii').lower()

                    month_map = {
                        'jan': '01', 'janv': '01',
                        'feb': '02', 'fev': '02', 'febr': '02',
                        'mar': '03',
                        'apr': '04', 'avr': '04',
                        'may': '05', 'mai': '05',
                        'jun': '06', 'juin': '06',
                        'jul': '07', 'juil': '07',
                        'aug': '08', 'aou': '08', 'aout': '08',
                        'sep': '09', 'sept': '09',
                        'oct': '10',
                        'nov': '11',
                        'dec': '12',
                    }
                    month = None
                    for key in (normalized, normalized[:4], normalized[:3]):
                        if key in month_map:
                            month = month_map[key]
                            break
                    if not month:
                        print('📅 Format de date non reconnu')
                        return True, ''

                    current_year = str(datetime.now().year)
                    extracted_date = f"{day}/{month}/{current_year}"
                    print(f'📅 Date extraite et formatée: {extracted_date}')
                    return True, extracted_date
                else:
                    print('📅 Format de date non reconnu')
                    return True, ''
            except Exception as e:
                print(f"📅 Erreur lors de l'extraction de la date:")

        except Exception as e:
            pass

    print("📅 Aucun booking existant trouvé")
    return False, ""

# -----------------------------------------------------------------------------/
# Data helpers (runtime-scoped; NO module-level CSV/DATE)

def _load_df(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return df.reset_index(drop=True)

def _save_df(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False, encoding="utf-8")

def _set_df(df: pd.DataFrame, index: int, col: str, value: str) -> None:
    if col not in df.columns:
        df[col] = ""
    prev = df.at[index, col] if 0 <= index < len(df) else None
    df.at[index, col] = value
    logger.info("DF Update [row=%s, col=%s]: %r -> %r", index, col, prev, value)


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
