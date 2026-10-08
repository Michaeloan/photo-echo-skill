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
import time
import zipfile

from PIL import Image, ImageOps
import pillow_heif
pillow_heif.register_heif_opener()
from handbook_core.animation import validate_scene_plan
from handbook_core.artwork import prepare_scene
from handbook_core.editorial import compose_equal_halves, compose_full_photo, english_caption
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
        if scene.meta.get("photo_complete"):
            x,y,pw,ph=scene.meta["original_rect"]
            filters=(f"[1:v]{tone}scale={pw}:{ph}:force_original_aspect_ratio=decrease,format=rgba,"
                f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=0xf9f8f4,setsar=1[top];"
                f"[0:v][top]overlay={x}:{y}:shortest=1[out]")
        else:
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
    if args.layout not in ("full-photo","legacy-crop") or args.image_kind not in ("handbook","illustration","both") or args.image_format not in ("png","jpg"):
        raise ValueError("Unsupported layout or static export choice")
    if type(args.still) is not bool or type(args.apple) is not bool or args.caption_language not in ("english","original"):
        raise ValueError("Unsupported output mode or caption policy")
    if type(args.width) is not int or not 64<=args.width<=2160:
        raise ValueError("Canvas outside supported size")
    if args.width%2 or not 10<=args.fps<=60:
        raise ValueError("Width must be even; height divisible by four; FPS 10–60")
    if args.layout=="legacy-crop" and args.height is None:
        args.height=1440
    if args.height is not None and (type(args.height) is not int or not 64<=args.height<=2880 or args.height%4):
        raise ValueError("Explicit height must be 64–2880 and divisible by four")
    if args.layout=="legacy-crop" and (type(args.height) is not int or not 64<=args.height<=2880 or args.height%4):
        raise ValueError("Explicit legacy crop needs a valid --height")
    if not math.isfinite(args.duration) or not .2<=args.duration<=30:
        raise ValueError("Static duration must be .2–30 seconds")
    if not math.isfinite(args.gain) or not 0<=args.gain<=2:
        raise ValueError("Motion gain must be 0–2; default 1")
    if args.apple and args.still:
        raise ValueError("Apple resource export requires video; remove --still")
    if args.cover_seconds is not None and (not math.isfinite(args.cover_seconds) or args.cover_seconds<0):
        raise ValueError("Invalid cover time")
    plan = {"regions": []} if args.still else validate_scene_plan(read_json(args.plan) if args.plan else {"regions": []})
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
    if args.caption_language=="english":
        caption=english_caption(caption)
    scene = (compose_full_photo(original,art,args.width,args.paper_ratio,args.scale,caption,args.caption_language,height=args.height) if args.layout=="full-photo" else
             compose_equal_halves(original, art, args.width, args.height, focus, args.scale, caption))
    duration = video_info(args.live_video)[0] if args.live_video and not args.still else args.duration
    if not args.still and not tool_path("ffmpeg"):
        raise RuntimeError("FFmpeg is required for video; --still creates a PNG without it")
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    settings={key:getattr(args,key) for key in ("width","height","layout","paper_ratio","scale","gain","fps","duration",
        "cover_seconds","still","apple","image_kind","image_format","caption_language")}
    report = {"state": "rendering", "motion_version": MOTION_VERSION, "animation_configured": bool(plan["regions"]), "apple_verified": False,
              "phone_verified": False, "composition": scene.meta, "selection": selection, "plan": plan,
              "source_sha256": hashlib.sha256(Path(args.source).read_bytes()).hexdigest(), "duration": duration,
              "fps": args.fps, "files": {}, "settings":settings, "input_name":args.input_name,
              "job_id":args.job_id, "created_at":time.time()}
    def save_report():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "report.json")
    save_report()
    try:
        source_copy=output/("source"+Path(args.source).suffix.lower())
        shutil.copyfile(args.source,source_copy)
        raw_art=output/("art-original"+Path(args.art).suffix.lower())
        shutil.copyfile(args.art,raw_art)
        report.update(source_snapshot=source_copy.name,art_snapshot=raw_art.name)
        if args.plan and Path(args.plan).is_file():
            shutil.copyfile(args.plan,output/"motion-original.json")
            report["plan_snapshot"]="motion-original.json"
        if args.live_video:
            report["live_video_source"]=str(Path(args.live_video).resolve())
        if args.live_video and not args.still:
            movie=output/("source-live"+Path(args.live_video).suffix.lower())
            shutil.copyfile(args.live_video,movie)
            report["live_video_snapshot"]=movie.name
        art.save(output / "illustration.png")
        report["files"]["illustration"] = "illustration.png"
        if selection:
            reference, pixels = crop_reference(original, selection)
            reference.save(output / "reference.png")
            report["files"]["reference"] = "reference.png"
            report["selection_crop_pixels"] = pixels
            (output/"selection.json").write_text(json.dumps(selection,ensure_ascii=False),encoding="utf-8")
            report["selection_snapshot"]="selection.json"
        if args.still:
            if args.image_kind in ("handbook","both"):
                frame=scene.frame(0,duration,{"regions":[]})
                filename="cover."+args.image_format
                frame.save(output/filename,"PNG" if args.image_format=="png" else "JPEG",**({"quality":95,"subsampling":0} if args.image_format=="jpg" else {}))
                report["files"]["cover"]=filename
            if args.image_kind in ("illustration","both"):
                filename="art-export."+args.image_format
                if args.image_format=="jpg":
                    flattened=Image.new("RGBA",art.size,"white");flattened.alpha_composite(art)
                    flattened.convert("RGB").save(output/filename,"JPEG",quality=95,subsampling=0)
                else:
                    Image.frombytes("RGBA",art.size,art.tobytes()).save(output/filename,"PNG")
                report["files"]["art_export"]=filename
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
    suffixes = ("_手帐.png","_手帐.jpg","_插画.png","_插画.jpg","_手帐.mp4","_实况.JPG","_实况.MOV")
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
    image_format=record.get("settings",{}).get("image_format","png")
    if record.get("state")!="still_ready":
        image_format="png"
    candidates = [("cover","_手帐."+image_format),("art_export","_插画."+image_format),("video","_手帐.mp4"),
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
    if args.command == "recompose":
        return _saved_jobs(args)
    if args.command != "batch":
        return [{"source":str(Path(args.source).expanduser().resolve()),"art":args.art,
                 **{key:getattr(args,key) for key in ("selection","plan","live_video","caption","focus")}}]
    jobs_file = Path(args.jobs).expanduser().resolve()
    raw = read_json(jobs_file)
    if not isinstance(raw,list) or not 1<=len(raw)<=1000:
        raise ValueError("Batch requires 1–1000 photo items")
    allowed = {"source","art","selection","plan","live_video","caption","focus","name",
               "width","height","layout","paper_ratio","scale","gain","fps","duration","cover_seconds",
               "still","apple","image_kind","image_format","caption_language"}
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


def _saved_jobs(args):
    """Find latest successful settings for each input, reusing saved material."""
    output=Path(args.from_output).expanduser().resolve()
    latest={}
    for path in (output/".photo-echo").glob("*/report.json"):
        record=read_json(path)
        if record.get("state") not in ("still_ready","video_ready","apple_ready","apple_incomplete"):
            continue
        if not all(record.get(key) for key in ("source_snapshot","art_snapshot","job_id","input_name")):
            continue
        cache=path.parent.resolve()
        def asset(key):
            if not record.get(key):
                return None
            resolved=(cache/record[key]).resolve()
            if not resolved.is_relative_to(cache):
                raise ValueError("Saved material is outside its workspace")
            return str(resolved)
        job={**record.get("settings",{}),"source":asset("source_snapshot"),"art":asset("art_snapshot"),
             "selection":None,"plan":asset("plan_snapshot"),
             "live_video":asset("live_video_snapshot") or record.get("live_video_source"),
             "caption":record.get("composition",{}).get("caption",""),"name":record["input_name"],
             "_job_id":record["job_id"],"_created":record.get("created_at",0)}
        # Recomposition starts with the current full-photo still workflow;
        # dimensions, paper height, caption and art scale stay per-photo.
        for key in ("layout","still","apple"):
            job.pop(key,None)
        if record.get("settings",{}).get("layout")=="legacy-crop":
            job.pop("height",None)
        previous=latest.get(record["job_id"])
        if previous is None or job["_created"]>previous["_created"]:
            latest[record["job_id"]]=job
    jobs=sorted(latest.values(),key=lambda job:job["_created"])
    if args.select:
        chosen=set(args.select)
        matched=set()
        selected=[]
        for job in jobs:
            labels={job["name"],Path(job["name"]).stem,job["_job_id"]}
            if chosen & labels:
                selected.append(job);matched.update(chosen & labels)
        if chosen-matched:
            raise ValueError("Some selected inputs have no completed reusable artwork")
        jobs=selected
    if not jobs:
        raise ValueError("No reusable completed batch found; supply the existing source/art paths as a batch")
    return jobs


def _zip_results(output,files):
    target=output.with_suffix(output.suffix+".zip")
    for index in range(2,10001):
        if not target.exists():
            break
        target=output.with_name(output.name+f"_{index}.zip")
    else:
        raise ValueError("Too many existing ZIP exports")
    temporary=target.with_name(target.name+"."+uuid.uuid4().hex+".writing")
    created=False
    try:
        with zipfile.ZipFile(temporary,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name in files:
                path=(output/name).resolve()
                if not path.is_relative_to(output.resolve()) or not path.is_file():
                    raise ValueError("Export result is missing or outside the output folder")
                archive.write(path,name)
        with target.open("xb") as outgoing, temporary.open("rb") as incoming:
            created=True
            shutil.copyfileobj(incoming,outgoing,1024*1024)
        return str(target)
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def export(args):
    """One shared result folder; intermediate files remain in its private workspace."""
    jobs = _jobs(args)
    if args.command=="recompose" and not args.out:
        args.out=args.from_output
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
        input_name=item.get("name",source.name)
        if not isinstance(input_name,str) or Path(input_name).name!=input_name or not input_name:
            raise ValueError("Input name must be a single filename")
        name, lock = _reserve_name(output,Path(input_name))
        chosen = copy.copy(args)
        defaults={"width":1080,"height":None,"layout":"full-photo","paper_ratio":2/3,"scale":1,
                  "gain":1,"fps":30,"duration":3,"cover_seconds":None,"still":True,"apple":False,
                  "image_kind":"handbook","image_format":"png","caption_language":"english"}
        for key,value in defaults.items():
            override=getattr(args,key,None)
            setattr(chosen,key,override if override is not None else item.get(key,value))
        if chosen.apple and getattr(args,"still",None) is None and "still" not in item:
            chosen.still=False
        for key in ("selection","plan","live_video","caption","focus"):
            setattr(chosen,key,getattr(args,key,None) if getattr(args,key,None) is not None else item.get(key))
        chosen.source,chosen.art,chosen.out = str(source),item["art"],str(cache)
        chosen.input_name=input_name
        chosen.job_id=item.get("_job_id") or hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:24]
        entry = {"input":input_name,"job_id":chosen.job_id,"workspace":cache.relative_to(output).as_posix(),"state":"failed","files":[]}
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
        files=[name for entry in summary["results"] for name in entry["files"]]
        if args.zip and files:
            summary["zip"]=_zip_results(output,files)
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
    sub.add_argument("--focus", type=float, nargs=2)
    render_options(sub)
    for command in ("batch","recompose"):
        sub=commands.add_parser(command,help="Make or adjust a shared photo batch without regenerating illustrations")
        if command=="batch":
            sub.add_argument("--jobs",required=True,help="Agent-prepared material list; paths relative to this file")
        else:
            sub.add_argument("--from-output",required=True,help="An existing Photo Echo result folder")
            sub.add_argument("--select",nargs="+",help="Optional original filenames, stems or saved job IDs")
        sub.add_argument("--out",help="One shared result folder")
        sub.add_argument("--caption",help="English caption or an empty string; explicit override for the selected items")
        render_options(sub)
    args = parser.parse_args()
    try:
        return crop(args) if args.command == "crop" else export(args)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


def render_options(parser):
    for name,typ in (("width",int),("height",int),("fps",int),("duration",float),
                     ("scale",float),("gain",float),("paper-ratio",float),("cover-seconds",float)):
        parser.add_argument("--"+name,type=typ,default=None)
    parser.add_argument("--layout",choices=("full-photo","legacy-crop"),default=None,
                        help="Default: complete photo, automatic canvas; legacy crop only when explicitly requested")
    parser.add_argument("--image-kind",choices=("handbook","illustration","both"),default=None)
    parser.add_argument("--image-format",choices=("png","jpg"),default=None)
    parser.add_argument("--caption-language",choices=("english","original"),default=None,
                        help="Default: English or blank; original language only on explicit request")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--still",dest="still",action="store_true")
    mode.add_argument("--video",dest="still",action="store_false")
    parser.set_defaults(still=None)
    parser.add_argument("--apple",action="store_true",default=None)
    parser.add_argument("--zip",action="store_true",help="Also save a ZIP containing only this run's selected results")


if __name__ == "__main__":
    raise SystemExit(main())
