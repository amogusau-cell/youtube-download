#!/usr/bin/env python3
"""
Improved video converter:
- Keeps high visual quality (CRF for libx264; CQ/VBR for NVENC/VideoToolbox)
- Copies AAC audio when present (avoid unnecessary re-encode)
- Preserves compatibility: H.264 (high), yuv420p, level 4.1, mp4 container
- Scales only when needed
- Per-file ffmpeg progress (uses -progress pipe)
"""
import subprocess
import json
import platform
from pathlib import Path
import shutil
from datetime import datetime
from tqdm import tqdm
import os
import math
import signal

# ---------- CONFIG ----------
INPUT_FOLDER = "videos"
OUTPUT_FOLDER = "converted_videos"
BACKUP_ORIGINALS = False
USE_HARDWARE_ENCODER = True

# Max target resolution (downscale only if source exceeds)
TARGET_MAX_WIDTH = 1920 * 2
TARGET_MAX_HEIGHT = 1080 * 2

# Software (libx264) quality: lower CRF => higher quality/size (18 is visually near-lossless)
DEFAULT_CRF = 18
# Hardware target maxrate (effective ceiling for VBR hw encoders)
HW_MAXRATE = "12M"
HW_BUFSIZE = "24M"
# Audio
AUDIO_BITRATE = "128k"
# Recognized video extensions
VIDEO_EXTS = [".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm"]

