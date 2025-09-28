# probe_find_digit.py
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
import time, re

APPIUM_SERVER = "http://127.0.0.1:4726"    # pick the server for THIS phone
UDID = "DEF4C19312001213"                  # the phone on that server
DAY = "10"

def _parse_bounds(bstr: str):
    try:
        pts = re.findall(r"\[(\d+),(\d+)\]", bstr)
        (x1, y1), (x2, y2) = [(int(a), int(b)) for (a, b) in pts]
        w, h = x2 - x1, y2 - y1
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "w": w, "h": h,
                "cx": x1 + w // 2, "cy": y1 + h // 2}
    except Exception:
        return None

def _area(b): return max(0, b["x2"] - b["x1"]) * max(0, b["y2"] - b["y1"])

def _find_big_digit(driver, text: str):
    try:
        cal = driver.find_element(AppiumBy.ID, "com.moh.nusukapp:id/composeableView")
        candidates = cal.find_elements(AppiumBy.XPATH, f".//android.widget.TextView[@text='{text}']")
    except Exception:
        candidates = driver.find_elements(AppiumBy.XPATH, f"//android.widget.TextView[@text='{text}']")

    best = best_bounds = None
    best_area = -1
    print(f"\nFound {len(candidates)} candidates for text='{text}':")

    for i, el in enumerate(candidates):
        try:
            disp = el.is_displayed()
        except Exception:
            disp = True
        b = _parse_bounds(el.get_attribute("bounds"))
        if not b:
            continue

        a = _area(b)
        print(f"  #{i}: displayed={disp} bounds={b} area={a}")  # 👈 print area too

        if not disp:
            continue
        if a >= best_area:
            best, best_bounds, best_area = el, b, a

    print(f"===> Best area picked: {best_area}\n")  # 👈 also print which one was chosen
    return best, best_bounds

caps = {
    "platformName": "Android",
    "appium:automationName": "UiAutomator2",
    "appium:udid": UDID,
    "appium:noReset": True,
    "appium:autoLaunch": False,        # don't relaunch app
    "appium:newCommandTimeout": 3600
}

options = UiAutomator2Options().load_capabilities(caps)
driver = webdriver.Remote(APPIUM_SERVER, options=options)   # <-- correct

time.sleep(1)  # app should already be open on the calendar
el, bounds = _find_big_digit(driver, DAY)
print("\n=== RESULT ===")
print("Element:", el)
print("Bounds :", bounds)
# driver.quit()  # keep session if you want to run again
