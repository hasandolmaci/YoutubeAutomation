"""Verify release privacy defaults without authorizing accounts or uploading."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import channel_config
import startup_upload


class ReleaseTests(unittest.TestCase):
    def test_new_profile_has_no_connection_or_enabled_schedule(self):
        with tempfile.TemporaryDirectory(dir=channel_config.ROOT / 'output') as directory:
            root = Path(directory)
            with patch.object(channel_config, 'ROOT', root), patch.object(channel_config, 'CHANNELS', root / 'channels'):
                profile = channel_config.create_channel('main', 'Main channel')
                self.assertIsNone(profile['youtube_channel_id'])
                self.assertFalse(profile['schedule']['enabled'])

    def test_startup_disabled_by_default(self):
        with tempfile.TemporaryDirectory(dir=channel_config.ROOT / 'output') as directory:
            with patch.object(startup_upload, 'SHARED', Path(directory)), patch.object(sys, 'argv', ['startup_upload.py']), patch.object(startup_upload, 'upload_channels') as upload, patch.object(startup_upload, 'wait_for_network') as network:
                self.assertEqual(startup_upload.main(), 0)
                upload.assert_not_called()
                network.assert_not_called()

    def test_startup_discovers_users_connected_profiles(self):
        with tempfile.TemporaryDirectory(dir=channel_config.ROOT / 'output') as directory:
            root = Path(directory)
            with patch.object(channel_config, 'ROOT', root), patch.object(channel_config, 'CHANNELS', root / 'channels'), patch.object(startup_upload, 'CHANNELS', root / 'channels'):
                channel_config.create_channel('main', 'Main')
                profile = channel_config.create_channel('custom', 'Custom')
                profile['youtube_channel_id'] = 'example-channel-id'
                channel_config.write_json(root / 'channels/custom/config.json', profile)
                (root / 'channels/custom/credentials/channel_token.json').write_text('{}')
                self.assertEqual(startup_upload.channel_ids(), ['custom'])

    def test_failed_upload_is_not_retried_and_other_profile_is_attempted(self):
        with patch.object(startup_upload, 'channel_ids', return_value=['first', 'second']), patch.object(startup_upload.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('uploader', 7200), SimpleNamespace(returncode=0, stdout='', stderr='')]) as run:
            self.assertEqual(startup_upload.upload_channels(), 1)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], 'second')


if __name__ == '__main__':
    unittest.main()