# ---------- helpers ----------
def run_cmd(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def probe(path):
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    cp = run_cmd(cmd)
    if cp.returncode != 0:
        return None
    try:
        return json.loads(cp.stdout)
    except:
        return None

def detect_hardware_encoder():
    system = platform.system()
    try:
        enc = run_cmd(['ffmpeg', '-hide_banner', '-encoders']).stdout.lower()
    except:
        enc = ""
    if not USE_HARDWARE_ENCODER:
        return None, "Software libx264"
    if system == "Darwin" and 'h264_videotoolbox' in enc:
        return 'h264_videotoolbox', "Apple VideoToolbox (hw)"
    if system in ("Linux", "Windows") and 'h264_nvenc' in enc:
        return 'h264_nvenc', "NVIDIA NVENC (hw)"
    return None, "Software libx264"

def h264_level_int(level_field):
    if level_field is None:
        return None
    try:
        lv = float(level_field)
        return int(round(lv * 10)) if lv < 10 else int(lv)
    except:
        try:
            return int(level_field)
        except:
            return None

def is_compatible_probe(probe_json):
    """Return (bool, issues_list). Compatible = H264, yuv420p, level <=4.1, AAC present, <=1080p, container mp4/mov."""
    if not probe_json:
        return False, ["ffprobe failed"]
    issues = []
    fmt = probe_json.get("format", {})
    fname = fmt.get("format_name", "")
    streams = probe_json.get("streams", [])
    # container
    if not any(x in fname for x in ("mp4", "mov")):
        issues.append(f"Container: {fname} (prefer mp4/mov)")
    video = None
    audio_ok = False
    subs = False
    for s in streams:
        if s.get("codec_type") == "video" and video is None:
            video = s
        elif s.get("codec_type") == "audio":
            if s.get("codec_name") == "aac":
                audio_ok = True
        elif s.get("codec_type") == "subtitle":
            subs = True
            issues.append(f"Embedded subtitle: {s.get('codec_name')}")
    if not video:
        issues.append("No video stream")
        return False, issues
    if video.get("codec_name") != "h264":
        issues.append(f"Video codec: {video.get('codec_name')}")
    if video.get("pix_fmt") and video.get("pix_fmt") != "yuv420p":
        issues.append(f"Pixel format: {video.get('pix_fmt')}")
    profile = (video.get("profile") or "").lower()
    if profile and profile not in ("baseline","main","high"):
        issues.append(f"Profile: {video.get('profile')}")
    lvl = h264_level_int(video.get("level"))
    if lvl and lvl > 41:
        issues.append(f"Level {lvl/10:.1f} > 4.1")
    w = int(video.get("width",0))
    h = int(video.get("height",0))
    if w > TARGET_MAX_WIDTH or h > TARGET_MAX_HEIGHT:
        issues.append(f"Res {w}x{h} > {TARGET_MAX_WIDTH}x{TARGET_MAX_HEIGHT}")
    if not audio_ok:
        issues.append("No AAC audio track")
    if subs:
        issues.append("Embedded subtitles may trigger transcoding on iOS")
    return len(issues) == 0, issues

def build_ffmpeg_cmd(input_path, output_path, encoder=None, force_scale=False, copy_audio=False):
    """
    Build ffmpeg command tuned for quality:
    - libx264: CRF (DEFAULT_CRF) (no fixed -b:v)
    - h264_nvenc: CQ/VBR style settings with a generous maxrate
    - h264_videotoolbox: use higher bitrate + qscale (best-effort)
    """
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(input_path)]

    vf = []
    if force_scale:
        # scale while preserving aspect ratio, force even dimensions (h264 requirement)
        # uses -2 trick to keep divisible by 2
        vf_expr = ("scale='if(gt(iw/ih,{ar}),{w},-2)':'if(gt(iw/ih,{ar}),-2,{h})'"
                   .format(ar=TARGET_MAX_WIDTH/TARGET_MAX_HEIGHT, w=TARGET_MAX_WIDTH, h=TARGET_MAX_HEIGHT))
        vf.append(vf_expr)

    # Choose video codec and quality strategy
    if encoder == 'h264_videotoolbox':
        # Videotoolbox tends to be less efficient than libx264: give it a higher ceiling
        # Use a quality parameter (-q:v) and higher bitrate ceiling.
        cmd += ["-c:v","h264_videotoolbox",
                "-pix_fmt","yuv420p",
                "-profile:v","high",
                "-level","4.1",
                "-q:v","18",                 # quality hint (smaller = better). best-effort
                "-b:v", HW_MAXRATE,
                "-maxrate", HW_MAXRATE,
                "-bufsize", HW_BUFSIZE]
    elif encoder == 'h264_nvenc':
        # NVENC: prefer VBR with CQ to keep visual quality.
        # -rc vbr_hq (or vbr) and -cq provide quality target (lower = better).
        # We also leave -b:v 0 to let CQ control, but give a maxrate ceiling for compatibility.
        cmd += ["-c:v","h264_nvenc",
                "-pix_fmt","yuv420p",
                "-profile:v","high",
                "-level","4.1",
                "-preset","p4",              # balanced preset; use p1 for best quality slower
                "-rc","vbr",                # rate control: vbr (or try vbr_hq if ffmpeg supports)
                "-cq","19",                 # NVENC quality target (lower = better). ~19 is close to CRF18
                "-b:v","0",                 # let CQ drive bitrate
                "-maxrate", HW_MAXRATE,
                "-bufsize", HW_BUFSIZE]
    else:
        # Software encoding (libx264) - use CRF (quality-based).
        cmd += ["-c:v","libx264",
                "-preset","slow",           # slower => better quality for same size; change to medium if too slow
                "-crf", str(DEFAULT_CRF),
                "-pix_fmt","yuv420p",
                "-profile:v","high",
                "-level","4.1"]

    if vf:
        cmd += ["-vf", ",".join(vf)]

    # Audio handling: copy if already AAC, else re-encode to AAC stereo
    if copy_audio:
        cmd += ["-c:a","copy"]
    else:
        cmd += ["-c:a","aac","-b:a",AUDIO_BITRATE,"-ac","2"]

    cmd += ["-movflags","+faststart","-f","mp4","-progress","pipe:1","-nostats","-loglevel","error", str(output_path)]
    return cmd

def get_duration_seconds(path):
    cp = run_cmd([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1", str(path)
    ])
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        return float(cp.stdout.strip())
    except:
        return None

