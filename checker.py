import subprocess
from pathlib import Path

# CONFIG
CHECK_FOLDER = "vids"   # Folder to scan
VIDEO_EXTS = [".mp4", ".mkv", ".webm"]

def ffprobe(path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(path)
    ]
    return subprocess.run(cmd, capture_output=True, text=True)

def analyze_video(path):
    result = ffprobe(path)
    if result.returncode != 0:
        return False, ["ffprobe failed"]

    import json
    data = json.loads(result.stdout)

    issues = []
    video_ok = audio_ok = True
    subs_found = False

    # Container
    container = data["format"]["format_name"]
    if "mp4" not in container:
        issues.append(f"Container is {container}, expected MP4")

    for stream in data["streams"]:
        if stream["codec_type"] == "video":
            codec = stream.get("codec_name")
            profile = stream.get("profile", "")
            pix_fmt = stream.get("pix_fmt", "")
            level = stream.get("level", 0)

            if codec != "h264":
                video_ok = False
                issues.append(f"Video codec is {codec}, expected h264")

            if pix_fmt != "yuv420p":
                video_ok = False
                issues.append(f"Pixel format is {pix_fmt}, expected yuv420p")

            if level and level > 41:
                video_ok = False
                issues.append(f"H.264 level {level/10:.1f} > 4.1")

            if profile.lower() not in ["baseline", "main", "high"]:
                video_ok = False
                issues.append(f"Unsupported profile: {profile}")

        elif stream["codec_type"] == "audio":
            if stream.get("codec_name") != "aac":
                audio_ok = False
                issues.append(f"Audio codec is {stream.get('codec_name')}, expected AAC")

        elif stream["codec_type"] == "subtitle":
            subs_found = True
            issues.append(f"Embedded subtitle: {stream.get('codec_name')}")

    if subs_found:
        issues.append("Embedded subtitles trigger transcoding on iOS")

    return video_ok and audio_ok and not subs_found, issues

def main():
    folder = Path(CHECK_FOLDER)
    if not folder.exists():
        print(f"❌ Folder not found: {folder}")
        return

    files = [f for f in folder.iterdir() if f.suffix.lower() in VIDEO_EXTS]

    if not files:
        print("❌ No video files found")
        return

    print("=" * 70)
    print("🎬 Jellyfin Direct Play Compatibility Check")
    print("=" * 70)

    ok = bad = 0

    for file in files:
        passed, issues = analyze_video(file)

        if passed:
            print(f"✅ {file.name}")
            ok += 1
        else:
            print(f"❌ {file.name}")
            for i in issues:
                print(f"   ↳ {i}")
            bad += 1

    print("=" * 70)
    print(f"✅ Direct Play Ready: {ok}")
    print(f"❌ Needs Fixing: {bad}")
    print("=" * 70)

if __name__ == "__main__":
    main()
