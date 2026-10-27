"""Create local folders and an unconnected profile without overwriting data."""
from channel_config import ROOT, CHANNELS, create_channel

def initialize():
    for name in ('credentials', 'backgrounds', 'stories', 'videos', 'narrations', 'output'):
        (ROOT / name).mkdir(exist_ok=True)
    if not (CHANNELS / 'main' / 'config.json').exists():
        create_channel('main', 'Main channel')
    print('Local workspace ready. No accounts connected or automation enabled.')

if __name__ == '__main__':
    initialize()
