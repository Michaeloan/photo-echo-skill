"""Local crop / still / animation / optional Apple resource export. No model calls."""
from __future__ import annotations
import argparse
import copy
import hashlib
import contextlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
import uuid
import os

from PIL import Image, ImageOps
import pillow_heif
pillow_heif.register_heif_opener()
from handbook_core.animation import validate_scene_plan
from handbook_core.artwork import prepare_scene
from handbook_core.editorial import compose_equal_halves
from handbook_core.media import (NO_WINDOW, extract_cover, package_apple, run, stop_process,
                                 tool_path, video_info)
from handbook_core.selection import crop_reference, selection_header_focus, validate_selection
from handbook_core.continuous_motion import VERSION as MOTION_VERSION


def read_json(path):
    if Path(path).stat().st_size > 2_000_000:
        raise ValueError("JSON settings exceed two MB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("JSON numbers must be finite")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=constant)


def crop(args):
    with Image.open(args.source) as image:
        selection = validate_selection(read_json(args.selection), ImageOps.exif_transpose(image).size)
        reference, pixels = crop_reference(image, selection)
    output = Path(args.out)
    if output.exists():
        raise ValueError("Reference already exists; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    reference.save(output)
    print(json.dumps({"reference": str(output), "crop_pixels": pixels,
                      "suggested_focus": selection_header_focus(selection)}, ensure_ascii=False))


def encode(scene, plan, target, fps, duration, live_video=None, focus=(.5, .5)):
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Install FFmpeg or set LIVE_HANDBOOK_FFMPEG")
    width, height = scene.page.size
    with tempfile.TemporaryDirectory(prefix="encode-", dir=target.parent) as temporary:
        silent, errors_path = Path(temporary)/"silent.mp4", Path(temporary)/"ffmpeg.log"
        with errors_path.open("wb") as errors:
            process = subprocess.Popen([ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
                "-threads", "2", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(silent)], stdin=subprocess.PIPE, stderr=errors,
                stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
            try:
                for frame in range(max(1, round(duration*fps))):
                    process.stdin.write(scene.frame(frame/fps, duration, plan).tobytes())
                process.stdin.close()
                process.wait(timeout=60)
                if process.returncode:
                    raise RuntimeError(errors_path.read_text(encoding="utf-8", errors="replace")[-1500:])
            finally:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                stop_process(process)
        if not live_video:
            shutil.copyfile(silent, target)
            return
        info = video_info(live_video)[1]
        hdr = any(stream.get("color_transfer") in ("smpte2084", "arib-std-b67")
                  for stream in info["streams"] if stream.get("codec_type") == "video")
        tone = ("zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,"
                "zscale=p=bt709:t=bt709:m=bt709:r=tv,format=yuv420p," if hdr else "")
        half = height//2
        ratio = width/half
        fx, fy = focus
        filters = (f"[1:v]{tone}crop=w='min(iw,ih*{ratio:.10f})':h='min(ih,iw/{ratio:.10f})':"
            f"x='max(0,min(iw-ow,iw*{fx:.10f}-ow/2))':y='max(0,min(ih-oh,ih*{fy:.10f}-oh/2))',"
            f"scale={width}:{half},format=rgba,setsar=1[top];[0:v][top]overlay=0:0:shortest=1[out]")
        run([ffmpeg, "-y", "-v", "error", "-i", silent, "-i", live_video, "-filter_complex", filters,
             "-map", "[out]", "-map", "1:a?", "-c:v", "libx264", "-threads", "2", "-preset", "fast",
             "-crf", "18", "-c:a", "aac", "-pix_fmt", "yuv420p", "-r", str(fps), "-t", str(duration),
             "-movflags", "+faststart", target], timeout=max(180, duration*20))


def _render_one(args):
    # Validate everything before decoding media, creating outputs or running a tool.
    if type(args.width) is not int or type(args.height) is not int or not 64<=args.width<=2160 or not 64<=args.height<=2880:
        raise ValueError("Canvas outside supported size")
    if args.width%2 or args.height%4 or not 10<=args.fps<=60:
        raise ValueError("Width must be even; height divisible by four; FPS 10–60")
    if not math.isfinite(args.duration) or not .2<=args.duration<=30:
        raise ValueError("Static duration must be .2–30 seconds")
    if not math.isfinite(args.gain) or not 0<=args.gain<=2:
        raise ValueError("Motion gain must be 0–2; default 1")
    if args.apple and args.still:
        raise ValueError("Apple resource export requires video; remove --still")
    if args.cover_seconds is not None and (not math.isfinite(args.cover_seconds) or args.cover_seconds<0):
        raise ValueError("Invalid cover time")
    plan = validate_scene_plan(read_json(args.plan) if args.plan else {"regions": []})
    plan = copy.deepcopy(plan)
    for region in plan["regions"]:
        region["amplitude"] = min(.02, region["amplitude"]*args.gain)
    with Image.open(args.source) as opened:
        if opened.width*opened.height > 200_000_000:
            raise ValueError("Source exceeds 200 million pixels")
        original = ImageOps.exif_transpose(opened).convert("RGB")
    selection = validate_selection(read_json(args.selection), original.size) if args.selection else None
    focus = args.focus or (selection_header_focus(selection) if selection else [.5, .5])
    caption = args.caption if args.caption is not None else (selection["caption"] if selection else "")
    with Image.open(args.art) as opened:
        art = prepare_scene(opened)
    scene = compose_equal_halves(original, art, args.width, args.height, focus, args.scale, caption)
    duration = video_info(args.live_video)[0] if args.live_video else args.duration
    if not args.still and not tool_path("ffmpeg"):
        raise RuntimeError("FFmpeg is required for video; --still creates a PNG without it")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    report = {"state": "rendering", "motion_version": MOTION_VERSION, "animation_configured": bool(plan["regions"]), "apple_verified": False,
              "phone_verified": False, "composition": scene.meta, "selection": selection, "plan": plan,
              "source_sha256": hashlib.sha256(Path(args.source).read_bytes()).hexdigest(), "duration": duration,
              "fps": args.fps, "files": {}}
    def save_report():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "report.json")
    save_report()
    try:
        art.save(output / "illustration.png")
        report["files"]["illustration"] = "illustration.png"
        if selection:
            reference, pixels = crop_reference(original, selection)
            reference.save(output / "reference.png")
            report["files"]["reference"] = "reference.png"
            report["selection_crop_pixels"] = pixels
        if args.still:
            scene.frame(0, duration, {"regions": []}).save(output / "cover.png")
            report["files"]["cover"] = "cover.png"
            report["state"] = "still_ready"
        else:
            video = output / "preview.mp4"
            pending = output / "preview-writing.mp4"
            encode(scene, plan, pending, args.fps, duration, args.live_video, focus)
            pending.replace(video)
            seconds = min(args.cover_seconds if args.cover_seconds is not None else duration/2,
                          max(0, duration-1/args.fps))
            extract_cover(video, output / "cover.jpg", seconds)
            extract_cover(video, output / "cover.png", seconds)
            report["files"].update(video="preview.mp4", cover="cover.png", apple_cover="cover.jpg")
            report["cover_seconds"] = seconds
            report["state"] = "video_ready"
            if args.apple:
                try:
                    picture, movie, checks = package_apple(output/"cover.jpg", video, output, seconds)
                    report["files"].update(apple_image=picture.relative_to(output).as_posix(), apple_video=movie.relative_to(output).as_posix())
                    report.update(state="apple_ready", apple_verified=checks["valid"], apple_checks=checks)
                except Exception as error:
                    report.update(state="apple_incomplete", apple_error=str(error))
                    save_report()
                    print(json.dumps(report, ensure_ascii=False))
                    return 2
        save_report()
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except BaseException as error:
        report.update(state="interrupted" if isinstance(error, (KeyboardInterrupt, InterruptedError)) else "failed", error=str(error))
        save_report()
        (output / "preview-writing.mp4").unlink(missing_ok=True)
        raise


def _output_folder(args, source):
    output = Path(args.out).expanduser() if args.out else source.parent/"Photo Echo"
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not output.is_dir():
        raise ValueError("Output must be a folder")
    (output/".photo-echo").mkdir(exist_ok=True)
    return output


def _reserve_name(output, source):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source.stem).strip(" .")[:100] or "Photo"
    if stem.split(".",1)[0].upper() in {"CON","PRN","AUX","NUL",*[f"{base}{i}" for base in ("COM","LPT") for i in range(1,10)]}:
        stem = "_"+stem
    reserved = output/".photo-echo/names"
    reserved.mkdir(exist_ok=True)
    existing = {p.name.casefold() for p in output.iterdir()}
    suffixes = ("_手帐.png","_手帐.mp4","_实况.JPG","_实况.MOV")
    for index in range(1,10001):
        name = stem if index==1 else f"{stem}_{index}"
        if any((name+suffix).casefold() in existing for suffix in suffixes):
            continue
        lock = reserved/(name.casefold()+".lock")
        try:
            with lock.open("x",encoding="utf-8") as file:
                file.write(source.name)
            return name, lock
        except FileExistsError:
            continue
    raise ValueError("Too many identically named inputs")


def _publish(output, cache, name, record):
    candidates = [("cover","_手帐.png"),("video","_手帐.mp4"),
                  ("apple_image","_实况.JPG"),("apple_video","_实况.MOV")]
    pending, installed = [], []
    try:
        for key,suffix in candidates:
            relative = record.get("files",{}).get(key)
            if not relative:
                continue
            source = (cache/relative).resolve()
            if not source.is_relative_to(cache.resolve()) or not source.is_file():
                raise ValueError("Completed result is missing or outside its workspace")
            target = output/(name+suffix)
            if target.exists():
                raise ValueError("Result name was taken; existing files are preserved")
            stage = cache/(uuid.uuid4().hex+".publish")
            shutil.copyfile(source,stage)
            pending.append((stage,target))
        for stage,target in pending:
            try:
                os.link(stage,target)
            except FileExistsError:
                raise ValueError("Result already exists; it was not overwritten") from None
            except OSError:
                # Filesystems without hardlinks still get exclusive creation.
                with target.open("xb") as writer:
                    installed.append(target)
                    with stage.open("rb") as reader:
                        shutil.copyfileobj(reader,writer,1024*1024)
            else:
                installed.append(target)
        return [path.name for path in installed]
    except BaseException:
        for path in installed:
            path.unlink(missing_ok=True)
        raise
    finally:
        for stage,_ in pending:
            stage.unlink(missing_ok=True)


def _jobs(args):
    if args.command != "batch":
        return [{"source":str(Path(args.source).expanduser().resolve()),"art":args.art,
                 **{key:getattr(args,key) for key in ("selection","plan","live_video","caption","focus")}}]
    jobs_file = Path(args.jobs).expanduser().resolve()
    raw = read_json(jobs_file)
    if not isinstance(raw,list) or not 1<=len(raw)<=1000:
        raise ValueError("Batch requires 1–1000 photo items")
    allowed = {"source","art","selection","plan","live_video","caption","focus"}
    result = []
    for item in raw:
        if not isinstance(item,dict) or set(item)-allowed or not {"source","art"}<=set(item):
            raise ValueError("Batch item needs source and artwork; unknown settings refused")
        clean = dict(item)
        for key in ("source","art","selection","plan","live_video"):
            value = clean.get(key)
            if value is None and key not in ("source","art"):
                continue
            if not isinstance(value,str) or not value.strip():
                raise ValueError("Material paths must be nonempty strings")
            path = Path(value).expanduser()
            clean[key] = str((jobs_file.parent/path).resolve() if not path.is_absolute() else path.resolve())
        result.append(clean)
    return result


def export(args):
    """One shared result folder; intermediate files remain in its private workspace."""
    jobs = _jobs(args)
    output = _output_folder(args,Path(jobs[0]["source"]))
    summary = {"status":"processing","output":str(output),"success":0,"partial":0,"failed":0,"interrupted":0,
               "unprocessed":len(jobs),"results":[]}
    report_file = output/".photo-echo"/("batch-"+uuid.uuid4().hex+".json")
    def save_summary():
        stage=report_file.with_suffix(".tmp")
        stage.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        stage.replace(report_file)
    save_summary()
    interrupted = False
    for item in jobs:
        source = Path(item["source"])
        cache = output/".photo-echo"/uuid.uuid4().hex
        name, lock = _reserve_name(output,source)
        chosen = copy.copy(args)
        for key in ("selection","plan","live_video","caption","focus"):
            setattr(chosen,key,item.get(key))
        chosen.source,chosen.art,chosen.out = str(source),item["art"],str(cache)
        entry = {"input":source.name,"state":"failed","files":[]}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = _render_one(chosen)
            record = read_json(cache/"report.json")
            entry["files"] = _publish(output,cache,name,record)
            entry["state"] = record["state"]
            if code==2:
                summary["partial"] += 1
                entry["error"] = record.get("apple_error","Apple export incomplete")
            else:
                summary["success"] += 1
        except (KeyboardInterrupt,InterruptedError) as error:
            entry.update(state="interrupted",error=str(error) or "Processing interrupted")
            summary["interrupted"] += 1
            interrupted = True
        except Exception as error:
            summary["failed"] += 1
            entry["error"] = str(error)
        finally:
            summary["results"].append(entry)
            summary["unprocessed"] -= 1
            summary["status"] = "interrupted" if interrupted else "processing"
            lock.unlink(missing_ok=True)
            save_summary()
        if interrupted:
            break
    if not interrupted:
        summary["status"] = "complete" if not summary["failed"] and not summary["partial"] else (
            "partial" if summary["success"] or summary["partial"] else "failed")
    save_summary()
    print(json.dumps(summary,ensure_ascii=False))
    return 130 if interrupted else 2 if summary["failed"] or summary["partial"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sub = commands.add_parser("crop", help="Validate selection and save the actual AI reference")
    for name in ("source", "selection", "out"):
        sub.add_argument("--"+name, required=True)
    sub = commands.add_parser("render", help="Make one photo echo in the shared result folder")
    for name in ("source", "art"):
        sub.add_argument("--"+name, required=True)
    sub.add_argument("--out", help="Default: Photo Echo folder beside the input photo")
    for name in ("selection", "plan", "live-video", "caption"):
        sub.add_argument("--"+name)
    sub.add_argument("--width", type=int, default=1080)
    sub.add_argument("--height", type=int, default=1440)
    sub.add_argument("--fps", type=int, default=30)
    sub.add_argument("--duration", type=float, default=3)
    sub.add_argument("--focus", type=float, nargs=2)
    sub.add_argument("--scale", type=float, default=1)
    sub.add_argument("--gain", type=float, default=1)
    sub.add_argument("--cover-seconds", type=float)
    sub.add_argument("--still", action="store_true")
    sub.add_argument("--apple", action="store_true")
    sub = commands.add_parser("batch", help="Internal helper: one photo group, one result folder")
    sub.add_argument("--jobs",required=True,help="Agent-prepared material list; paths relative to this file")
    sub.add_argument("--out",help="Default: Photo Echo folder beside the first input photo")
    for name,typ,default in (("width",int,1080),("height",int,1440),("fps",int,30),
                             ("duration",float,3),("scale",float,1),("gain",float,1)):
        sub.add_argument("--"+name,type=typ,default=default)
    sub.add_argument("--cover-seconds",type=float)
    sub.add_argument("--still",action="store_true")
    sub.add_argument("--apple",action="store_true")
    args = parser.parse_args()
    try:
        return crop(args) if args.command == "crop" else export(args)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
