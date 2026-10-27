"""Create or connect a channel profile. No uploads are performed."""
import argparse
from channel_config import create_channel, credentials_for
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['create','connect'])
parser.add_argument('channel')
parser.add_argument('--name')
args=parser.parse_args()
try:
    if args.action=='create':
        config=create_channel(args.channel,args.name or args.channel)
        print(f"Created {config['name']}. Add complete story JSON files to channels/{args.channel}/stories.")
    else:
        _, channel_id=credentials_for(args.channel,connect=True)
        print(f'Connected and verified YouTube channel: {channel_id}')
except Exception as exc: raise SystemExit(str(exc))
