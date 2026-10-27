"""Fit narration duration while preserving pitch and shifting word timestamps."""
import argparse
import subprocess
import wave
from channel_config import read_json,write_json
from pathlib import Path
import imageio_ffmpeg

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    parser.add_argument('--seconds',type=float,default=179)
    args=parser.parse_args()
    metadata=read_json(args.folder/'metadata.json')
    factor=metadata['duration_seconds']/args.seconds
    if factor<=1:return
    if factor>1.2:raise RuntimeError('Refusing more than 20% additional speed.')
    original=args.folder/'narration.wav'
    target=args.folder/'narration_fitted.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',str(original),'-af',f'atempo={factor:.10f}','-ar','24000','-c:a','pcm_s16le',str(target)],check=True)
    with wave.open(str(target)) as audio:duration=audio.getnframes()/audio.getframerate()
    timings=read_json(args.folder/'timings.json')
    for word in timings:
        word['start']=round(min(duration,word['start']/factor),4)
        word['end']=round(min(duration,word['end']/factor),4)
    if any(w['end']<=w['start'] for w in timings):raise RuntimeError('Invalid fitted word timings')
    target.replace(original)
    metadata.update(duration_seconds=duration,post_speed_factor=factor)
    write_json(args.folder/'metadata.json',metadata)
    write_json(args.folder/'timings.json',timings)
    print(f'Fitted narration to {duration:.2f} seconds (speed adjustment {factor:.3f}x).',flush=True)

if __name__=='__main__':main()
