import streamlit as st
import subprocess
from pathlib import Path
import os

SAVEDIR = Path('/mnt/owntone/music/')

playlist = st.checkbox(label="playlist", value=False)
url = st.text_input(label="URL")
if not playlist:
    title = st.text_input(label="Title")
artist = st.text_input(label="Artist")
album = st.text_input(label="Album")
delay = st.number_input(label="Delay (s)", value=0)



if st.button("Run Command"):
    if not url:
        st.error("need the URL!")
        st.stop()

    # Run the command and capture output as it happens
    savedir = SAVEDIR / artist
    dirname = artist
    playlist_flag = "--no-playlist"
    if playlist:
        dirname = f"{artist}-{album}"
        savedir = SAVEDIR / dirname
        playlist_flag = "--yes-playlist"
    savedir.mkdir(parents=True, exist_ok=True)
    if playlist:
        title = "%(playlist_index)02d-%(title)s"
    else:
        title = title if title else "%(title)s"
    metadata = [
        "--embed-metadata",
        "--embed-thumbnail",
    ]
    # 1. Use FFmpeg arguments to FORCE static values.
    # We use --postprocessor-args to tell FFmpeg exactly what to write.
    ffmpeg_args = []

    if artist:
        # Sanitize quotes just in case
        safe_artist = artist.replace('"', '\\"')
        ffmpeg_args.append(f'-metadata artist="{safe_artist}"')
        ffmpeg_args.append(f'-metadata album_artist="{safe_artist}"')

    if album:
        safe_album = album.replace('"', '\\"')
        ffmpeg_args.append(f'-metadata album="{safe_album}"')

    # Add the FFmpeg args if they exist
    if ffmpeg_args:
        # "Metadata:" tells yt-dlp to run this during the metadata step
        metadata.extend(["--postprocessor-args", f"Metadata:{' '.join(ffmpeg_args)}"])

    # 2. Handle Track Numbers (This is dynamic, so we still use parse-metadata)
    # playlist_index is calculated by yt-dlp, so we map it to track_number
    if playlist:
        metadata.extend(["--parse-metadata", "playlist_index:%(track_number)s"])
    else:
        # Optional: Force track 1 for single downloads if you want
        metadata.extend(["--parse-metadata", "1:%(track_number)s"])
    cmd = ["yt-dlp", playlist_flag, "-x", "--audio-format", "m4a", "-P", str(savedir), "-o", title, *metadata, url]
    st.info(" ".join(cmd))
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    placeholder = st.empty()  # this area will be updated live
    output = ""
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
