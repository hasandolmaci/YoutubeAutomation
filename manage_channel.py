"""Create or connect a channel profile. No uploads are performed."""
import argparse
from channel_config import create_channel, credentials_for, load_channel, upload_method
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['create','connect','disconnect-browser'])
parser.add_argument('channel')
parser.add_argument('--name')
parser.add_argument('--method', choices=['api','browser'])
parser.add_argument('--reconnect', action='store_true', help='Ignore saved browser state and sign in again.')
args=parser.parse_args()
try:
    if args.action=='create':
        config=create_channel(args.channel,args.name or args.channel)
        print(f"Created {config['name']}. Add complete story JSON files to channels/{args.channel}/stories.")
    elif args.action == 'disconnect-browser':
        from browser_upload import disconnect
        disconnect(args.channel)
    elif (args.method or upload_method(load_channel(args.channel))) == 'browser':
        from browser_upload import connect
        connect(args.channel, reconnect=args.reconnect)
    else:
        _, channel_id=credentials_for(args.channel,connect=True)
        print(f'Connected and verified YouTube channel: {channel_id}')
except Exception as exc: raise SystemExit(str(exc))
