r"""Generate one Kokoro narration and automatic word timestamps.

Run with .venv-tts\Scripts\python.exe narrate.py stories\1nspy0i.json
"""
import argparse
import json
import os
import re
from voice_selection import select_voice
from difflib import SequenceMatcher
from pathlib import Path
from bisect import bisect_left, bisect_right

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME', str(ROOT / '.model-cache' / 'huggingface'))
_PIPELINE = None
_ESPEAK_READY = False


def prepare_script(story, include_title=True):
    """Remove page boilerplate and exact duplicated passages, preserving original files."""
    raw = re.sub(r'(?im)^\s*read more\s*$', '', story['text'])
    paragraphs, seen, removed = [], set(), []
    for paragraph in re.split(r'\n\s*\n', raw):
        paragraph = clean_text(paragraph)
        key = ' '.join(re.findall(r"\w+", paragraph.casefold()))
        if not key:
            continue
        if len(key.split()) >= 8 and key in seen:
            removed.append({'type':'duplicate_paragraph','text':paragraph})
            continue
        seen.add(key)
        paragraphs.append(paragraph)
    text = ' '.join(paragraphs)
    sentences, seen_sentences = [], set()
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence_key = ' '.join(re.findall(r'\w+', sentence.casefold()))
        if len(sentence_key.split()) >= 8 and sentence_key in seen_sentences:
            removed.append({'type':'duplicate_sentence','text':sentence})
            continue
        seen_sentences.add(sentence_key)
        sentences.append(sentence)
    text = ' '.join(sentences)
    # Also catch a whole passage pasted twice without paragraph breaks.
    while True:
        tokens = list(re.finditer(r"\w+(?:['’\-]\w+)*", text))
        normalized = [t.group().casefold() for t in tokens]
        duplicate = None
        seeds = {}
        best_width = 0
        for second in range(max(0,len(tokens)-11)):
            seed = tuple(normalized[second:second+12])
            for index in seeds.get(seed, []):
                width = second-index
                if width < 12 or width <= best_width or second+width > len(tokens):
                    continue
                if normalized[index:second] == normalized[second:second+width]:
                    best_width = width
                    duplicate = (tokens[second].start(),
                                 tokens[second+width].start() if second+width<len(tokens) else len(text))
            seeds.setdefault(seed, []).append(second)
        if not duplicate:
            break
        start, end = duplicate
        removed.append({'type':'adjacent_duplicate_passage','text':text[start:end]})
        text = text[:start] + text[end:]
    text = clean_text(text)
    title = clean_text(story.get('title','')).rstrip('.!?')
    normalize = lambda s: ' '.join(re.findall(r"\w+",s.casefold()))
    title_key, body_key = normalize(title), normalize(text)
    title_already_present = bool(title_key and (body_key==title_key or body_key.startswith(title_key+' ')))
    opening = re.split(r'[.!?]', text, maxsplit=1)[0]
    hook_words = normalize(opening).replace("won t", "wont").split()
    title_words = title_key.replace("won t", "wont").split()
    if len(hook_words) >= 8 and title_words[:len(hook_words)] == hook_words:
        title_already_present = True
    if include_title and title and not title_already_present:
        text = title + '. ' + text
    return text, removed, title_already_present


def repetition_review(script):
    """Flag similar long sentences for review without silently rewriting the story."""
    sentences = re.split(r'(?<=[.!?])\s+', script)
    normalized = [' '.join(re.findall(r'\w+', s.casefold())) for s in sentences]
    findings = []
    for index, sentence in enumerate(normalized):
        if len(sentence.split()) < 12:
            continue
        for earlier in range(index):
            previous = normalized[earlier]
            if len(previous.split()) < 12 or min(len(previous),len(sentence))/max(len(previous),len(sentence)) < .85:
                continue
            if SequenceMatcher(None, previous, sentence, autojunk=False).ratio() >= .92:
                findings.append({'type':'similar_sentence','first':sentences[earlier],'second':sentences[index]})
                break
    return findings


def clean_text(text):
    text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def add_period_pauses(audio, words, sample_rate, seconds):
    """Insert silence after period tokens and shift subsequent caption timings."""
    import numpy as np
    pause_samples = round(seconds * sample_rate)
    if pause_samples <= 0:
        return audio, words, 0
    boundaries = sorted(set(
        min(len(audio), round(word['end'] * sample_rate))
        for word in words if word['word'].strip() == '.'
    ))
    pieces, cursor = [], 0
    for boundary in boundaries:
        pieces.extend((audio[cursor:boundary], np.zeros(pause_samples, dtype=audio.dtype)))
        cursor = boundary
    pieces.append(audio[cursor:])
    shifted = []
    for word in words:
        start = round(word['start'] * sample_rate)
        end = round(word['end'] * sample_rate)
        shifted.append({
            **word,
            'start': round((start + bisect_right(boundaries, start) * pause_samples) / sample_rate, 4),
            'end': round((end + bisect_left(boundaries, end) * pause_samples) / sample_rate, 4),
        })
    return np.concatenate(pieces), shifted, len(boundaries)


