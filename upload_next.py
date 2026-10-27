r"""Upload one unused batch video publicly, then rename it with _used.

Run: .venv\Scripts\python.exe upload_next.py
Preview without uploading: add --dry-run
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from channel_config import paths, load_channel, credentials_for, lock, SHARED, read_json

ROOT = Path(__file__).resolve().parent
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def select_video(folder, history, dry_run=False):
    manifest_path = folder / 'batch.json'
    if not manifest_path.exists():
        raise RuntimeError(f'Missing story title mapping: {manifest_path}')
    items = json.loads(manifest_path.read_text(encoding='utf-8'))
    for path in sorted(folder.glob('*.mp4')):
        if path.stem.endswith('_used'):
            continue
        digest = fingerprint(path)
        previous = history.get(digest)
        used = path.with_stem(path.stem + '_used')
        if previous:
            if previous['status'] == 'uploaded':
                if not dry_run:
                    if used.exists():
                        raise RuntimeError(f'Rename destination exists: {used.name}')
                    path.rename(used)
                print(f"Skipping already uploaded video: {path.name}")
                continue
            raise RuntimeError(
                f'Previous upload of {path.name} has an uncertain result. '
                'Check YouTube Studio and credentials/upload_history.json before retrying; '
                'stopped to prevent a duplicate.')
        item = next((row for row in items if row.get('video') == path.name), None)
        if not item or item.get('status') != 'complete':
            continue
        title = item['title'].strip()
        if not title or len(title) > 100 or any(char in title for char in '<>'):
            raise RuntimeError(f'Story title is invalid for YouTube (maximum 100 characters): {title!r}')
        if used.exists():
            raise RuntimeError(f'Rename destination exists: {used.name}')
        return path, used, digest, title, item
    return None


def authorize():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    token = ROOT / 'credentials/token.json'
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / 'credentials/client_secret.json'), SCOPES)
        creds = flow.run_local_server(port=0, access_type='offline', prompt='consent', timeout_seconds=300)
    token.write_text(creds.to_json(), encoding='utf-8')
    return creds


def run(folder, dry_run, channel='main'):
    config = load_channel(channel)
    ledger = paths(channel)['credentials'] / 'upload_history.json'
    history = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
    selected = select_video(folder, history, dry_run)
    if selected is None:
        print('No unused videos remain in this folder.')
        return
    path, used, digest, title, item = selected
    shared = read_json(SHARED / 'video_uploads.json', {})
    permissions = read_json(SHARED / 'cross_channel_permissions.json', {})
    allowed_channels = permissions.get(digest, {}).get('channels', [])
    previous_channel = shared.get(digest, {}).get('channel')
    approved_copy = channel in allowed_channels and previous_channel in allowed_channels
    if digest in shared and previous_channel != channel and not approved_copy:
        raise RuntimeError('This exact video was uploaded or claimed by another channel. Nothing uploaded.')
    if digest in shared and shared[digest].get('status') == 'uploading':
        raise RuntimeError('This video has an uncertain upload result. Check YouTube Studio before retrying.')
    if digest in shared and digest not in history and not approved_copy:
        raise RuntimeError('Shared upload record already exists. Check YouTube Studio before retrying.')
    usage = read_json(SHARED / 'story_usage.json', {})
    if item.get('story_hash') in usage and usage[item['story_hash']]['channel'] != channel and channel not in allowed_channels:
        raise RuntimeError('This story is assigned to another channel. Nothing uploaded.')
    print(f"Channel: {config['name']} ({config.get('youtube_channel_id') or 'not connected'})", flush=True)
    print(f'Video: {path.name}\nTitle: {title}\nVisibility: PUBLIC', flush=True)
    if dry_run:
        print(f'Dry run only. After a successful upload: {used.name}')
        return
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    credentials, channel_id = credentials_for(channel)
    youtube = build('youtube', 'v3', credentials=credentials)
    media = MediaFileUpload(str(path), mimetype='video/mp4', chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(
        part='snippet,status',
        body={
            'snippet': {'title': title, 'categoryId': '22',
                        'description': 'Narrated story with satisfying background visuals.'},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
        },
        media_body=media,
        notifySubscribers=False,
    )
    history[digest] = {'status': 'uploading', 'file': str(path), 'title': title}
    shared[digest] = {**history[digest], 'channel': channel, 'youtube_channel_id': channel_id}
    write_json(SHARED / 'video_uploads.json', shared)
    write_json(ledger, history)
    # If interrupted here, the uploading record blocks automatic duplicate retries.
    result = None
    try:
        while result is None:
            progress, result = request.next_chunk()
            if progress:
                print(f'Uploaded {progress.progress():.0%}', flush=True)
    finally:
        # Windows prevents renaming while MediaFileUpload's stream is open.
        media.stream().close()
        youtube.close()
    video_id = result['id']
    history[digest].update(status='uploaded', video_id=video_id,
                           youtube_channel_id=channel_id,
                           privacy=result.get('status', {}).get('privacyStatus'),
                           renamed_file=str(used))
    write_json(ledger, history)
    shared[digest] = {**history[digest], 'channel':channel}
    write_json(SHARED / 'video_uploads.json',shared)
    print(f"Uploaded: https://www.youtube.com/watch?v={video_id}", flush=True)
    try:
        path.rename(used)
    except OSError as exc:
        raise RuntimeError('Upload SUCCEEDED, but the local file could not be renamed. '
                           'Upload history will prevent re-uploading this video. '
                           f'Close any app using the file, then run again. Details: {exc}') from exc
    print(f'Renamed: {used.name}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    channel_paths=paths(args.channel)
    if args.folder is None:
        folders=sorted(p.parent for p in channel_paths['videos'].glob('*/batch.json'))
        args.folder=next((f for f in folders if any(not p.stem.endswith('_used') for p in f.glob('*.mp4'))), None)
        if args.folder is None:
            print('No unused videos remain.'); return
    if args.folder.resolve().parent != channel_paths['videos'].resolve():
        parser.error('Video folder must belong to the selected channel.')
    if not args.folder.is_dir():
        parser.error('Video folder does not exist')
    lock = channel_paths['credentials'] / 'upload_next.lock'
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise SystemExit('Another uploader may be running. Check before removing credentials/upload_next.lock.')
    try:
        with handle:
            handle.write(str(os.getpid()))
            handle.flush()
            with __import__('channel_config').lock('upload'):
                run(args.folder.resolve(), args.dry_run, args.channel)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Upload stopped: {exc}')
