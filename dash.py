import streamlit as st
import subprocess
from pathlib import Path
import os

SAVEDIR = Path('/mnt/owntone/music/')

url = st.text_input(label="URL")
title = st.text_input(label="Title")
author = st.text_input(label="Author")
album = st.text_input(label="Album")
delay = st.number_input(label="Delay (s)", value=0)

playlist = st.checkbox(label="playlist", value=False)

if st.button("Run Command"):
    if not url:
        st.error("need the URL!")
        st.stop()

    st.info("Downloading...")
    placeholder = st.empty()  # this area will be updated live
    output = ""

    # Run the command and capture output as it happens
    savedir = SAVEDIR / author
    dirname = author
    playlist_flag = "--no-playlist"
    if playlist:
        dirname = f"{author}-{album}"
        savedir = SAVEDIR / dirname
        playlist_flag = "--yes-playlist"
    savedir.mkdir(parents=True, exist_ok=True)
    if title == "":
        if playlist:
            title = '"%(playlist_index)02d-%(title)s"'
        else:
            title = '"%(title)s"'
    cmd = ["yt-dlp", playlist_flag, "-x", "--audio-format", "m4a", "-P", str(savedir), "-o", title, url]
    st.text(" ".join(cmd))
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    dst = ""
    for line in process.stdout:
        output += line
        if line.startswith("[ExtractAudio] Destination:"):
            dst = Path(line.split(":")[1].strip())
        elif line.startswith("[ExtractAudio] Not converting audio"):
            dst = Path(line.split(';')[0].split()[-1].strip())
        placeholder.text(output)  # update the text live

    process.wait()  # wait for process to finish

    if process.returncode == 0:
        placeholder.text("")
        st.success("✅")
        os.system(f"ls {savedir}/*.m4a > {savedir}/{dirname}.m3u")
    else:
        st.error(f"Failed with code: {process.returncode}")
        st.stop()


    if delay != 0:
        st.info("Trimming...")
        st.text(["ffmpeg", "-y", "-i", str(dst), "-ss", str(delay), "-c", "copy", "/tmp/temp_audio.m4a"])
        process2 = subprocess.Popen(
            ["ffmpeg", "-y", "-i", str(dst), "-ss", str(delay), "-c", "copy", "/tmp/temp_audio.m4a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in process2.stdout:
            placeholder.text(output)

        process2.wait()

        if process2.returncode == 0:
            placeholder.text("")
            st.success("✅ Command completed successfully!")
            os.system(f"mv /tmp/temp_audio.m4a {dst}")
            os.system(f"ls {savedir}/*.m4a > {savedir}/{dirname}.m3u")
        else:
            st.error(f"❌ Command failed with code {process.returncode}")
            st.stop()
