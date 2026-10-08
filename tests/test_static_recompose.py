"""Observable static-first behavior and quota-free adjustment of saved batches."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import render_handbook
from render_handbook import main,read_json
from handbook_core.editorial import compose_full_photo


class StaticRecomposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.art=self.root/"art.png"
        image=Image.new("RGBA",(100,80),(0,0,0,0))
        ImageDraw.Draw(image).ellipse((25,20,75,60),fill=(30,100,140,210))
        image.save(self.art)
        self.source=self.root/"portrait.png"
        pixels=np.zeros((240,120,3),np.uint8)
        pixels[:120,:,0]=220;pixels[120:,:,2]=180
        Image.fromarray(pixels).save(self.source)
        self.out=self.root/"result"

    def tearDown(self):self.tmp.cleanup()

    def invoke(self,*argv):
        with patch.object(sys,"argv",["photo_echo.py",*argv]),contextlib.redirect_stdout(io.StringIO()) as log:
            code=main()
        return code,json.loads(log.getvalue())

    def render(self,*extra):
        return self.invoke("render","--source",str(self.source),"--art",str(self.art),"--out",str(self.out),*extra)

    def latest(self):
        return max((read_json(p) for p in (self.out/".photo-echo").glob("*/report.json")),key=lambda r:r["created_at"])

    def test_default_is_only_png_no_video_probe_or_encoding(self):
        with patch("render_handbook.tool_path",side_effect=AssertionError("no media tools")), \
             patch("render_handbook.video_info",side_effect=AssertionError("no video probe")), \
             patch("render_handbook.encode",side_effect=AssertionError("no encoding")):
            code,summary=self.render("--live-video",str(self.root/"missing.mov"))
        self.assertEqual(code,0)
        self.assertEqual([p.name for p in self.out.iterdir() if p.is_file()],["portrait_手帐.png"])
        self.assertEqual(summary["success"],1)
        record=self.latest()
        self.assertTrue(record["composition"]["photo_complete"])
        self.assertEqual(record["composition"]["header_crop_normalized"],[0,0,1,1])

    def test_default_output_keeps_both_ends_of_portrait(self):
        self.render("--width","120","--focus",".5","1")
        record=self.latest();x,y,w,h=record["composition"]["original_rect"]
        with Image.open(self.out/"portrait_手帐.png") as image,Image.open(self.source) as source:
            self.assertEqual(image.crop((x,y,x+w,y+h)).tobytes(),source.resize((w,h),Image.Resampling.LANCZOS).tobytes())

    def test_square_landscape_and_portrait_get_different_canvas_ratios(self):
        art=Image.open(self.art)
        canvases=[]
        for size in ((120,240),(240,120),(160,160)):
            scene=compose_full_photo(Image.new("RGB",size,"red"),art,180)
            self.assertEqual(scene.meta["header_crop_pixels"],[0,0,*size])
            canvases.append(scene.page.size)
        self.assertEqual(len(set(canvases)),3)
        art.close()

    def test_explicit_canvas_still_contains_the_complete_source(self):
        self.render("--width","120","--height","160")
        record=self.latest()
        self.assertEqual(record["composition"]["canvas"],[120,160])
        self.assertEqual(record["composition"]["canvas_policy"],"explicit")
        self.assertEqual(record["composition"]["header_crop_normalized"],[0,0,1,1])
        self.assertEqual(record["composition"]["original_rect"][2:],[40,80])

    def test_jpg_and_transparent_png_illustration_are_separate_choices(self):
        code,_=self.render("--image-kind","both","--image-format","jpg")
        self.assertEqual(code,0)
        self.assertEqual({p.suffix for p in self.out.iterdir() if p.is_file()},{".jpg"})
        self.assertEqual(len(list(self.out.glob("*.jpg"))),2)
        code,_=self.render("--image-kind","illustration")
        self.assertEqual(code,0)
        file=next(self.out.glob("*_插画.png"))
        with Image.open(file) as image:
            self.assertEqual(image.mode,"RGBA")
            self.assertEqual(image.getpixel((0,0))[3],0)

    def test_static_ignores_old_invalid_motion_plan(self):
        plan=self.root/"bad-motion.json"
        plan.write_text('{"regions":[{"type":"particles"}]}',encoding="utf-8")
        with patch("render_handbook.validate_scene_plan",side_effect=AssertionError("static must skip motion analysis")):
            code,_=self.render("--plan",str(plan))
        self.assertEqual(code,0)
        self.assertFalse(self.latest()["animation_configured"])

    def test_english_or_blank_and_explicit_language_override(self):
        self.render("--caption","静水")
        self.assertEqual(self.latest()["composition"]["caption"],"")
        self.render("--caption","Quiet water")
        self.assertEqual(self.latest()["composition"]["caption"],"Quiet water")

    def test_recompose_works_after_original_inputs_are_moved_and_does_not_overwrite(self):
        self.render("--caption","Quiet water","--width","180")
        old=(self.out/"portrait_手帐.png").read_bytes()
        self.source.rename(self.root/"moved-photo.png")
        self.art.rename(self.root/"moved-art.png")
        with patch("render_handbook.tool_path",side_effect=AssertionError("no remote or video dependency")):
            code,summary=self.invoke("recompose","--from-output",str(self.out),"--paper-ratio",".45","--scale",".9")
        self.assertEqual(code,0)
        self.assertEqual(summary["success"],1)
        self.assertEqual((self.out/"portrait_手帐.png").read_bytes(),old)
        self.assertTrue((self.out/"portrait_2_手帐.png").is_file())
        record=self.latest()
        self.assertEqual(record["composition"]["caption"],"Quiet water")
        self.assertEqual(record["settings"]["paper_ratio"],.45)
        self.assertEqual(record["settings"]["scale"],.9)

    def test_recompose_retains_each_photo_settings_and_can_select_one(self):
        second=self.root/"wide.png";Image.new("RGB",(240,120),"blue").save(second)
        jobs=self.root/"jobs.json"
        jobs.write_text(json.dumps([{"source":str(self.source),"art":str(self.art),"scale":.8,"paper_ratio":.4,"caption":"Quiet water"},
            {"source":str(second),"art":str(self.art),"scale":1.2,"paper_ratio":.9,"caption":"Open sky"}]),encoding="utf-8")
        self.invoke("batch","--jobs",str(jobs),"--out",str(self.out))
        code,summary=self.invoke("recompose","--from-output",str(self.out))
        self.assertEqual((code,summary["success"]),(0,2))
        saved={r["input_name"]:r for r in sorted((read_json(p) for p in (self.out/".photo-echo").glob("*/report.json")),key=lambda r:r["created_at"])}
        self.assertEqual(saved["portrait.png"]["settings"]["scale"],.8)
        self.assertEqual(saved["wide.png"]["settings"]["scale"],1.2)
        self.assertEqual(saved["wide.png"]["settings"]["paper_ratio"],.9)
        code,summary=self.invoke("recompose","--from-output",str(self.out),"--select","portrait.png","--caption","New light")
        self.assertEqual((code,summary["success"]),(0,1))
        self.assertEqual(summary["results"][0]["input"],"portrait.png")
        self.assertEqual(len(list(self.out.glob("wide*_手帐.png"))),2)
        self.assertEqual(self.latest()["composition"]["caption"],"New light")

    def test_one_missing_saved_artwork_does_not_block_other_completed_photos(self):
        second=self.root/"wide.png";Image.new("RGB",(240,120),"blue").save(second)
        jobs=self.root/"jobs.json"
        jobs.write_text(json.dumps([{"source":str(source),"art":str(self.art)} for source in (self.source,second)]),encoding="utf-8")
        self.invoke("batch","--jobs",str(jobs),"--out",str(self.out))
        for path in (self.out/".photo-echo").glob("*/report.json"):
            record=read_json(path)
            if record["input_name"]=="portrait.png":
                (path.parent/record["art_snapshot"]).unlink()
        code,summary=self.invoke("recompose","--from-output",str(self.out))
        self.assertEqual(code,2)
        self.assertEqual((summary["success"],summary["failed"]),(1,1))
        self.assertTrue((self.out/"wide_2_手帐.png").is_file())

    def test_legacy_crop_recomposes_to_adaptive_complete_photo(self):
        self.render("--layout","legacy-crop","--width","120","--height","160")
        self.assertFalse(self.latest()["composition"]["photo_complete"])
        code,_=self.invoke("recompose","--from-output",str(self.out))
        self.assertEqual(code,0)
        record=self.latest()
        self.assertTrue(record["composition"]["photo_complete"])
        self.assertEqual(record["composition"]["canvas_policy"],"adaptive")
        self.assertEqual(record["composition"]["canvas"],[120,320])

    def test_zip_contains_only_this_runs_selected_static_result(self):
        self.render()
        code,summary=self.invoke("recompose","--from-output",str(self.out),"--image-format","jpg","--zip")
        self.assertEqual(code,0)
        with zipfile.ZipFile(summary["zip"]) as archive:
            self.assertEqual(len(archive.namelist()),1)
            self.assertTrue(archive.namelist()[0].endswith('.jpg'))
            self.assertFalse(any('.photo-echo' in n for n in archive.namelist()))

    def test_original_live_video_keeps_complete_frame_and_audio(self):
        from handbook_core.media import tool_path,run,video_info
        if not tool_path("ffmpeg") or not tool_path("ffprobe"):
            self.skipTest("optional native Live tools unavailable")
        movie=self.root/"source.mov"
        run([tool_path("ffmpeg"),"-y","-v","error","-f","lavfi","-i",
             "color=c=blue:s=80x160:r=10,drawbox=x=0:y=0:w=iw:h=80:color=red:t=fill",
             "-f","lavfi","-i","sine=frequency=440:sample_rate=44100","-t","0.4",
             "-c:v","libx264","-threads","2","-pix_fmt","yuv420p","-c:a","aac",movie])
        code,_=self.render("--video","--live-video",str(movie),"--width","120","--fps","10")
        self.assertEqual(code,0)
        record=self.latest();w,h=record["composition"]["canvas"]
        target=self.out/"portrait_手帐.mp4"
        duration,info=video_info(target)
        self.assertAlmostEqual(duration,.4,places=1)
        self.assertTrue(any(s["codec_type"]=="audio" for s in info["streams"]))
        raw=run([tool_path("ffmpeg"),"-v","error","-i",target,"-frames:v","1","-an","-f","rawvideo","-pix_fmt","rgb24","pipe:1"])
        frame=np.frombuffer(raw,np.uint8).reshape(h,w,3)
        x,y,pw,ph=record["composition"]["original_rect"]
        red=frame[y+4,x+4].astype(int);blue=frame[y+ph-5,x+pw-5].astype(int)
        self.assertGreater(red[0],red[2]+100)
        self.assertGreater(blue[2],blue[0]+100)


if __name__=="__main__":unittest.main()
