"""Browser-upload safety tests: no Google login or real upload is performed."""
import json
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import browser_upload
import channel_config as channels
import upload_next

CHANNEL_ID = 'UC' + 'a' * 22
OTHER_ID = 'UC' + 'b' * 22
HAS_PLAYWRIGHT = (importlib.util.find_spec('playwright') is not None
                  and importlib.util.find_spec('seleniumbase') is not None)


class BrowserUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=channels.ROOT / 'output', prefix='browser_test_')
        self.root = Path(self.temp.name)
        self.patches = [patch.object(channels, 'ROOT', self.root),
                        patch.object(channels, 'CHANNELS', self.root / 'channels'),
                        patch.object(channels, 'SHARED', self.root / 'shared'),
                        patch.object(browser_upload, 'CHANNELS', self.root / 'channels'),
                        patch.object(upload_next, 'SHARED', self.root / 'shared')]
        for p in self.patches:
            p.start()
        self.config = channels.create_channel('main', 'Test channel')
        self.config.update(youtube_channel_id=CHANNEL_ID, upload_method='browser')
        channels.write_json(self.root / 'channels/main/config.json', self.config)
        (self.root / 'shared').mkdir()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def make_video(self):
        folder = self.root / 'videos/test'
        folder.mkdir(parents=True)
        file = folder / 'example.mp4'
        file.write_bytes(b'test-only media, never uploaded')
        channels.write_json(folder / 'batch.json', [{'video':file.name, 'title':'Test title', 'status':'complete'}])
        return folder, file

    def test_only_studio_https_channel_urls_are_accepted(self):
        self.assertEqual(browser_upload.studio_channel(f'https://studio.youtube.com/channel/{CHANNEL_ID}/videos'), CHANNEL_ID)
        for url in [f'https://studio.youtube.com.evil.example/channel/{CHANNEL_ID}',
                    f'http://studio.youtube.com/channel/{CHANNEL_ID}',
                    f'https://accounts.google.com/channel/{CHANNEL_ID}',
                    'https://studio.youtube.com/channel/invalid']:
            self.assertIsNone(browser_upload.studio_channel(url))

    def test_wrong_channel_stops_before_any_upload_or_receipt(self):
        page = MagicMock()
        page.url = f'https://studio.youtube.com/channel/{OTHER_ID}/videos'
        before = MagicMock()
        with self.assertRaisesRegex(RuntimeError, 'Wrong YouTube channel'):
            browser_upload.upload_in_studio(page, Path('never.mp4'), 'Example', CHANNEL_ID, before)
        page.get_by_role.assert_not_called()
        before.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_saved_state_is_encrypted_and_can_be_reused(self):
        state = {'cookies':[{'name':'test-session', 'value':'private-test-cookie'}], 'origins':[]}
        browser_upload.save_state('main', state)
        saved = browser_upload.state_path('main').read_text()
        self.assertNotIn('private-test-cookie', saved)
        self.assertEqual(browser_upload.load_state('main'), state)
        self.assertTrue(channels.channel_connected('main'))
        browser_upload.disconnect('main')
        self.assertIsNone(browser_upload.load_state('main'))
        self.assertFalse(channels.channel_connected('main'))

    def test_corrupt_session_has_safe_reconnect_message(self):
        channels.write_json(browser_upload.state_path('main'), {'format':'wrong', 'data':'secret-must-not-be-logged'})
        with self.assertRaisesRegex(RuntimeError, 'Reconnect') as error:
            browser_upload.load_state('main')
        self.assertNotIn('secret-must-not-be-logged', str(error.exception))

    @unittest.skipUnless(HAS_PLAYWRIGHT, 'Optional Playwright dependency not installed')
    def test_missing_session_never_starts_browser_during_upload(self):
        with patch('playwright.sync_api.sync_playwright') as launcher:
            with self.assertRaisesRegex(RuntimeError, 'Connect this channel'):
                with browser_upload.session('main'):
                    self.fail('Missing session was accepted')
            launcher.assert_not_called()

    def test_interactive_signin_keeps_browser_visible(self):
        with patch.object(browser_upload, 'load_state', return_value=None), patch.object(browser_upload, 'open_browser') as launch, patch.object(browser_upload, 'new_session_page') as new_page, patch.object(browser_upload, 'wait_for_studio') as wait:
            page, context = MagicMock(), MagicMock()
            new_page.return_value = (context, page)
            wait.return_value = (page, CHANNEL_ID)
            with browser_upload.session('main', interactive=True):
                pass
            launch.assert_called_once_with(headless=False)

    def test_session_window_replaces_only_launchers_blank_page(self):
        browser, startup_context = MagicMock(), MagicMock()
        blank, existing = MagicMock(), MagicMock()
        blank.url = 'about:blank'
        blank.is_closed.return_value = False
        existing.url = 'https://example.com/'
        startup_context.pages = [blank, existing]
        browser.contexts = [startup_context]
        state = {'cookies': [], 'origins': []}
        context, page = browser_upload.new_session_page(browser, state)
        blank.close.assert_called_once()
        existing.close.assert_not_called()
        page.close.assert_not_called()
        self.assertIs(context, browser.new_context.return_value)
        browser.new_context.assert_called_once_with(storage_state=state, locale='en-US')

    @unittest.skipUnless(HAS_PLAYWRIGHT, 'Optional Playwright dependency not installed')
    def test_saved_session_is_loaded_into_browser_without_forcing_login(self):
        state = {'cookies':[], 'origins':[]}
        with patch.object(browser_upload, 'load_state', return_value=state), patch('playwright.sync_api.sync_playwright') as launch, patch('seleniumbase.sb_cdp.Chrome') as chrome:
            browser = launch.return_value.__enter__.return_value.chromium.connect_over_cdp.return_value
            context = browser.new_context.return_value
            page = context.new_page.return_value
            context.pages = [page]
            page.url = f'https://studio.youtube.com/channel/{CHANNEL_ID}'
            page.is_closed.return_value = False
            page.locator.return_value.first.is_visible.return_value = True
            with browser_upload.session('main') as (_, _, actual):
                self.assertEqual(actual, CHANNEL_ID)
            browser.new_context.assert_called_once_with(storage_state=state, locale='en-US')
            chrome.assert_called_once_with(incognito=True, headless=True, chromium_arg='--mute-audio,--disable-features=Translate')
            launch.return_value.__enter__.return_value.chromium.launch.assert_not_called()
            browser.close.assert_called_once()
            chrome.return_value.quit.assert_called_once()

    @unittest.skipUnless(HAS_PLAYWRIGHT, 'Optional browser dependencies not installed')
    def test_failed_attachment_closes_selenium_and_exposes_actual_error(self):
        with patch.object(browser_upload, 'load_state', return_value={'cookies':[]}), patch('playwright.sync_api.sync_playwright') as launch, patch('seleniumbase.sb_cdp.Chrome') as chrome:
            launch.return_value.__enter__.return_value.chromium.connect_over_cdp.side_effect = ValueError('test attachment failure')
            with self.assertRaisesRegex(RuntimeError, 'ValueError.*test attachment failure'):
                with browser_upload.session('main'):
                    self.fail('Attachment unexpectedly succeeded')
            chrome.return_value.quit.assert_called_once()

    @unittest.skipUnless(HAS_PLAYWRIGHT, 'Optional browser dependencies not installed')
    def test_selenium_starts_before_playwright_event_loop(self):
        order = []
        selenium = MagicMock()
        playwright = MagicMock()
        with patch('seleniumbase.sb_cdp.Chrome', side_effect=lambda **kwargs: (order.append('chrome') or selenium)), patch('playwright.sync_api.sync_playwright') as launch:
            launch.return_value.__enter__.side_effect = lambda: (order.append('playwright') or playwright)
            with browser_upload.open_browser():
                self.assertEqual(order, ['chrome', 'playwright'])
            selenium.quit.assert_called_once()

    def test_expired_session_requires_reconnect(self):
        page = MagicMock()
        page.url = 'https://accounts.google.com/signin'
        with self.assertRaisesRegex(RuntimeError, 'expired'):
            browser_upload.wait_for_studio(page, CHANNEL_ID, timeout=0)

    def test_login_completion_in_popup_survives_original_tab_closing(self):
        original, popup = MagicMock(), MagicMock()
        original.is_closed.return_value = True
        popup.is_closed.return_value = False
        popup.url = f'https://studio.youtube.com/channel/{CHANNEL_ID}/dashboard'
        popup.locator.return_value.first.is_visible.return_value = True
        context = MagicMock()
        context.pages = [original, popup]
        actual_page, actual_id = browser_upload.wait_for_studio(original, CHANNEL_ID, context=context, return_page=True)
        self.assertIs(actual_page, popup)
        self.assertEqual(actual_id, CHANNEL_ID)
        original.wait_for_timeout.assert_not_called()

    def test_youtube_homepage_after_signin_continues_to_studio(self):
        page, context = MagicMock(), MagicMock()
        page.url = 'https://www.youtube.com/'
        page.is_closed.return_value = False
        page.locator.return_value.first.is_visible.return_value = True
        context.pages = [page]
        def navigate(*args, **kwargs):
            page.url = f'https://studio.youtube.com/channel/{CHANNEL_ID}/dashboard'
        page.goto.side_effect = navigate
        self.assertEqual(browser_upload.wait_for_studio(page, CHANNEL_ID, context=context), CHANNEL_ID)
        page.goto.assert_called_once()

    def test_failed_connection_keeps_error_for_dashboard_after_restart(self):
        with patch.object(browser_upload, 'session') as session:
            session.return_value.__enter__.side_effect = RuntimeError('Test sign-in did not finish')
            with self.assertRaisesRegex(RuntimeError, 'did not finish'):
                browser_upload.connect('main')
        status = channels.read_json(self.root / 'credentials/browser_connection_status.json')
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(status['error'], 'Test sign-in did not finish')
        self.assertFalse(browser_upload.state_path('main').exists())

    def test_processing_confirmation_requires_matching_video_and_waits_five_seconds(self):
        page, dialog, processing, success, radio, link = [MagicMock() for _ in range(6)]
        page.url = f'https://studio.youtube.com/channel/{CHANNEL_ID}'
        def locate(selector):
            if selector == 'ytcp-uploads-dialog': return dialog
            if selector == 'ytcp-video-share-dialog': return success
            if 'uploads-still-processing-dialog-title' in selector: return processing
            return MagicMock()
        page.locator.side_effect = locate
        dialog.locator.return_value = radio
        radio.get_attribute.return_value = 'true'
        radio.all.return_value = [link]
        link.get_attribute.return_value = 'https://youtube.com/shorts/abcdefghijk'
        dialog.get_attribute.return_value = 'abcdefghijk'
        success.is_visible.return_value = False
        processing.is_visible.return_value = True
        before = MagicMock()
        with patch.object(browser_upload.time, 'sleep') as sleep:
            self.assertEqual(browser_upload.upload_in_studio(page, Path('example.mp4'), 'Example', CHANNEL_ID, before), 'abcdefghijk')
            sleep.assert_called_once_with(5)
        before.assert_called_once()
        dialog.get_attribute.return_value = 'differentid'
        with patch.object(browser_upload.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'processing video identity'):
                browser_upload.upload_in_studio(page, Path('example.mp4'), 'Example', CHANNEL_ID, before)
            sleep.assert_not_called()

    def test_receipts_require_a_real_youtube_video_link(self):
        self.assertEqual(browser_upload.video_id_from_url('https://youtu.be/abcdefghijk'), 'abcdefghijk')
        self.assertIsNone(browser_upload.video_id_from_url('https://youtube.com.attacker.example/watch?v=abcdefghijk'))

    def test_browser_success_uses_shared_history_and_marks_file_used(self):
        folder, file = self.make_video()
        def publish(channel, video, title, before):
            before()
            receipt = channels.read_json(self.root / 'credentials/upload_history.json')
            self.assertEqual(next(iter(receipt.values()))['status'], 'uploading')
            return 'abcdefghijk', CHANNEL_ID
        with patch.object(browser_upload, 'upload', side_effect=publish), patch('googleapiclient.discovery.build') as api:
            upload_next.run(folder, False, 'main')
            api.assert_not_called()
        self.assertFalse(file.exists())
        self.assertTrue(file.with_stem('example_used').exists())
        record = next(iter(channels.read_json(self.root / 'credentials/upload_history.json').values()))
        self.assertEqual(record['status'], 'uploaded')
        self.assertEqual(record['upload_method'], 'browser')

    def test_interrupted_browser_upload_blocks_a_second_attempt(self):
        folder, file = self.make_video()
        def interrupted(channel, video, title, before):
            before()
            raise RuntimeError('Connection lost after file selection')
        with patch.object(browser_upload, 'upload', side_effect=interrupted) as publish:
            with self.assertRaisesRegex(RuntimeError, 'Connection lost'):
                upload_next.run(folder, False, 'main')
            with self.assertRaisesRegex(RuntimeError, 'uncertain result'):
                upload_next.run(folder, False, 'main')
            self.assertEqual(publish.call_count, 1)
        self.assertTrue(file.exists())

    def test_dry_run_does_not_open_browser_or_write_auth(self):
        folder, _ = self.make_video()
        with patch.object(browser_upload, 'upload') as upload:
            upload_next.run(folder, True, 'main')
            upload.assert_not_called()
        self.assertFalse(browser_upload.state_path('main').exists())
        self.assertFalse((self.root / 'credentials/upload_history.json').exists())


if __name__ == '__main__':
    unittest.main()
