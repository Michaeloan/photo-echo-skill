"""Explicit local media tools; no network or account calls."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from PIL import Image
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=3)

def tool_path(name):
    override = os.environ.get("LIVE_HANDBOOK_" + name.upper())
    if override and Path(override).is_file():
        return str(Path(override).resolve())
    aliases = {"livephotobox": ["lpb", "livephotobox"], "exiftool": ["exiftool"]}
    names = aliases.get(name, [name])
    for alias in names:
        installed = shutil.which(alias)
        if installed:
            return installed
    bases = [Path(__file__).resolve().parents[1], Path(sys.executable).resolve().parent]
    if getattr(sys, "_MEIPASS", None):
        bases.insert(0, Path(sys._MEIPASS))
    for base in bases:
        for alias in names:
            tools = base / "tools"
            if tools.is_dir():
                found = next(tools.rglob(alias + ".exe"), None)
                if found:
                    return str(found.resolve())
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            pass
    return None


def cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("手帐任务已取消")


def run(args, cancel=None, timeout=180, env=None, input_data=None):
    """Poll only our process; drain outputs through communicate to avoid pipe deadlocks."""
    cancelled(cancel)
    process = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE,
        stdin=subprocess.PIPE if input_data is not None else None,
        stderr=subprocess.PIPE, creationflags=NO_WINDOW, env=env)
    deadline = time.monotonic() + timeout
    try:
        while True:
            cancelled(cancel)
            if time.monotonic() > deadline:
                raise TimeoutError("本机媒体工具运行超时")
            try:
                output, errors = process.communicate(input=input_data, timeout=.3)
                break
            except subprocess.TimeoutExpired:
                input_data = None
                continue
        if process.returncode:
            raise RuntimeError(errors.decode("utf-8", "replace")[-1500:] or "本机媒体工具失败")
        return output
    finally:
        if process.poll() is None:
            stop_process(process)


def video_info(video):
    probe = tool_path("ffprobe")
    if not probe:
        raise RuntimeError("缺少 ffprobe，无法安全读取原始 Live 时长")
    result = json.loads(run([probe, "-v", "error", "-show_format", "-show_streams", "-of", "json", video]))
    streams = [s for s in result.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise ValueError("原始 Live 视频无有效视频轨道")
    duration = float(result.get("format", {}).get("duration") or streams[0].get("duration", 0))
    if not 0 < duration < 300:
        raise ValueError("原始 Live 视频无有效视频轨道或时长超过五分钟")
    return duration, result


def extract_cover(video, target, seconds, cancel=None):
    run([tool_path("ffmpeg"), "-y", "-v", "error", "-i", video, "-ss", f"{seconds:.6f}",
        "-frames:v", "1", "-q:v", "2", target], cancel)
    if not Path(target).is_file():
        raise RuntimeError("无法从合成视频取得封面")


def _tag(records, name):
    for record in records or []:
        for key, value in record.items():
            if key.split(":")[-1].lower() == name.lower():
                return value
    return None


def read_exif(path, timed=False, cancel=None):
    # Windows Perl's argv uses the legacy codepage. Feed filenames through a
    # UTF-8 argfile on stdin, so Chinese project paths remain readable.
    path = str(Path(path).resolve())
    if "\n" in path or "\r" in path:
        raise ValueError("素材路径不能包含换行")
    args = ["-charset", "filename=utf8", "-j", "-a", "-G1"]
    if timed:
        args.append("-ee3")
    args.append(path)
    result = run([tool_path("exiftool"), "-@", "-"], cancel, input_data=("\n".join(args)+"\n").encode("utf-8"))
    if not result.strip():
        raise RuntimeError("ExifTool 未返回素材元数据")
    return json.loads(result)


def validate_apple_metadata(probe, image_exif, video_exif, seconds=None):
    image_id = _tag(image_exif, "ContentIdentifier")
    video_id = _tag(video_exif, "ContentIdentifier") or probe.get("format", {}).get("tags", {}).get("com.apple.quicktime.content.identifier")
    timed = any(s.get("codec_type") == "data" and s.get("codec_tag_string") == "mebx"
                for s in probe.get("streams", [])) and _tag(video_exif, "StillImageTime") is not None
    timestamp_valid = True
    if seconds is not None:
        group = next((key.rsplit(":", 1)[0] for record in video_exif for key in record
                      if key.endswith(":StillImageTime")), None)
        track = next((record.get(group + ":TrackID") for record in video_exif
                      if group and group + ":TrackID" in record), None)
        stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "data" and
                       int(str(s.get("id", "0")), 0) == track), None)
        packets = [p for p in probe.get("packets", []) if stream and p.get("stream_index") == stream.get("index")]
        timestamp_valid = bool(packets and abs(float(packets[0].get("pts_time", -999))-seconds) <= .04)
    return {"valid": bool(image_id and image_id == video_id and timed and timestamp_valid),
            "paired_identifier": bool(image_id and image_id == video_id), "timed_metadata": timed,
            "cover_timestamp": timestamp_valid}


def disk_path(path):
    """Python disk operations may need extended paths; never pass these to LPB."""
    path = Path(path).resolve()
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return Path("\\\\?\\UNC\\"+value[2:] if value.startswith("\\\\") else "\\\\?\\"+value)
    return path


def copy_cancelled(source, target, cancel=None):
    with disk_path(source).open("rb") as reader, disk_path(target).open("wb") as writer:
        while True:
            cancelled(cancel)
            chunk = reader.read(1024*1024)
            if not chunk:
                break
            writer.write(chunk)


def package_apple(cover, video, folder, seconds, cancel=None):
    cli, probe, exiftool = [tool_path(n) for n in ("livephotobox", "ffprobe", "exiftool")]
    if not all((cli, probe, exiftool)):
        raise RuntimeError("Apple 实况未完成：缺少 Live Photo Box、ffprobe 或 ExifTool")
    cancelled(cancel)
    folder = Path(folder)
    # LPB uses legacy native/Perl paths internally. Deep project paths plus its
    # own Temp/task directories can exceed MAX_PATH, even when Python works.
    # Keep all native operations in a private short staging directory and copy
    # only the verified, immutable pair into the project afterwards.
    with tempfile.TemporaryDirectory(prefix="live-handbook-") as temporary:
        stage = Path(temporary)
        staged_cover, staged_video = stage/"cover.jpg", stage/"preview.mp4"
        copy_cancelled(cover,staged_cover,cancel)
        copy_cancelled(video,staged_video,cancel)
        env = os.environ.copy()
        env["DOTNET_PROCESSOR_COUNT"] = str(min(os.cpu_count() or 4, 8))
        motion = stage/"motion"; motion.mkdir()
        apple = stage/"apple"; apple.mkdir()
        run([cli,"merge",staged_cover,staged_video,"-p","motionphoto","-o",motion,
            "--key-timestamp",f"{seconds:.6f}","-j","1","-y"],cancel,300,env)
        source = next((p for p in motion.rglob("*") if p.suffix.lower()==".jpg"),None)
        if not source:
            raise RuntimeError("Live Photo Box 未生成中间 Motion Photo")
        run([cli,"split",source,"-p","apple","-f","jpg+mov","-o",apple,
            "--key-timestamp",f"{seconds:.6f}","-j","1","-y"],cancel,300,env)
        image = next((p for p in apple.rglob("*") if p.suffix.lower()==".jpg"),None)
        movie = next((p for p in apple.rglob("*") if p.suffix.lower()==".mov"),None)
        if not image or not movie:
            raise RuntimeError("Live Photo Box 未生成 Apple 配对资源")
        data = json.loads(run([probe,"-v","error","-show_format","-show_streams",
                              "-show_packets","-of","json",movie],cancel))
        checks = validate_apple_metadata(data,read_exif(image,cancel=cancel),
                                        read_exif(movie,timed=True,cancel=cancel),seconds)
        if not checks["valid"]:
            raise RuntimeError("Apple 配对元数据检查失败："+json.dumps(checks,ensure_ascii=False))
        destination = folder/"apple"
        disk_path(destination).mkdir(parents=True,exist_ok=True)
        final_image, final_movie = destination/image.name, destination/movie.name
        pending_image, pending_movie = destination/(image.name+".tmp"), destination/(movie.name+".tmp")
        try:
            copy_cancelled(image,pending_image,cancel)
            copy_cancelled(movie,pending_movie,cancel)
            cancelled(cancel)
            disk_path(pending_image).replace(disk_path(final_image))
            disk_path(pending_movie).replace(disk_path(final_movie))
        finally:
            for pending in (pending_image,pending_movie):
                disk_path(pending).unlink(missing_ok=True)
        return final_image,final_movie,checks
