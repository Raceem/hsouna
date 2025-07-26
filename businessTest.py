from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    iphone = p.devices["iPhone 13"]
    browser = p.webkit.launch(headless=False)
    context = browser.new_context(**iphone)
    page = context.new_page()
    page.goto("https://services.nusuk.sa/nusuk-svc/reservation/rwda-select")
    print(page.title())
    browser.close()
