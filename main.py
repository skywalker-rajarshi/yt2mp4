import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

app = FastAPI(title="Video Downloader API")

# --- Configuration & Setup ---
MAX_BYTES = 1 * 1024 * 1024 * 1024  # Hard size cap: 1 GiB
YOUTUBE_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)
TEMP_DIR = Path(tempfile.gettempdir()) / "video_downloader"
TEMP_DIR.mkdir(exist_ok=True)


# --- Helper Functions ---
def is_youtube_url(url: str | None) -> bool:
    return bool(url and YOUTUBE_RE.match(url.strip()))

def sanitize_filename(name: str) -> str:
    name = re.sub(r'\s+', '_', name)
    safe = re.sub(r'[^A-Za-z0-9_.-]', '', name).strip('_.-')
    return safe or "download"

def check_binary(name: str, install_hint: str):
    if shutil.which(name) is None:
        raise HTTPException(status_code=500, detail=f"{name} not found. {install_hint}")

async def get_video_meta(url: str):
    meta_cmd = ["yt-dlp", "--no-playlist", "--dump-json", url]
    proc = await asyncio.create_subprocess_exec(
        *meta_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stderr_output = stderr.decode(errors="ignore")
    if proc.returncode != 0:
        if "age-restricted" in stderr_output or "Sign in to confirm your age" in stderr_output:
             raise HTTPException(status_code=403, detail="This video is age-restricted and cannot be downloaded.")
        raise HTTPException(status_code=502, detail=f"yt-dlp metadata error: Could not fetch video details.")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Could not parse video metadata.")

def cleanup_file_sync(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        print(f"Error cleaning up file {path}: {e}")

def format_bytes(size: int | None) -> str:
    if size is None: return "N/A"
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(power_labels) -1 :
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

# --- API Endpoints ---
@app.post("/api/video_info")
async def get_video_info(payload: dict = Body(...)):
    url = payload.get("url")
    format_req = payload.get("format", "mp4")
    quality_req = payload.get("quality", "best")

    if not is_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    meta = await get_video_meta(url)
    title = meta.get("title", "video")
    thumbnail = meta.get("thumbnail")

    estimated_size = None
    formats = meta.get("formats", [])

    if format_req == "mp3":
        audio_streams = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        best_audio = max(audio_streams, key=lambda x: x.get('abr', 0), default=None)
        if best_audio:
            estimated_size = best_audio.get('filesize') or best_audio.get('filesize_approx')
    else: # Video formats
        height_req = int(quality_req.replace("p", "")) if "p" in quality_req else 10000
        
        video_streams = [
            f for f in formats 
            if f.get('vcodec') != 'none' and f.get('acodec') == 'none' 
            and (f.get('height') or 0) <= height_req
        ]
        best_video = max(video_streams, key=lambda x: (x.get('height', 0), x.get('vbr', 0)), default=None)
        
        audio_streams = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        best_audio = max(audio_streams, key=lambda x: x.get('abr', 0), default=None)
        
        if best_video and best_audio:
            size1 = best_video.get('filesize') or best_video.get('filesize_approx') or 0
            size2 = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0
            estimated_size = size1 + size2
        else:
            combined_streams = [
                f for f in formats 
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none' 
                and (f.get('height') or 0) <= height_req
            ]
            best_combined = max(combined_streams, key=lambda x: (x.get('height', 0), x.get('vbr', 0)), default=None)
            if best_combined:
                estimated_size = best_combined.get('filesize') or best_combined.get('filesize_approx')

    return {
        "title": title,
        "thumbnail_url": thumbnail,
        "estimated_size": format_bytes(estimated_size)
    }


@app.post("/api/download")
async def download_video(payload: dict = Body(...)):
    url = payload.get("url")
    format = payload.get("format", "mp4")
    quality = payload.get("quality", "best")
    bitrate = payload.get("bitrate", "192")

    if not is_youtube_url(url):
        raise HTTPException(status_code=400, detail="Please provide a valid YouTube URL.")

    check_binary("yt-dlp", "Install with: pip install yt-dlp")
    if format == "mp3":
        check_binary("ffmpeg", "Install ffmpeg and ensure it is in PATH")

    meta = await get_video_meta(url)
    title = meta.get("title", "video")
    safe_title = sanitize_filename(title)

    if format == "mp3":
        filename = f"{safe_title}.mp3"
        temp_filename = f"{safe_title}_{Path(tempfile.mktemp()).stem}.mp3"
        output_path = TEMP_DIR / temp_filename
        dl_cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", f"{bitrate}K", "--embed-thumbnail", "--add-metadata", "-o", str(output_path), url]
        proc = await asyncio.create_subprocess_exec(*dl_cmd, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not output_path.exists():
            error_detail = stderr.decode(errors="ignore")
            if "age-restricted" in error_detail or "Sign in to confirm your age" in error_detail:
                raise HTTPException(status_code=403, detail="This video is age-restricted and cannot be downloaded.")
            raise HTTPException(status_code=502, detail="Failed to create MP3 file.")
        def stream_mp3():
            with open(output_path, "rb") as f: yield from f
        cleanup_task = BackgroundTask(cleanup_file_sync, output_path)
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return StreamingResponse(stream_mp3(), media_type="audio/mpeg", headers=headers, background=cleanup_task)

    ext = "mp4" if format == "mp4" else "webm"
    filename = f"{safe_title}-{quality}.{ext}" if quality != "best" else f"{safe_title}.{ext}"
    height_selector = ""
    if "p" in quality:
        height = quality.replace("p", "")
        height_selector = f"[height<={height}]"
    if format == "mp4":
        format_selector = f"bestvideo[vcodec^=avc1]{height_selector}+bestaudio[ext=m4a]/best[ext=mp4]{height_selector}/best"
    else:
        format_selector = f"bestvideo[ext=webm]{height_selector}+bestaudio[ext=webm]/best[ext=webm]{height_selector}/best"
    dl_cmd = ["yt-dlp", "--no-playlist", "-f", format_selector, "-o", "-", url]
    if format == "mp4":
        dl_cmd.extend(["--merge-output-format", "mp4"])
    proc = await asyncio.create_subprocess_exec(*dl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    async def stream_content():
        try:
            # We need to wait for the process to finish to check stderr
            stdout_data, stderr_data = await proc.communicate()
            stderr_output = stderr_data.decode(errors="ignore")

            if proc.returncode != 0:
                if "age-restricted" in stderr_output or "Sign in to confirm your age" in stderr_output:
                    # We can't raise HTTPException here as headers are already sent.
                    # This stream will be empty, and the client will see a failed download.
                    # A better architecture (websockets) would solve this.
                    print("Age-restricted video download failed.")
                    return # End the stream
                if "does not start with a start code" not in stderr_output:
                     print(f"yt-dlp failed: {stderr_output[-1000:]}")
                     return

            # Stream the captured stdout data
            total_bytes = 0
            chunk_size = 65536
            for i in range(0, len(stdout_data), chunk_size):
                chunk = stdout_data[i:i+chunk_size]
                total_bytes += len(chunk)
                if total_bytes > MAX_BYTES:
                    print("File too large, stopping stream.")
                    break
                yield chunk

        finally:
            if proc.returncode is None: proc.kill()

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(stream_content(), media_type=f"video/{ext}", headers=headers)

# --- Mount static files (must be last) ---
app.mount("/", StaticFiles(directory="static", html=True), name="static")