# ---------- ffmpeg progress helper ----------
def run_ffmpeg_with_progress(cmd, duration_seconds, progress_bar):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        start_new_session=True,
    )
    last_percent = 0
    try:
        # ffmpeg -progress writes key=value lines to stdout
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            if raw.startswith("out_time_ms="):
                try:
                    out_ms = int(raw.split("=",1)[1])
                    # out_time_ms is in microseconds (ffmpeg prints microseconds)
                    out_s = out_ms / 1_000_000.0
                    if duration_seconds:
                        percent = min(int((out_s / duration_seconds) * 100), 100)
                        if percent > last_percent:
                            progress_bar.n = percent
                            progress_bar.refresh()
                            last_percent = percent
                except:
                    pass
            elif raw.startswith("out_time="):
                try:
                    t = raw.split("=",1)[1]
                    h,m,s = t.split(":")
                    out_s = float(h)*3600 + float(m)*60 + float(s)
                    if duration_seconds:
                        percent = min(int((out_s / duration_seconds) * 100), 100)
                        if percent > last_percent:
                            progress_bar.n = percent
                            progress_bar.refresh()
                            last_percent = percent
                except:
                    pass
            elif raw.startswith("progress="):
                if raw.split("=",1)[1] == "end":
                    progress_bar.n = 100
                    progress_bar.refresh()
    except KeyboardInterrupt:
        # Ensure ffmpeg and any children die immediately on Ctrl+C
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except:
            pass
        try:
            proc.wait(timeout=2)
        except:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except:
                pass
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()
    proc.wait()
    stderr = proc.stderr.read()
    if proc.stderr:
        proc.stderr.close()
    return proc.returncode, stderr

def remux_copy(input_path, output_path, progress_bar):
    # fast remux with copy (no re-encode)
    cmd = ["ffmpeg","-hide_banner","-y","-i", str(input_path), "-c","copy","-movflags","+faststart","-progress","pipe:1","-nostats","-loglevel","error", str(output_path)]
    dur = get_duration_seconds(input_path)
    return run_ffmpeg_with_progress(cmd, dur, progress_bar)

# ---------- main conversion logic ----------
def convert_file(input_path, output_path, encoder, overall_pbar=None):
    p_in = probe(input_path)
    compatible, issues = is_compatible_probe(p_in)
    fmt = p_in.get("format",{}).get("format_name","") if p_in else ""
    tmp_sw = output_path.with_suffix(".sw.tmp.mp4")

    def cleanup_partial_outputs():
        # Remove incomplete artifacts if conversion is interrupted.
        for p in (output_path, tmp_sw):
            try:
                if p.exists():
                    p.unlink()
            except:
                pass

    # Already fully compatible and mp4 -> skip
    if compatible and ("mp4" in fmt or "mov" in fmt):
        return True, "already compatible - skipped"

    # If compatible except container -> fast remux copy
    if compatible:
        try:
            with tqdm(total=100, desc=f"Remux {input_path.name}", position=1, leave=False, ncols=100) as pbar:
                rc, err = remux_copy(input_path, output_path, pbar)
                if rc == 0:
                    return True, "remuxed to mp4"
                else:
                    pass
        except KeyboardInterrupt:
            cleanup_partial_outputs()
            raise

    # Determine scaling need
    need_scale = False
    audio_is_aac = False
    if p_in:
        for s in p_in.get("streams",[]):
            if s.get("codec_type") == "video":
                w = int(s.get("width",0)); h = int(s.get("height",0))
                if w > TARGET_MAX_WIDTH or h > TARGET_MAX_HEIGHT:
                    need_scale = True
                break
        for s in p_in.get("streams",[]):
            if s.get("codec_type") == "audio" and s.get("codec_name") == "aac":
                audio_is_aac = True

    # build cmd: copy audio if possible to avoid re-encode
    cmd = build_ffmpeg_cmd(input_path, output_path, encoder=encoder, force_scale=need_scale, copy_audio=audio_is_aac)

    dur = get_duration_seconds(input_path)
    try:
        with tqdm(total=100, desc=f"Encode {input_path.name}", position=1, leave=False, ncols=100) as pbar:
            rc, stderr = run_ffmpeg_with_progress(cmd, dur, pbar)
    except KeyboardInterrupt:
        cleanup_partial_outputs()
        raise

    if rc == 0:
        p_out = probe(output_path)
        ok_out, issues_out = is_compatible_probe(p_out)
        if ok_out:
            return True, "encoded and compatible"
        # else, fallback to software encode if we used hardware or something odd happened
    # fallback to software libx264 using CRF
    cmd_sw = build_ffmpeg_cmd(input_path, tmp_sw, encoder=None, force_scale=need_scale, copy_audio=audio_is_aac)
    try:
        with tqdm(total=100, desc=f"SW encode {input_path.name}", position=1, leave=False, ncols=100) as pbar:
            rc2, stderr2 = run_ffmpeg_with_progress(cmd_sw, dur, pbar)
    except KeyboardInterrupt:
        cleanup_partial_outputs()
        raise
    if rc2 == 0:
        ok_tmp, issues_tmp = is_compatible_probe(probe(tmp_sw))
        if ok_tmp:
            if output_path.exists():
                output_path.unlink()
            tmp_sw.rename(output_path)
            return True, "software encoded (CRF) and compatible"
        else:
            # still not compatible - return failure and issues
            return False, f"software encoded but not compatible: {issues_tmp}"
    else:
        return False, f"both hw and sw encoding failed: {stderr[:200]} {stderr2[:200]}"

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

