"""Channel configuration, identity checks, and shared duplicate records."""
import contextlib
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNELS = ROOT / 'channels'
SHARED = ROOT / 'output' / 'shared'

def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def load_channel(channel='main'):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', channel):
        raise ValueError('Channel ID must use lowercase letters, numbers, hyphens or underscores.')
    config = read_json(CHANNELS / channel / 'config.json')
    if not config:
        raise ValueError(f'Unknown channel: {channel}')
    return config

def paths(channel='main'):
    config = load_channel(channel)
    # Keep existing files in place for the original channel.
    base = ROOT if channel == 'main' else CHANNELS / channel
    return {name: base / name for name in ('credentials','stories','videos','narrations','output')}

def create_channel(channel, name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', channel):
        raise ValueError('Use a short lowercase channel ID, e.g. wholesome-stories.')
    config_path = CHANNELS / channel / 'config.json'
    if config_path.exists():
        raise ValueError('That channel ID already exists.')
    config = {'id':channel, 'name':name.strip() or channel, 'youtube_channel_id':None, 'upload_method':'api',
              'youtube_channel_name':None, 'voice':'af_heart', 'speed':1.0,
              'period_pause':0.25, 'caption_style':'words', 'story_category':'General stories',
              'backgrounds':[], 'min_words':1, 'max_words':400,
              'schedule':{'enabled':False, 'timezone':'Europe/Berlin', 'times':['10:00','18:00']}}
    write_json(config_path, config)
    for folder in paths(channel).values(): folder.mkdir(parents=True, exist_ok=True)
    return config

def story_fingerprint(text):
    normalized = ' '.join(unicodedata.normalize('NFKC',text).casefold().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def upload_method(config):
    method = config.get('upload_method', 'api')
    if method not in ('api', 'browser'):
        raise ValueError('Upload method must be api or browser.')
    return method

def channel_connected(channel):
    config = load_channel(channel)
    name = 'youtube_browser_auth.json' if upload_method(config) == 'browser' else 'channel_token.json'
    return bool(config.get('youtube_channel_id')) and (paths(channel)['credentials'] / name).exists()

@contextlib.contextmanager
def lock(name):
    SHARED.mkdir(parents=True, exist_ok=True)
    target = SHARED / (name+'.lock')
    try: handle = target.open('x')
    except FileExistsError: raise RuntimeError(f'Another {name} job is running. Check before removing {target}.')
    try:
        with handle:
            handle.write(str(os.getpid())); handle.flush()
            yield
    finally: target.unlink(missing_ok=True)

def credentials_for(channel, connect=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    config = load_channel(channel)
    channel_paths = paths(channel)
    token = channel_paths['credentials'] / 'channel_token.json'
    scopes = ['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly']
    creds = Credentials.from_authorized_user_file(str(token),scopes) if token.exists() else None
    if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
    if connect:
        token.parent.mkdir(parents=True, exist_ok=True)
        client = channel_paths['credentials'] / 'client_secret.json'
        if not client.exists(): client = ROOT / 'credentials/client_secret.json'
        if not client.exists():
            raise RuntimeError('Add your own Desktop OAuth client JSON at credentials/client_secret.json first. See README.md.')
        flow = InstalledAppFlow.from_client_secrets_file(str(client), scopes)
        creds = flow.run_local_server(port=0,access_type='offline',prompt='consent select_account',timeout_seconds=300,
            authorization_prompt_message='Choose the Google / YouTube channel for this profile in your browser.',
            success_message='Channel authorization received. Return to the dashboard.')
    if not creds or not creds.valid:
        raise RuntimeError('Connect this channel in the dashboard before uploading.')
    from googleapiclient.discovery import build
    with build('youtube','v3',credentials=creds) as api:
        channels = api.channels().list(part='snippet',mine=True).execute().get('items',[])
    if len(channels)!=1: raise RuntimeError('Could not identify exactly one authorized YouTube channel.')
    actual = channels[0]
    expected = config.get('youtube_channel_id')
    if expected and actual['id'] != expected:
        raise RuntimeError(f"Wrong YouTube channel: expected {expected}, got {actual['id']}. Nothing uploaded.")
    if not expected and not connect: raise RuntimeError('Connect this profile to bind its YouTube channel first.')
    if connect:
        # Do not bind the same destination to multiple profiles by accident.
        for config_file in CHANNELS.glob('*/config.json'):
            other = read_json(config_file,{})
            if other.get('id')!=channel and other.get('youtube_channel_id')==actual['id']:
                raise RuntimeError(f"This YouTube channel is already assigned to {other['name']}.")
        config.update(youtube_channel_id=actual['id'],youtube_channel_name=actual['snippet']['title'])
        write_json(CHANNELS/channel/'config.json',config)
    write_json(token,json.loads(creds.to_json()))
    return creds, actual['id']
