import subprocess
from pathlib import Path
import json
from tqdm import tqdm
from converter import convert_videos
import os
from yt_dlp import YoutubeDL

SIZE_CHECK = False
ASK_BEFORE_DOWNLOAD = False
DOWNLOAD = True
CONVERT_VIDEOS = False

JSON_PATH = "yt_links.json"

DOWNLOAD_TEMP_PATH = Path("download_temp")
VIDEO_PATH = Path("videos")
CONVERT_TEMP_PATH = Path("converted_videos")

if not DOWNLOAD_TEMP_PATH.exists():
    DOWNLOAD_TEMP_PATH.mkdir()

if not VIDEO_PATH.exists():
    VIDEO_PATH.mkdir()

if not CONVERT_TEMP_PATH.exists():
    CONVERT_TEMP_PATH.mkdir()

COMMON_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,

    "format": "(bv*[height<=1080]+ba/b)[ext=mp4]/b",

    "concurrent_fragment_downloads": 5,

    "merge_output_format": "mp4"
}

def convert(input_path: str, output_path: str):
    convert_videos(input_path, output_path)


def move(src, dst, buffer_size=1024 * 1024):
    file_size = os.path.getsize(src)

    with open(src, "rb") as fsrc, open(dst, "wb") as fdst, \
            tqdm(total=file_size, unit="B", unit_scale=True, desc=os.path.basename(src)) as pbar:

        while True:
            buf = fsrc.read(buffer_size)
            if not buf:
                break
            fdst.write(buf)
            pbar.update(len(buf))

    os.remove(src)


def get_video_size_bytes(url):
    ydl_opts = {
        **COMMON_YDL_OPTS,
        "format": "bestvideo+bestaudio",
        "merge_output_format": "mp4",
        "skip_download": True,
        "print_to_file": {},
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    size = info.get("filesize") or info.get("filesize_approx") or 0
    return int(size)


def check_download(path: Path, filename: str):
    return (path / filename).exists()


def get_final_filename(url, output_folder):
    ydl_opts = {
        **COMMON_YDL_OPTS,
        "outtmpl": f"{output_folder}/%(title)s.%(ext)s",
        "skip_download": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)

    return Path(filename).name


def download_video_with_srt(url, output_folder="vids"):
    Path(output_folder).mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        **COMMON_YDL_OPTS,
        "format": "bestvideo+bestaudio",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "srt",
        "convertsubtitles": "srt",
        "outtmpl": f"{output_folder}/%(title)s.%(ext)s",
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except:
        return False


if __name__ == "__main__":
    with open(JSON_PATH) as f:
        youtube_videos = json.load(f)

    if SIZE_CHECK:
        total_size = 0

        for video in tqdm(youtube_videos, desc="Checking File Size"):
            size = get_video_size_bytes(video)
            total_size += size

        print(f"\nTotal size: {total_size / 1024 / 1024 / 1024:.2f} GB")

    if ASK_BEFORE_DOWNLOAD:
        input("Press any key to continue: ")

    if DOWNLOAD:
        for video in tqdm(youtube_videos, desc="Downloading Videos"):

            final_name = get_final_filename(video, str(VIDEO_PATH))

            if check_download(VIDEO_PATH, final_name):
                print(f"✅ Skipping (already exists): {final_name}")
                continue

            download_video_with_srt(video, str(DOWNLOAD_TEMP_PATH))

            move_files = []
            files = [f for f in DOWNLOAD_TEMP_PATH.iterdir() if f.is_file()]
            for file in files:
                move_files.append(file)

            if CONVERT_VIDEOS:
                convert(str(DOWNLOAD_TEMP_PATH), str(CONVERT_TEMP_PATH))
                files = [f for f in CONVERT_TEMP_PATH.iterdir() if f.is_file()]
                for file in files:
                    move_files.append(file)

            for file in tqdm(move_files, desc="Moving Files"):
                move(str(file), str(VIDEO_PATH / file.name))

    print("\nDone!")