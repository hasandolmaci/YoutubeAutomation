
from concurrent.futures import ThreadPoolExecutor
from seleniumbase import sb_cdp
from playwright.sync_api import sync_playwright
import time


def run_task(worker_id, link):
    sb = None

    try:
        sb = sb_cdp.Chrome(incognito=True, headless=True, chromium_arg="--mute-audio")
        endpoint_url = sb.get_endpoint_url()

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint_url)
            page = browser.contexts[0].pages[0]

            page.goto(link, wait_until="domcontentloaded")

            button = page.get_by_role(
                "button",
                name="Reject all",
                exact=True
            )

            if button.count() > 0:
                button.click(timeout=30000)

            print(f"Worker {worker_id}: Opened {link}")
            time.sleep(100)

    except Exception as exc:
        print(f"Worker {worker_id}: Error: {exc}")

    finally:
        if sb is not None:
            sb.quit()
        print(f"Worker {worker_id}: Closed")


if __name__ == "__main__":
    link = "https://www.youtube.com/shorts/kGNd6LfdVho"

    with ThreadPoolExecutor(max_workers=20) as executor:
        list(executor.map(run_task, range(20), [link] * 20))
