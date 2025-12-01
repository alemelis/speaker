import streamlit as st
import subprocess
from pathlib import Path
import os

SAVEDIR = Path('/mnt/owntone/music/')

url = st.text_input(label="URL")
title = st.text_input(label="Title")
author = st.text_input(label="Author")
delay = st.number_input(label="Delay (s)", value=0)

if st.button("Run Command"):
    if not url:
        st.error("need the URL!")
        st.stop()

    if "&" in url:
        url = url.split("&")[0]

    st.info("Downloading...")
    placeholder = st.empty()  # this area will be updated live
    output = ""

    # Run the command and capture output as it happens
    savedir = SAVEDIR / author
    savedir.mkdir(parents=True, exist_ok=True)
    if title == "":
        title = '"%(title)s"'
    process = subprocess.Popen(
        ["yt-dlp", "-x", "--audio-format", "m4a", "-P", str(savedir), "-o", title, url],
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
        st.success("✅")
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
            st.success("✅ Command completed successfully!")
            os.system(f"mv /tmp/temp_audio.m4a {dst}")
        else:
            st.error(f"❌ Command failed with code {process.returncode}")
            st.stop()
