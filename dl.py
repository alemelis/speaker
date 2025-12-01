import os

SAVEDIR = '/mnt/navidrome/music/'

with open('links.txt', 'r') as f:
    links = f.readlines()

for link in links:
    link = link.strip()
    os.system(f'yt-dlp -x -P {SAVEDIR} {link}')
