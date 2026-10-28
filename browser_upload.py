"""Optional YouTube Studio uploader. Sign-in is always performed by the user."""
import base64
import contextlib
import ctypes
import json
import os
import re
import time
from urllib.parse import urlparse, parse_qs

from channel_config import CHANNELS, load_channel, paths, read_json, write_json, lock

STATE_FILE = 'youtube_browser_auth.json'
CHANNEL_PATTERN = re.compile(r'^/channel/(UC[A-Za-z0-9_-]{22})(?:/|$)')


def state_path(channel):
    return paths(channel)['credentials'] / STATE_FILE


def protect(data, decrypt=False):
    """Windows DPAPI: state is encrypted for the current Windows login."""
    if os.name != 'nt':
        raise RuntimeError('Saved browser sessions currently require Windows.')
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise RuntimeError('Cannot access the saved session with this Windows account. Reconnect the browser.')
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel.LocalFree(ctypes.cast(destination.data, ctypes.c_void_p))


def save_state(channel, state):
    encrypted = protect(json.dumps(state).encode('utf-8'))
    write_json(state_path(channel), {'format': 'windows-dpapi-v1',
                                   'data': base64.b64encode(encrypted).decode('ascii')})


def load_state(channel):
    try:
        value = read_json(state_path(channel))
        if value is None:
            return None
        if value.get('format') != 'windows-dpapi-v1':
            raise ValueError('Unknown session format')
        state = json.loads(protect(base64.b64decode(value['data'], validate=True), decrypt=True))
        if not isinstance(state, dict) or not isinstance(state.get('cookies'), list):
            raise ValueError('Invalid session')
        return state
    except Exception:
        raise RuntimeError('Saved browser session cannot be read. Use Reconnect to sign in again.') from None


def studio_channel(url):
    parsed = urlparse(url)
    match = CHANNEL_PATTERN.match(parsed.path)
    return match.group(1) if parsed.scheme == 'https' and parsed.hostname == 'studio.youtube.com' and match else None


def verify_channel(actual, expected):
    if not actual:
        raise RuntimeError('YouTube browser session expired or sign-in is incomplete. Connect the browser again.')
    if expected and actual != expected:
        raise RuntimeError(f'Wrong YouTube channel: expected {expected}, got {actual}. Nothing uploaded.')


def wait_for_studio(page, expected=None, timeout=30, context=None, return_page=False):
    context = context or page.context
    deadline = time.monotonic() + timeout
    redirected = set()
    empty_since = None
    while time.monotonic() < deadline:
        # Google can finish account setup in a popup and close the original tab.
        candidates = [candidate for candidate in context.pages if not candidate.is_closed()]
        if not candidates:
            empty_since = empty_since or time.monotonic()
            if time.monotonic() - empty_since > 2:
                raise RuntimeError('Sign-in window closed before YouTube Studio was verified. No new session saved.')
            time.sleep(.2)
            continue
        empty_since = None
        for candidate in candidates:
            try:
                if urlparse(candidate.url).hostname == 'studio.youtube.com' and candidate not in redirected:
                    proceed = candidate.locator('a[href^="https://studio.youtube.com/?"][href*="approve_browser_access=true"]')
                    if proceed.count() == 1 and proceed.is_visible():
                        print('Continuing through YouTube Studio browser compatibility notice…', flush=True)
                        redirected.add(candidate)
                        proceed.click()
                actual = studio_channel(candidate.url)
                if actual and (not expected or actual == expected):
                    if candidate.locator('ytcp-navigation-drawer').first.is_visible():
                        return (candidate, actual) if return_page else actual
                # Account setup can return to YouTube rather than Studio.
                if urlparse(candidate.url).hostname in ('www.youtube.com', 'youtube.com') and candidate not in redirected:
                    redirected.add(candidate)
                    candidate.goto('https://studio.youtube.com/?hl=en', wait_until='domcontentloaded', timeout=60_000)
            except Exception:
                if not candidate.is_closed():
                    raise
        active = next((candidate for candidate in candidates if not candidate.is_closed()), None)
        if active is not None:
            try:
                active.wait_for_timeout(500)
            except Exception:
                if not active.is_closed():
                    raise
        page = active or page
    verify_channel(studio_channel(page.url), expected)
    raise RuntimeError('YouTube Studio did not finish loading. Reconnect and try again.')


