"""Produce ten complete story Shorts and mark successfully rendered stories used."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import narrate
from channel_config import paths, load_channel, lock, SHARED, read_json, write_json, story_fingerprint

ROOT = Path(__file__).resolve().parent
DEST = ROOT / 'videos' / 'batch_001'
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--channel',default='main')
    parser.add_argument('--count',type=int,default=10)
    parser.add_argument('--batch',help='Existing batch name to resume')
    parser.add_argument('--max-words',type=int,help='Override the word limit for this batch only')
    args=parser.parse_args()
    if not 1<=args.count<=100: parser.error('count must be between 1 and 100')
    config=load_channel(args.channel)
    if args.max_words is not None:
        if not config['min_words']<=args.max_words<=2000:parser.error('Invalid max-words override')
        config['max_words']=args.max_words
    channel_paths=paths(args.channel)
    from datetime import datetime,timezone
    batch=args.batch or ('batch_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',batch): parser.error('Invalid batch name')
    DEST=channel_paths['videos']/batch
    usage=read_json(SHARED/'story_usage.json',{})
    backgrounds=[ROOT/'backgrounds'/name for name in config['backgrounds']] if config['backgrounds'] else sorted((ROOT/'backgrounds').glob('*.mp4'))
    if not backgrounds or any(not p.is_file() or p.resolve().parent!=(ROOT/'backgrounds').resolve() for p in backgrounds):
        raise RuntimeError('No valid background clips selected')
    DEST.mkdir(parents=True, exist_ok=True)
    plan_path = DEST / 'batch.json'
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        config=read_json(DEST/'settings.json',config)
    else:
        candidates = []
        for path in channel_paths['stories'].glob('*.json'):
            story = json.loads(path.read_text(encoding='utf-8-sig'))
            if path.stem.endswith('_used'):
                continue
            if story.get('text_source') != 'post_page' or not story.get('text', '').strip():
                continue
            title=story.get('title','').strip()
            if not title or len(title)>100 or any(c in title for c in '<>'):
                continue
            count = len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", story.get('title', '') + ' ' + story['text']))
            fingerprint=story_fingerprint(story['text'])
            story_id=story.get('id',path.stem)
            already_used=any(row.get('story_id')==story_id for row in usage.values())
            if config['min_words'] <= count <= config['max_words'] and fingerprint not in usage and not already_used and all(story_fingerprint(row[2]['text'])!=fingerprint for row in candidates):
                candidates.append((count, path.name, story))
        selected = sorted(candidates, key=lambda item: (item[0], item[1]))[:args.count]
        if len(selected) < args.count:
            raise RuntimeError(f'Only {len(selected)} eligible complete, unused stories; requested {args.count}. Add stories or lower the count.')
        plan = [{'story': name, 'title': story['title'], 'words': count,
                 'background': backgrounds[i % len(backgrounds)].name, 'story_hash':story_fingerprint(story['text']),
                 'name': f'{i + 1:02d}_{Path(name).stem}', 'status': 'pending'}
                for i, (count, name, story) in enumerate(selected)]
        write_json(plan_path,plan)
        write_json(DEST/'settings.json',config)

    for item in plan:
        source=channel_paths['stories']/item['story']
        if 'story_hash' not in item:
            original=source if source.exists() else source.with_stem(source.stem+'_used')
            item['story_hash']=story_fingerprint(read_json(original)['text'])
        previous=usage.get(item['story_hash'])
        if previous and previous['channel']!=args.channel:
            raise RuntimeError('A story in this batch belongs to another channel.')
        if previous and previous.get('batch') not in (None,batch):
            raise RuntimeError('A story in this batch belongs to another batch.')
        usage[item['story_hash']]={'channel':args.channel,'batch':batch,'status':'complete' if item['status']=='complete' else 'reserved','story_id':Path(item['story']).stem}
    write_json(plan_path,plan)
    write_json(SHARED/'story_usage.json',usage)

    for item in plan:
        source = channel_paths['stories'] / item['story']
        used = source.with_stem(source.stem + '_used')
        output = DEST / (item['name'] + ('_yellow_words' if config['caption_style']=='words' else '') + '.mp4')
        if item['status'] == 'complete' and output.exists():
            if source.exists() and not used.exists():
                source.rename(used)
            continue
        print(f"Starting {item['name']}: {item['words']} words", flush=True)
        narration = channel_paths['narrations'] / source.stem / batch
        sys.argv = ['narrate.py', str(source), '--output', str(narration), '--voice',config['voice'],'--speed',str(config['speed']),'--period-pause',str(config['period_pause'])]
        narrate.main()
        metadata=read_json(narration/'metadata.json')
        # Keep every output below the Shorts duration limit without cutting the story.
        if metadata['duration_seconds']>179:
            factor=metadata['duration_seconds']/179
            if factor>1.2:raise RuntimeError('Narration needs editorial shortening; refusing excessive speed-up.')
            subprocess.run([str(PYTHON),str(ROOT/'fit_narration.py'),str(narration),'--seconds','179'],check=True)
        subprocess.run([
            str(PYTHON), str(ROOT / 'make_video.py'), '--caption-style', config['caption_style'],
            '--narration', str(narration), '--background', str(ROOT / 'backgrounds' / item['background']),
            '--destination', str(DEST), '--name', item['name'],
        ], check=True)
        # Fully decode each finished file before marking its source used.
        validation = subprocess.run([
            str(PYTHON), '-c',
            "import subprocess,sys,imageio_ffmpeg; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-xerror','-i',sys.argv[1],'-f','null','-'],check=True)",
            str(output),
        ], check=True)
        metadata = json.loads((narration / 'metadata.json').read_text(encoding='utf-8'))
        item.update(status='complete', video=output.name,
                    duration_seconds=metadata['duration_seconds'], used_story=used.name)
        # Save completion before renaming, so interrupted runs can recover.
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        if used.exists():
            raise RuntimeError(f'Used story destination already exists: {used.name}')
        source.rename(used)
        usage[item['story_hash']].update(status='complete')
        write_json(SHARED/'story_usage.json',usage)
        print(f"Completed {item['name']}; marked {used.name}", flush=True)
    print(f'Batch complete: {len(plan)} videos for {config["name"]}.', flush=True)


if __name__ == '__main__':
    with lock('production'):
        main()
