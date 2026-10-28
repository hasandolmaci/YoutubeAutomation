"""Publish from each enabled channel's queue at its configured local times.

Run manually to enable the worker. It must remain running; missed times are not replayed.
"""
import argparse
import subprocess
import time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from channel_config import ROOT,CHANNELS,SHARED,load_channel,paths,read_json,write_json,lock,channel_connected

def tick(dry_run=False, now=None):
    now=now or datetime.now(timezone.utc)
    ledger=read_json(SHARED/'schedule_runs.json',{})
    for file in sorted(CHANNELS.glob('*/config.json')):
        config=load_channel(file.parent.name)
        schedule=config['schedule']
        if not schedule['enabled']:continue
        local=now.astimezone(ZoneInfo(schedule['timezone']))
        slot=local.strftime('%H:%M')
        key=f"{config['id']}:{local.date()}:{slot}"
        if slot not in schedule['times'] or key in ledger:continue
        if dry_run:
            print(f"Due: {config['name']} at {slot} ({schedule['timezone']})",flush=True);continue
        if not channel_connected(config['id']):
            print(f"Not connected: {config['name']}",flush=True);continue
        if (SHARED/'upload.lock').exists():continue
        ledger[key]={'status':'started','started_at':now.isoformat()}
        write_json(SHARED/'schedule_runs.json',ledger)
        result=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'upload_next.py'),'--channel',config['id']],cwd=ROOT)
        ledger[key]['status']='finished' if result.returncode==0 else 'needs_attention'
        write_json(SHARED/'schedule_runs.json',ledger)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:
        with lock('scheduler'):
            while True:
                tick(args.dry_run)
                if args.once:break
                time.sleep(20)
    except KeyboardInterrupt:print('Scheduler stopped.')