@contextlib.contextmanager
def open_browser(headless=False):
    """Start SeleniumBase before entering Playwright's synchronous event loop."""
    try:
        from playwright.sync_api import sync_playwright
        from seleniumbase import sb_cdp
    except ImportError:
        raise RuntimeError('Install browser upload support: .venv\\Scripts\\python.exe -m pip install -r requirements-browser.txt') from None
    sb = None
    try:
        try:
            sb = sb_cdp.Chrome(incognito=True, headless=headless, chromium_arg='--mute-audio,--disable-features=Translate')
            endpoint_url = sb.get_endpoint_url()
        except Exception as exc:
            raise RuntimeError(f'Could not start Chrome ({type(exc).__name__}): {exc}') from exc
        with sync_playwright() as playwright:
            browser = None
            try:
                try:
                    browser = playwright.chromium.connect_over_cdp(endpoint_url)
                except Exception as exc:
                    raise RuntimeError(f'Could not connect to Chrome ({type(exc).__name__}): {exc}') from exc
                yield browser
            finally:
                if browser is not None:
                    with contextlib.suppress(Exception):
                        browser.close()
    finally:
        if sb is not None:
            with contextlib.suppress(Exception):
                sb.quit()


def new_session_page(browser, saved=None):
    """Replace the launcher's empty window with the saved-session window."""
    startup_pages = [page for context in browser.contexts for page in context.pages
                     if page.url == 'about:blank']
    context = browser.new_context(storage_state=saved, locale='en-US')
    page = context.new_page()
    # Create the replacement first so closing the last startup tab cannot exit Chrome.
    for startup in startup_pages:
        if not startup.is_closed() and startup.url == 'about:blank':
            startup.close()
    return context, page


@contextlib.contextmanager
def session(channel, interactive=False, reconnect=False):
    saved = None if reconnect else load_state(channel)
    if saved is None and not interactive:
        raise RuntimeError('Connect this channel using Browser upload before uploading.')
    if not interactive and not load_channel(channel).get('youtube_channel_id'):
        raise RuntimeError('Connect the browser to bind its YouTube channel before uploading.')
    with lock('browser_' + channel):
        with open_browser(headless=not interactive) as browser:
            context, page = new_session_page(browser, saved)
            page.set_default_timeout(30_000)
            page.goto('https://studio.youtube.com/?hl=en', wait_until='domcontentloaded', timeout=60_000)
            expected = load_channel(channel).get('youtube_channel_id')
            if interactive and (not saved or studio_channel(page.url) != expected):
                print('Sign in yourself in Chrome and open the intended channel in YouTube Studio. '
                      'The session will be saved automatically. No password is read by this app.', flush=True)
            page, actual = wait_for_studio(page, expected, 600 if interactive else 30,
                                           context=context, return_page=True)
            verify_channel(actual, expected)
            yield page, context, actual


def connect(channel, reconnect=False):
    status_file = paths(channel)['credentials'] / 'browser_connection_status.json'
    write_json(status_file, {'status':'connecting', 'error':None})
    try:
        with session(channel, interactive=True, reconnect=reconnect) as (page, context, actual):
            config = load_channel(channel)
            for file in CHANNELS.glob('*/config.json'):
                other = read_json(file, {})
                if other.get('id') != channel and other.get('youtube_channel_id') == actual:
                    raise RuntimeError('That YouTube channel is already assigned to another profile.')
            print('YouTube Studio verified. Saving your encrypted session…', flush=True)
            save_state(channel, context.storage_state(indexed_db=True))
            config.update(youtube_channel_id=actual, upload_method='browser')
            write_json(CHANNELS / channel / 'config.json', config)
            write_json(status_file, {'status':'connected', 'error':None})
            print(f'Browser connected to {actual}. Saved session is encrypted locally.', flush=True)
    except Exception as exc:
        # Only the error is persisted, never cookies or browser storage contents.
        with contextlib.suppress(Exception):
            write_json(status_file, {'status':'failed', 'error':str(exc)})
        raise


