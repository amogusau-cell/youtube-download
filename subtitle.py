import subprocess
import json
from pathlib import Path
import shutil
from datetime import datetime
from tqdm import tqdm
import sys

# CONFIG
INPUT_FOLDER = "vids"
OUTPUT_FOLDER = "video_no_subs"
SUBS_FOLDER = "extracted_subs"
BACKUP_ORIGINALS = True
VIDEO_EXTS = [".mp4", ".mkv", ".mov", ".avi", ".m4v", ".ts", ".webm"]

# Mapping for some known subtitle codec -> preferred extension
CODEC_EXT_MAP = {
    "subrip": ".srt",
    "srt": ".srt",
    "ass": ".ass",
    "ssa": ".ass",
    "webvtt": ".vtt",
    "webvtt": ".vtt",
    "mov_text": ".srt",      # will convert to srt
    "hdmv_pgs_subtitle": ".sup",
    "dvd_subtitle": ".sup",
    "dvdsub": ".sup",
    "pgs": ".sup",
    # fallback will use codec name as ext
}

def run(cmd):
    """Run subprocess and return CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True)

def probe(path: Path):
    """Return ffprobe json dict or None."""
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    cp = run(cmd)
    if cp.returncode != 0:
        return None
    try:
        return json.loads(cp.stdout)
    except Exception:
        return None

def safe_mkdir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def format_sub_filename(video_path: Path, idx: int, codec: str, lang: str):
    base = video_path.stem
    lang_part = f".{lang}" if lang else ""
    ext = CODEC_EXT_MAP.get(codec, f".{codec}" if codec else ".sub")
    # sanitize ext (no slashes)
    ext = ext.replace("/", "_")
    return f"{base}.s{idx}{lang_part}{ext}"

def extract_subtitle_stream(video_path: Path, stream_index: int, out_path: Path):
    """
    Try to extract/convert subtitle stream to a usable file.
    - For text-based types, convert to SRT: ffmpeg -i in -map 0:s:IDX -c:s srt out.srt
    - For bitmaps, attempt to copy stream to file with extension .sup or codec-name.
    Returns (True, message) or (False, error_message)
    """
    # first get codec name for this stream
    p = probe(video_path)
    if not p:
        return False, "ffprobe failed"

    streams = p.get("streams", [])
    target_stream = None
    for s in streams:
        if s.get("index") == stream_index and s.get("codec_type") == "subtitle":
            target_stream = s
            break
    if not target_stream:
        return False, f"subtitle stream {stream_index} not found"

    codec = target_stream.get("codec_name", "")
    lang = target_stream.get("tags", {}).get("language", "") if target_stream.get("tags") else ""

    # choose output extension / conversion
    preferred_ext = CODEC_EXT_MAP.get(codec)
    # If codec is text-like or mov_text or webvtt -> convert to srt
    text_like = codec in ("subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "vtt")
    out_file = out_path

    try:
        if text_like:
            # Convert to srt (if not ass we could keep .ass, but user wanted srt)
            # For ASS we convert to srt as requested. If you want original format keep .ass instead.
            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-i", str(video_path),
                "-map", f"0:{stream_index}",
                "-c:s", "srt",                 # convert to srt
                str(out_file)
            ]
            cp = run(cmd)
            if cp.returncode == 0:
                return True, f"extracted (converted to srt) as {out_file.name}"
            else:
                # fallback: try copy (maybe it's already srt)
                cmd2 = [
                    "ffmpeg", "-hide_banner", "-y",
                    "-i", str(video_path),
                    "-map", f"0:{stream_index}",
                    "-c:s", "copy",
                    str(out_file)
                ]
                cp2 = run(cmd2)
                if cp2.returncode == 0:
                    return True, f"extracted (copied) as {out_file.name}"
                else:
                    return False, f"ffmpeg extraction failed: {cp.stderr[:200]} {cp2.stderr[:200]}"
        else:
            # Non-text (bitmap/pgs/dvd). Try to copy raw stream to file with codec extension (.sup / .bin)
            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-i", str(video_path),
                "-map", f"0:{stream_index}",
                "-c:s", "copy",
                str(out_file)
            ]
            cp = run(cmd)
            if cp.returncode == 0:
                return True, f"extracted raw subtitle stream as {out_file.name}"
            else:
                return False, f"raw extract failed: {cp.stderr[:200]}"
    except Exception as e:
        return False, f"exception: {str(e)}"

def remux_remove_subs(input_path: Path, output_path: Path):
    """
    Remux input to output excluding subtitle streams.
    Uses: ffmpeg -i in -map 0 -map -0:s -c copy out
    If remux to same container fails, fallback to mkv container.
    """
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), "-map", "0", "-map", "-0:s", "-c", "copy", str(output_path)]
    cp = run(cmd)
    if cp.returncode == 0:
        return True, "remuxed without subtitles"
    else:
        # fallback: try mkv container (more forgiving)
        fallback = output_path.with_suffix(".no_subs.mkv")
        cmd2 = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path), "-map", "0", "-map", "-0:s", "-c", "copy", str(fallback)]
        cp2 = run(cmd2)
        if cp2.returncode == 0:
            return True, f"remuxed to {fallback.name} (fallback)"
        else:
            return False, f"remux failed: {cp.stderr[:300]} {cp2.stderr[:300]}"

def process_file(video_path: Path, out_video_dir: Path, subs_dir: Path, backup_dir: Path = None):
    p = probe(video_path)
    if p is None:
        return False, f"ffprobe failed for {video_path.name}"

    streams = p.get("streams", [])
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
    if not subtitle_streams:
        return True, "no embedded subtitle streams found"

    # ensure dirs
    safe_mkdir(out_video_dir)
    safe_mkdir(subs_dir)
    if backup_dir:
        safe_mkdir(backup_dir)

    extracted = []
    # For each subtitle stream extract it
    for s in subtitle_streams:
        idx = s.get("index")
        codec = s.get("codec_name", "")
        lang = s.get("tags", {}).get("language", "") if s.get("tags") else ""
        fname = format_sub_filename(video_path, idx, codec, lang)
        out_sub_path = subs_dir / fname
        ok, msg = extract_subtitle_stream(video_path, idx, out_sub_path)
        extracted.append((ok, msg, out_sub_path.name))
        print(f"   • stream idx={idx} codec={codec} lang={lang} -> {msg}")

    # After extracting, remux file without subtitles
    out_video_path = out_video_dir / video_path.name
    ok_rmux, msg_rmux = remux_remove_subs(video_path, out_video_path)
    if not ok_rmux:
        return False, f"remux failed: {msg_rmux}"

    # backup original if asked
    if backup_dir:
        try:
            shutil.move(str(video_path), str(backup_dir / video_path.name))
        except Exception as e:
            print(f"Warning: failed to move original to backup: {e}")

    return True, f"extracted {len(subtitle_streams)} subs, remux: {msg_rmux}"

def main():
    inp = Path(INPUT_FOLDER)
    out_vid = Path(OUTPUT_FOLDER)
    subs_out = Path(SUBS_FOLDER)
    if not inp.exists():
        print(f"❌ Input folder '{INPUT_FOLDER}' not found. Create it and put videos there.")
        return

    files = sorted([p for p in inp.iterdir() if p.suffix.lower() in VIDEO_EXTS])
    if not files:
        print("❌ No supported video files found in input folder.")
        return

    backup_dir = (inp / "originals_backup") if BACKUP_ORIGINALS else None
    if backup_dir:
        safe_mkdir(backup_dir)

    print(f"Found {len(files)} files. Processing...")

    results = []
    with tqdm(total=len(files), desc="Overall", ncols=100) as overall:
        for f in files:
            overall.set_postfix_str(f.name[:30])
            # quick probe to see if there are subtitles
            p = probe(f)
            if not p:
                results.append((f.name, False, "ffprobe failed"))
                overall.update(1)
                continue
            streams = p.get("streams", [])
            subs = [s for s in streams if s.get("codec_type") == "subtitle"]
            if not subs:
                results.append((f.name, True, "no embedded subtitles"))
                overall.update(1)
                continue

            start = datetime.now()
            ok, msg = process_file(f, out_vid, subs_out, backup_dir)
            duration = (datetime.now() - start).total_seconds()
            results.append((f.name, ok, msg, duration))
            overall.update(1)

    # summary
    print("\n" + "="*60)
    print("Summary:")
    for r in results:
        if r[1]:
            if len(r) == 4:
                print(f"✅ {r[0]} | {r[2]} | {r[3]:.0f}s")
            else:
                print(f"✅ {r[0]} | {r[2]}")
        else:
            print(f"❌ {r[0]} | {r[2]}")
    print("="*60)
    print(f"Extracted subs saved to: {Path(SUBS_FOLDER).resolve()}")
    print(f"Videos without subs saved to: {Path(OUTPUT_FOLDER).resolve()}")
    if BACKUP_ORIGINALS:
        print(f"Originals moved to: {Path(INPUT_FOLDER) / 'originals_backup'}")

if __name__ == "__main__":
    print("This will extract embedded subtitles to .srt/.sup and remux videos without subtitle streams.")
    ans = input("Continue? (y/N): ").strip().lower()
    if ans in ("y", "yes"):
        main()
    else:
        print("Cancelled.")
