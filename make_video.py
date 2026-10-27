"""Render the approved sample narration with automatic phrase captions."""
import json
import argparse
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent


def ass_time(seconds):
    ticks = round(seconds * 100)
    return f'{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--caption-style', choices=['phrases', 'words'], default='phrases')
    parser.add_argument('--narration', type=Path, default=ROOT / 'narrations/1nspy0i/af_heart_1_pause0.25')
    parser.add_argument('--background', type=Path, default=ROOT / 'backgrounds/background_000.mp4')
    parser.add_argument('--destination', type=Path, default=ROOT / 'videos/1nspy0i')
    parser.add_argument('--name', default='story_short')
    args = parser.parse_args()
    narration = args.narration.resolve()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    words = json.loads((narration / 'timings.json').read_text(encoding='utf-8'))
    metadata = json.loads((narration / 'metadata.json').read_text(encoding='utf-8'))
    duration = metadata['duration_seconds']
    merged_words = []
    for word in words:
        if not re.search(r'\w', word['word']) and merged_words:
            merged_words[-1] = {**merged_words[-1], 'word': merged_words[-1]['word'] + word['word'], 'end': word['end']}
        else:
            merged_words.append(dict(word))
    phrases, current = [], []
    for word in merged_words:
        current.append(word)
        text = ' '.join(w['word'] for w in current)
        if len(current) >= 4 or len(text) >= 30 or re.search(r'[.!?]$', word['word']):
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)
    if args.caption_style == 'words':
        phrases = [[word] for word in merged_words]
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,110,150,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    if args.caption_style == 'words':
        header = header.replace(
            'Style: Default,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,110,150,0,1',
            'Style: Default,Arial Black,112,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,10,2,5,110,110,0,1')
    for phrase in phrases:
        start, end = phrase[0]['start'], phrase[-1]['end']
        text = ' '.join(w['word'] for w in phrase)
        text = text.replace('\\', '').replace('{', '').replace('}', '')
        tags = r'{\pos(540,960)\fscx92\fscy92\t(0,65,\fscx100\fscy100)}' if args.caption_style == 'words' else r'{\pos(520,1000)}'
        events.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{tags}{text}')
    suffix = '_yellow_words' if args.caption_style == 'words' else ''
    captions = destination / f'{args.name}_captions{suffix}.ass'
    captions.write_text(header + '\n'.join(events) + '\n', encoding='utf-8')
    output = destination / f'{args.name}{suffix}.mp4'
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
        '-stream_loop', '-1', '-i', str(args.background.resolve()),
        '-i', str(narration / 'narration.wav'),
        '-map', '0:v:0', '-map', '1:a:0', '-vf', f'ass={captions.name}',
        '-t', str(duration), '-r', '30', '-c:v', 'libx264', '-preset', 'fast',
        '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', '48000', '-movflags', '+faststart', str(output),
    ], cwd=destination, check=True)
    print(f'Saved {output}; {len(phrases)} caption phrases; {duration:.3f} seconds', flush=True)


if __name__ == '__main__':
    main()