def disconnect(channel):
    with lock('browser_' + channel):
        state_path(channel).unlink(missing_ok=True)
    print('Saved browser session deleted. API credentials were not changed.', flush=True)


def video_id_from_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('youtu.be', 'www.youtube.com', 'youtube.com'):
        return None
    value = parsed.path.strip('/') if parsed.hostname == 'youtu.be' else parse_qs(parsed.query).get('v', [''])[0]
    if parsed.path.startswith('/shorts/'):
        value = parsed.path.split('/')[2]
    return value if re.fullmatch(r'[A-Za-z0-9_-]{11}', value) else None


def upload_in_studio(page, file, title, expected, before_upload):
    """Use Studio component IDs and machine values instead of translated labels."""
    verify_channel(studio_channel(page.url), expected)
    page.locator('ytcp-header .ytcpAppHeaderCreateIcon').click()
    page.locator('tp-yt-paper-item[test-id="upload"]').click()
    chooser = page.locator('ytcp-uploads-dialog input[type="file"]')
    chooser.wait_for(state='attached')
    verify_channel(studio_channel(page.url), expected)
    # Selecting a file starts a real upload/draft. Record uncertainty before this.
    before_upload()
    chooser.set_input_files(str(file))
    dialog = page.locator('ytcp-uploads-dialog')
    dialog.locator('ytcp-social-suggestions-textbox#title-textarea #textbox').fill(title)
    not_kids = dialog.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]')
    not_kids.click()
    if not_kids.get_attribute('aria-checked') != 'true':
        raise RuntimeError('Could not verify audience selection. Check the draft in YouTube Studio.')
    for _ in range(3):
        dialog.locator('#next-button button').click(timeout=600_000)
    public = dialog.locator('tp-yt-paper-radio-button[name="PUBLIC"]')
    public.click()
    if public.get_attribute('aria-checked') != 'true':
        raise RuntimeError('Could not verify public visibility. Check the draft in YouTube Studio.')
    verify_channel(studio_channel(page.url), expected)
    print('Public visibility verified. Waiting for Publish to become available…', flush=True)
    dialog.locator('#done-button button').click(timeout=600_000)
    print('Publish clicked. Waiting for YouTube confirmation…', flush=True)
    # YouTube may acknowledge Publish with a processing notice instead of a
    # share dialog. Neither the click nor the pre-publish video URL is a receipt.
    success = page.locator('ytcp-video-share-dialog')
    processing = page.locator('[role="dialog"][aria-labelledby="uploads-still-processing-dialog-title"]')
    deadline = time.monotonic() + 600
    ids = set()
    while time.monotonic() < deadline:
        if success.is_visible():
            ids = {video_id_from_url(link.get_attribute('href') or '')
                   for link in success.locator('a[href]').all()}
            break
        if processing.is_visible():
            ids = {video_id_from_url(link.get_attribute('href') or '')
                   for link in dialog.locator('a[href]').all()}
            ids.discard(None)
            video_id = dialog.get_attribute('video-id')
            if not video_id or ids != {video_id}:
                raise RuntimeError('Could not verify the processing video identity. Check YouTube Studio before retrying.')
            print('YouTube accepted the upload for public publishing. Processing is still pending.', flush=True)
            break
        page.wait_for_timeout(500)
    ids.discard(None)
    if len(ids) != 1:
        raise RuntimeError('Publication result is uncertain. Check YouTube Studio before retrying.')
    print('YouTube confirmation received. Waiting 5 seconds before closing the browser…', flush=True)
    # Keep the browser alive briefly after a verified receipt; a delay alone is
    # never treated as evidence that publishing succeeded.
    time.sleep(5)
    return ids.pop()


def upload(channel, file, title, before_upload):
    with session(channel) as (page, context, actual):
        video_id = upload_in_studio(page, file, title, actual, before_upload)
        # Session refresh failure must not erase an already confirmed upload receipt.
        try:
            save_state(channel, context.storage_state(indexed_db=True))
        except Exception:
            print('Video published; saved session could not be refreshed. Reconnect before the next upload.', flush=True)
        return video_id, actual
