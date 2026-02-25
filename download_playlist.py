import random
import subprocess
import json
from tqdm import tqdm
from pathlib import Path
from download_v2 import get_video_size_bytes, convert, move, download_video_with_srt
import requests
from yt_dlp import YoutubeDL

SIZE_CHECK = False
ASK_BEFORE_DOWNLOAD = False
DOWNLOAD = True
CONVERT_VIDEOS = True

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLYUI88BNN3JK_0HGANZP914caQLN2Sy56"

DOWNLOAD_TEMP_PATH = Path("download_temp")
VIDEO_PATH = Path("videos")
CONVERT_TEMP_PATH = Path("converted_videos")

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm"}
SUB_EXTS = {".srt", ".vtt", ".ass"}

if not DOWNLOAD_TEMP_PATH.exists():
    DOWNLOAD_TEMP_PATH.mkdir()

if not VIDEO_PATH.exists():
    VIDEO_PATH.mkdir()

Path(VIDEO_PATH / "Season 01").mkdir(exist_ok=True)

if not CONVERT_TEMP_PATH.exists():
    CONVERT_TEMP_PATH.mkdir()


COMMON_YDL_OPTS = {
    "quiet": False,
    "no_warnings": False,

    "format": "bv*+ba/b",

    "concurrent_fragment_downloads": 5,

    "merge_output_format": "mp4"
}


def get_index_from_title(title, videos):
    for index, video in enumerate(videos):
        if title == video["title"]:
            return index
    return None


def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def generate_fanart(video_path, output_path):
    duration = get_video_duration(video_path)
    timestamp = random.uniform(duration * 0.1, duration * 0.9)

    cmd = [
        "ffmpeg", "-ss", str(timestamp), "-i", video_path,
        "-vframes", "1",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
        "-y", output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate_poster(video_path, output_path):
    duration = get_video_duration(video_path)
    timestamp = random.uniform(duration * 0.2, duration * 0.8)

    cmd = [
        "ffmpeg", "-ss", str(timestamp), "-i", video_path,
        "-vframes", "1",
        "-vf", "scale=1000:1500:force_original_aspect_ratio=increase,crop=1000:1500",
        "-y", output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate_multiple_art(video_paths, show_folder, poster_count=3, fanart_count=3):
    show_folder = Path(show_folder)

    index_poster = 1
    index_fanart = 1

    for _ in range(1, poster_count + 1):
        current_art_video = random.choice(video_paths)
        name = "poster.jpg" if index_poster == 1 else f"poster-{index_poster}.jpg"
        generate_poster(current_art_video, show_folder / name)
        index_poster += 1

    for _ in range(1, fanart_count + 1):
        current_art_video = random.choice(video_paths)
        name = "fanart.jpg" if index_fanart == 1 else f"fanart-{index_fanart}.jpg"
        generate_fanart(current_art_video, show_folder / name)
        index_fanart += 1


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


def check_download(path: Path, filename: str):
    return (path / filename).exists()


if __name__ == "__main__":

    playlist_opts = {
        **COMMON_YDL_OPTS,
        "extract_flat": True
    }

    with YoutubeDL(playlist_opts) as ydl:
        data = ydl.extract_info(PLAYLIST_URL, download=False)

    print(data["title"])
    print(len(data["entries"]))

    videos = data["entries"]

    if SIZE_CHECK:
        total_size = 0
        for video in tqdm(videos, desc="Checking File Size"):
            video_url = video.get("webpage_url") or video.get("url") or f"https://www.youtube.com/watch?v={video['id']}"
            size = get_video_size_bytes(video_url)
            total_size += size
        print(f"\nTotal size: {total_size / 1024 / 1024 / 1024:.2f} GB")

    if ASK_BEFORE_DOWNLOAD:
        input("Press any key to continue: ")

    if DOWNLOAD:
        index = 0
        try:
            for video in tqdm(videos, desc="Downloading Videos"):
                video_url = video.get("webpage_url") or video.get(
                    "url") or f"https://www.youtube.com/watch?v={video['id']}"

                temp_name = get_final_filename(video_url, str(DOWNLOAD_TEMP_PATH))
                final_name = f"S01E{(index + 1):03} {temp_name}"

                print(final_name)

                if check_download(VIDEO_PATH / "Season 01", final_name):
                    print(f"✅ Skipping (already exists): {final_name}")
                    index += 1
                    continue

                download_video_with_srt(video_url, str(DOWNLOAD_TEMP_PATH))

                move_files = []

                if CONVERT_VIDEOS:
                    convert(str(DOWNLOAD_TEMP_PATH), str(CONVERT_TEMP_PATH))

                    files = [f for f in CONVERT_TEMP_PATH.iterdir()
                             if f.is_file() and f.suffix.lower() in (VIDEO_EXTS | SUB_EXTS)]
                else:
                    files = [f for f in DOWNLOAD_TEMP_PATH.iterdir()
                             if f.is_file() and f.suffix.lower() in (VIDEO_EXTS | SUB_EXTS)]

                move_files.extend(files)

                for file in tqdm(move_files, desc="Moving Files"):
                    move(
                        str(file),
                        str(VIDEO_PATH / "Season 01" / f"S01E{(index + 1):03} {file.name}")
                    )

                with open(VIDEO_PATH / "Season 01" / f"S01E{(index + 1):03}.nfo", "w") as f:
                    f.write(f"""<episodedetails>
<title>{videos[index]["title"]}</title>
<showtitle>{data["title"]}</showtitle>
<season>1</season>
<episode>{index + 1}</episode>
<studio>{videos[index]["channel"]}</studio>
</episodedetails>""")

                url = videos[index]["thumbnails"][-1]["url"]
                response = requests.get(url)

                if response.status_code == 200:
                    with open(VIDEO_PATH / "Season 01" / f"S01E{(index + 1):03}-thumb.jpg", "wb") as f:
                        f.write(response.content)

                index += 1
        finally:
            print("\nDownload Finished...")

        with open(VIDEO_PATH / "tvshow.nfo", "w") as f:
            f.write(f"""<tvshow>
<title>{data["title"]}</title>
<plot>{data["description"]}</plot>
</tvshow>""")

        print("Generating video data...")

        video_files = [
            f for f in (VIDEO_PATH / "Season 01").iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
        ]

        if video_files:
            print("Generating art...")
            generate_multiple_art(video_files, str(VIDEO_PATH), 5, 10)
        else:
            print("No videos found for art generation.")

    print("\nDone!")