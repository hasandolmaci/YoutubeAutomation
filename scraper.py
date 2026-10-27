r"""Save story text from Reddit Top of All Time after 5 automatic scrolls.

Run: .venv\Scripts\python.exe scraper.py
"""
from playwright.sync_api import expect, sync_playwright
from seleniumbase import sb_cdp
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from seleniumbase import sb_cdp
from playwright.sync_api import sync_playwright

sb = sb_cdp.Chrome(incognito=True)
endpoint_url = sb.get_endpoint_url()

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint_url)
        page = browser.contexts[0].pages[0]
        page.goto("https://www.reddit.com/r/stories/top/?t=all")
        time.sleep(2)
        # Complete any browser access checks manually before continuing.
        input("Once Reddit has loaded, press Enter to start automatic scrolling and collection...")
        page.locator("shreddit-post").first.wait_for(state="attached", timeout=30000)
        stories_dir = Path(__file__).resolve().parent / "stories"
        stories_dir.mkdir(exist_ok=True)

        # Keep snapshots as we scroll, including posts Reddit may later unload.
        max_scrolls = 5
        saved_ids = set()
        candidates_by_key = {}
        for scroll_number in range(max_scrolls + 1):
            loaded_posts = page.locator("shreddit-post").evaluate_all("""posts => posts.map(post => ({
            id: post.getAttribute('id'),
            title: post.getAttribute('post-title'),
            text: (post.querySelector('shreddit-post-text-body, [slot="text-body"], [id$="-post-rtjson-content"]')?.innerText || '').trim(),
            permalink: post.getAttribute('permalink') ||
                post.querySelector('a[slot="title"]')?.getAttribute('href')
            }))""")
            for candidate in loaded_posts:
                key = candidate["id"] or candidate["permalink"]
                if key:
                    candidates_by_key[key] = candidate
                # Save feed text immediately, before scrolling or opening detail tabs.
                permalink = candidate["permalink"] or ""
                if "/comments/" in permalink and candidate["text"] not in ("", "[removed]", "[deleted]"):
                    story_id = permalink.split("/comments/", 1)[1].split("/", 1)[0]
                    if story_id.isalnum():
                        destination = stories_dir / f"{story_id}.json"
                        if not destination.exists():
                            story = {
                                "id": story_id, "title": candidate["title"],
                                "text": candidate["text"],
                                "url": "https://www.reddit.com" + permalink if permalink.startswith("/") else permalink,
                                "text_source": "feed_preview",
                                "collected_at": datetime.now(timezone.utc).isoformat(),
                            }
                            destination.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
                            saved_ids.add(story_id)
                            print(f"Saved feed text for {story_id}", flush=True)
            print(f"Found {len(candidates_by_key)} posts; completed {scroll_number}/{max_scrolls} scrolls.", flush=True)
            if scroll_number == max_scrolls:
                break
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(7000)
        candidates = list(candidates_by_key.values())

        def read_body(post):
            for selector in (
                "shreddit-post-text-body",
                '[slot="text-body"]',
                '[id$="-post-rtjson-content"]',
                '.md',
            ):
                for element in post.locator(selector).all():
                    text = element.inner_text().strip()
                    if text and text not in ("[removed]", "[deleted]"):
                        return text
            return ""

        detail = browser.contexts[0].new_page()
        saved = 0
        seen = set()
        try:
            for candidate in candidates:
                if not candidate["permalink"]:
                    continue
                url = candidate["permalink"]
                if url.startswith("/"):
                    url = "https://www.reddit.com" + url
                # Only visit Reddit story links, never arbitrary post destinations.
                if not url.startswith("https://www.reddit.com/r/stories/comments/"):
                    continue
                story_id = url.split("/comments/", 1)[1].split("/", 1)[0]
                if not story_id.isalnum() or story_id in seen:
                    continue
                seen.add(story_id)
                try:
                    response = detail.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if response and response.status in (403, 429):
                        print(f"Reddit restricted access (HTTP {response.status}); stopping.")
                        break
                    post = detail.locator("shreddit-post").first
                    post.wait_for(state="attached", timeout=15000)
                    text = read_body(post)
                    if not text:
                        print(f"Skipped {story_id}: no story text found.")
                        continue
                    story = {
                        "id": story_id,
                        "title": candidate["title"] or post.get_attribute("post-title"),
                        "text": text,
                        "text_source": "post_page",
                        "url": url,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    }
                    destination = stories_dir / f"{story_id}.json"
                    destination.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
                    saved += 1
                    saved_ids.add(story_id)
                    print(f"Saved {story_id}")
                    time.sleep(2)
                except Exception as exc:
                    print(f"Could not read {story_id}: {exc}")
        finally:
            if not detail.is_closed():
                detail.close()
        print(f"Checked {len(candidates)} loaded posts; saved {len(saved_ids)} stories ({saved} full post texts) to {stories_dir}.")


except Exception as exc:
    print(f"Collection stopped: {exc}. Already saved story files are retained.")
finally:
    sb.quit()
