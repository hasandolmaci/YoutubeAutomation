"""Publish one queued video per channel at Windows sign-in."""
import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

from channel_config import ROOT, SHARED, CHANNELS, load_channel, paths, read_json, write_json, lock

def channel_ids():
    return [file.parent.name for file in sorted(CHANNELS.glob('*/config.json'))
            if load_channel(file.parent.name).get('youtube_channel_id')
            and (paths(file.parent.name)['credentials'] / 'channel_token.json').exists()]


def wait_for_network(timeout=600):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(('www.googleapis.com', 443), timeout=10):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(15)


def upload_channels(dry_run=False):
    failed = False
    for channel in channel_ids():
        logging.info('Starting channel: %s', channel)
        command = [sys.executable, '-u', str(ROOT / 'upload_next.py'), '--channel', channel]
        if dry_run:
            command.append('--dry-run')
        try:
            # Do not retry: a failed upload may already have reached YouTube.
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace',
                                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                    timeout=7200)
            logging.info('%s\n%s', channel, result.stdout.strip())
            if result.stderr:
                logging.warning('%s\n%s', channel, result.stderr.strip())
            if result.returncode:
                failed = True
                logging.error('Channel %s needs attention (exit %s).', channel, result.returncode)
        except (OSError, subprocess.TimeoutExpired):
            failed = True
            logging.exception('Channel %s stopped; check YouTube before retrying.', channel)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Preview without uploading.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--enable', action='store_true')
    mode.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    settings = SHARED / 'startup_settings.json'
    if args.enable or args.disable:
        write_json(settings, {'enabled': args.enable})
        print('Startup uploads ' + ('enabled.' if args.enable else 'disabled.'))
        return 0
    if not args.dry_run and not read_json(settings, {}).get('enabled', False):
        return 0
    SHARED.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(SHARED / 'startup_upload.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format='%(asctime)s %(levelname)s %(message)s')
    try:
        with lock('startup_upload'):
            logging.info('Startup run begins (dry_run=%s).', args.dry_run)
            if not args.dry_run and not wait_for_network():
                logging.error('No internet connection after 10 minutes. No videos uploaded.')
                return 1
            result = upload_channels(args.dry_run)
            logging.info('Startup run finished (exit %s).', result)
            return result
    except RuntimeError as exc:
        logging.error('%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