def convert_all_videos():
    inp = Path(INPUT_FOLDER)
    outp = Path(OUTPUT_FOLDER)
    if not inp.exists():
        print(f"❌ Input folder '{INPUT_FOLDER}' not found!")
        return
    outp.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in inp.iterdir() if p.suffix.lower() in VIDEO_EXTS])
    if not files:
        print("❌ No video files found")
        return

    encoder, enc_name = detect_hardware_encoder()
    print("="*60)
    print("Converter (preserve quality: libx264 CRF / hw CQ) - with pre-check & per-file progress")
    print(f"Input: {inp.resolve()} -> Output: {outp.resolve()}")
    print(f"Encoder: {enc_name}")
    print(f"Software CRF (libx264): {DEFAULT_CRF}   HW maxrate (ceiling): {HW_MAXRATE}")
    print("="*60)

    backup_dir = None
    if BACKUP_ORIGINALS:
        backup_dir = inp / "originals_backup"
        backup_dir.mkdir(exist_ok=True)

    ok = failed = skipped = 0
    with tqdm(total=len(files), desc="Overall", unit="file", ncols=100) as overall:
        for f in files:
            out_file = outp / (f.stem + ".mp4")
            p_in = probe(f)
            compatible, issues = is_compatible_probe(p_in)
            if compatible and ("mp4" in (p_in.get("format",{}).get("format_name","") or "")):
                overall.set_postfix_str(f"Skipped (already compatible): {f.name}")
                skipped += 1
                overall.update(1)
                continue
            start = datetime.now()
            success, msg = convert_file(f, out_file, encoder, overall)
            elapsed = (datetime.now() - start).total_seconds()
            if success:
                ok += 1
                overall.set_postfix_str(f"✅ {f.name[:30]} | {msg} | {elapsed:.0f}s")

                if BACKUP_ORIGINALS and backup_dir:
                    shutil.move(str(f), str(backup_dir / f.name))
                else:
                    # delete original if conversion succeeded
                    try:
                        f.unlink()
                    except Exception as e:
                        print(f"⚠️ Could not delete original {f.name}: {e}")
            else:
                failed += 1
                overall.set_postfix_str(f"❌ {f.name[:20]} | {msg}")
            overall.update(1)

    print("\n" + "="*60)
    print(f"Done. ✅ {ok}  ❌ {failed}  ⏭️ {skipped}")
    print("="*60)

def convert_videos(input_path, output_path):
    global INPUT_FOLDER, OUTPUT_FOLDER

    old_input = INPUT_FOLDER
    old_output = OUTPUT_FOLDER

    INPUT_FOLDER = str(input_path)
    OUTPUT_FOLDER = str(output_path)

    try:
        convert_all_videos()

        files = [f for f in Path(INPUT_FOLDER).iterdir() if f.is_file()]
        for file in files:
            move(file, Path(OUTPUT_FOLDER) / file.name)
    finally:
        INPUT_FOLDER = old_input
        OUTPUT_FOLDER = old_output


if __name__ == "__main__":
    print("⚠️ Convert videos to H.264 (High @ level 4.1) with preserved visual quality.")
    print(f"Input: {INPUT_FOLDER}  Output: {OUTPUT_FOLDER}")
    a = "y"
    if a in ("y","yes"):
        convert_all_videos()

        files = [f for f in Path(INPUT_FOLDER).iterdir() if f.is_file()]
        for file in files:
            move(file, Path(OUTPUT_FOLDER) / file.name)
    else:
        print("Cancelled.")