def main():
    global _PIPELINE, _ESPEAK_READY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('story', type=Path)
    parser.add_argument('--voice', default='af_heart')
    parser.add_argument('--speed', type=float, default=1.0)
    parser.add_argument('--body-only', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--period-pause', type=float, default=0.25,
                        help='Extra silence after periods, in seconds (default: 0.25)')
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error('speed must be positive')
    if args.period_pause < 0:
        parser.error('period-pause must be nonnegative')
    story = json.loads(args.story.read_text(encoding='utf-8-sig'))
    if not story.get('text', '').strip():
        parser.error('story has no text')
    script, removed_passages, title_already_present = prepare_script(story, not args.body_only)
    args.voice, voice_reason = select_voice(story, args.voice)
    output = args.output or ROOT / 'narrations' / args.story.stem / f'{args.voice}_{args.speed:g}_pause{args.period_pause:g}'
    output.mkdir(parents=True, exist_ok=True)
    review = repetition_review(script)
    (output/'cleanup.json').write_text(json.dumps({'removed_passages':removed_passages,'title_already_present':title_already_present,'review':review},ensure_ascii=False,indent=2),encoding='utf-8')
    if review:
        raise RuntimeError('Potential repeated sentences need review; see cleanup.json. Narration was not generated.')

    import numpy as np
    import soundfile as sf
    import torch
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    if not _ESPEAK_READY:
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        _ESPEAK_READY = True
    from kokoro import KPipeline

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    if _PIPELINE is None:
        _PIPELINE = KPipeline(lang_code=args.voice[0] if args.voice[0] in 'ab' else 'a', repo_id='hexgrad/Kokoro-82M', device='cpu')
    pipeline = _PIPELINE
    audio_parts, words, chunks = [], [], []
    offset = 0.0
    sample_rate = 24000
    for chunk_number, result in enumerate(pipeline(script, voice=args.voice, speed=args.speed), 1):
        audio = result.audio.detach().cpu().numpy().reshape(-1).copy()
        chunk_duration = len(audio) / sample_rate
        for token in result.tokens or []:
            start, end = token.start_ts, token.end_ts
            if start is None or end is None:
                if words and token.text.strip() and not re.search(r'\w', token.text):
                    words[-1]['word'] += token.text
                continue
            start = min(chunk_duration, max(0.0, float(start)))
            end = min(chunk_duration, max(start, float(end)))
            if end > start and token.text.strip():
                words.append({'word': token.text, 'start': round(offset + start, 4),
                              'end': round(offset + end, 4)})
        audio_parts.append(audio)
        chunks.append({'text':result.graphemes,'start':offset,'end':offset+chunk_duration})
        offset += chunk_duration
        print(f'Generated chunk {chunk_number}; {offset:.2f} seconds so far.', flush=True)
    if not audio_parts or not words:
        raise RuntimeError('Kokoro did not return audio and word timings')
    expected = re.findall(r'\w+', script.casefold())
    spoken = re.findall(r'\w+', ' '.join(c['text'] for c in chunks).casefold())
    if spoken != expected:
        (output/'chunks.json').write_text(json.dumps(chunks,ensure_ascii=False,indent=2),encoding='utf-8')
        raise RuntimeError('Narration chunk text differs from the script; stopped to avoid missing or repeated passages.')
    audio = np.concatenate(audio_parts)
    audio, words, pause_count = add_period_pauses(audio, words, sample_rate, args.period_pause)
    sf.write(output / 'narration.wav', audio, sample_rate, subtype='PCM_16')
    (output / 'script.txt').write_text(script, encoding='utf-8')
    (output / 'timings.json').write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'chunks.json').write_text(json.dumps(chunks,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata = {
        'story_file': str(args.story.resolve()), 'source_url': story.get('url'),
        'voice': args.voice, 'speed': args.speed, 'sample_rate': sample_rate,
        'voice_selection_reason': voice_reason,
        'duration_seconds': len(audio) / sample_rate,
        'word_count': len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", script)),
        'timestamp_count': len(words), 'includes_title': not args.body_only,
        'timing_source': 'Kokoro predicted token durations',
        'extra_period_pause_seconds': args.period_pause,
        'inserted_pause_count': pause_count,
        'removed_duplicate_passages':len(removed_passages),
    }
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2), flush=True)
    print(f'Saved narration to {output}', flush=True)


if __name__ == '__main__':
    main()
