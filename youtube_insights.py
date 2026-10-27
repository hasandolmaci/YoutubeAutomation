"""Fetch YouTube statistics; --connect opens read-only authorization."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from channel_config import paths, credentials_for

ROOT = Path(__file__).resolve().parent
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--channel',default='main')
    args = parser.parse_args()
    channel_paths=paths(args.channel)
    token = channel_paths['credentials'] / 'insights_token.json'
    combined=channel_paths['credentials'] / 'channel_token.json'
    if combined.exists(): token=combined
    credentials = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if not args.connect:
            raise RuntimeError('Connect insights to grant read-only YouTube access.')
        flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / 'credentials/client_secret.json'), SCOPES)
        credentials = flow.run_local_server(port=0, access_type='offline', prompt='consent', timeout_seconds=300,
            authorization_prompt_message='Complete read-only authorization in your browser.',
            success_message='Insights connected. You can close this tab.')
    if not combined.exists(): token.write_text(credentials.to_json(), encoding='utf-8')
    history_file=channel_paths['credentials'] / 'upload_history.json'
    history = json.loads(history_file.read_text(encoding='utf-8')) if history_file.exists() else {}
    ids = sorted({row['video_id'] for row in history.values() if row.get('status')=='uploaded' and row.get('video_id')})
    videos = {}
    with build('youtube', 'v3', credentials=credentials) as youtube:
        for start in range(0, len(ids), 50):
            response = youtube.videos().list(part='statistics', id=','.join(ids[start:start+50])).execute()
            for video in response.get('items', []):
                stats = video.get('statistics', {})
                videos[video['id']] = {key: int(stats[key]) if key in stats else None
                    for key in ('viewCount','likeCount','commentCount')}
    output = channel_paths['output'] / 'youtube_insights.json'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps({'updatedAt':datetime.now(timezone.utc).isoformat(), 'videos':videos}, indent=2), encoding='utf-8')
    os.replace(temporary, output)
    print(f'Updated insights for {len(videos)} videos.')

if __name__ == '__main__':
    try: main()
    except Exception as exc: raise SystemExit(str(exc))
