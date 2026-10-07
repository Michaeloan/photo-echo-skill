"""Meaningful local invariants using synthetic images. Never calls a model."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from handbook_core.animation import validate_scene_plan
from handbook_core.artwork import prepare_scene
from handbook_core.editorial import compose_equal_halves
from handbook_core.media import run, tool_path, video_info
from handbook_core.selection import validate_selection, crop_reference
from render_handbook import encode, main, read_json


class HandbookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.art = Image.new("RGBA", (160, 140))
        ImageDraw.Draw(self.art).ellipse((25, 25, 125, 110), fill=(20, 95, 140, 220))
        self.selection = {"mode": "subject", "primary_box": [.2, .2, .2, .2],
            "crop_box": [.1, .1, .6, .6], "expanded": False, "reason": "tree and water",
            "subject": "tree", "caption": "quiet water"}
    def tearDown(self):
        self.temporary.cleanup()
    def test_selection_rejects_unsafe_json_and_crop_preserves_metadata_free_reference(self):
        for raw in ('{"mode":"subject","mode":"scene"}', '{"crop_box":[NaN,0,1,1]}'):
            with self.assertRaises(ValueError):
                validate_selection(raw)
        photo = Image.new("RGB", (300, 200), "green")
        photo.info["description"] = "private source note"
        reference, pixels = crop_reference(photo, self.selection)
        self.assertEqual(pixels, (30, 20, 210, 140))
        self.assertEqual(reference.size, (180, 120))
        self.assertFalse(reference.info)
        self.assertEqual(photo.size, (300, 200))
    def test_photo_and_paper_stay_fixed_while_art_local_region_moves(self):
        photo = Image.new("RGB", (180, 120), (25, 90, 150))
        scene = compose_equal_halves(photo, self.art, 180, 240)
        plan = validate_scene_plan({"regions":[{"type":"wave","x":.2,"y":.2,"w":.4,"h":.4,"amplitude":.018}]})
        first, middle = np.array(scene.frame(0, 3, plan)), np.array(scene.frame(.75, 3, plan))
        self.assertTrue(np.array_equal(first[:120], np.array(photo)))
        self.assertTrue(np.array_equal(first[:120], middle[:120]))
        self.assertTrue(np.array_equal(first[121:140], middle[121:140]))
        self.assertFalse(np.array_equal(first[140:], middle[140:]))
        self.assertEqual(scene.meta["paper_rect"], [0, 120, 180, 120])
        self.assertFalse(scene.meta["outer_frame"])
    def test_portrait_display_crop_has_correct_ratio_and_focus(self):
        photo = Image.new("RGB", (100, 300), "red")
        ImageDraw.Draw(photo).rectangle((0, 150, 99, 299), fill="blue")
        scene = compose_equal_halves(photo, self.art, 180, 240, [.5, 1])
        x0, y0, x1, y1 = scene.meta["header_crop_pixels"]
        self.assertAlmostEqual((x1-x0)/(y1-y0), 1.5)
        self.assertEqual(scene.frame().getpixel((0, 0)), (0, 0, 255))
    def test_alpha_is_preserved_and_colored_background_refused(self):
        art = prepare_scene(self.art)
        self.assertLess(np.array(art.getchannel("A")).min(), 255)
        with self.assertRaises(ValueError):
            prepare_scene(Image.new("RGB", (100, 100), "green"))
    def test_large_or_particle_motion_rejected_before_any_tools(self):
        for region in (
            {"type":"particles","x":0,"y":0,"w":.2,"h":.2},
            {"type":"wave","x":0,"y":0,"w":.9,"h":.9},
            {"type":"wave","x":0,"y":0,"w":.2,"h":.2,"amplitude":.03},
        ):
            plan = self.root / "bad-plan.json"
            plan.write_text(json.dumps({"regions":[region]}), encoding="utf-8")
            argv = ["render_handbook.py", "render", "--source", "nonexistent.jpg", "--art", "nonexistent.png",
                    "--plan", str(plan), "--out", str(self.root/"out")]
            with patch.object(sys, "argv", argv), patch("render_handbook.tool_path", side_effect=AssertionError("tools must not run")):
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 1)
            self.assertFalse((self.root/"out").exists())
    def test_still_export_does_not_need_ffmpeg_and_refuses_overwrite(self):
        source, art, output = self.root/"source.png", self.root/"art.png", self.root/"result"
        Image.new("RGB", (120, 80), "blue").save(source)
        self.art.save(art)
        argv = ["render_handbook.py","render","--source",str(source),"--art",str(art),
                "--out",str(output),"--still","--width","120","--height","160"]
        with patch.object(sys, "argv", argv), patch("render_handbook.tool_path", side_effect=AssertionError("still must not probe")):
            self.assertEqual(main(), 0)
        report = read_json(output/"report.json")
        self.assertEqual(report["state"], "still_ready")
        self.assertFalse(report["animation_configured"])
        self.assertTrue((output/"cover.png").is_file())
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit):
                main()
    def test_real_heic_is_decoded_by_standalone_cli(self):
        source, art, output = self.root/"source.heic", self.root/"art.png", self.root/"heic-result"
        Image.new("RGB", (120, 80), "blue").save(source, format="HEIF")
        self.art.save(art)
        argv = ["render_handbook.py","render","--source",str(source),"--art",str(art),
                "--out",str(output),"--still","--width","120","--height","160"]
        with patch.object(sys, "argv", argv):
            self.assertEqual(main(), 0)
        report = read_json(output/"report.json")
        self.assertEqual(report["composition"]["source_size"], [120,80])
        self.assertEqual(report["state"], "still_ready")
    def test_native_live_preserves_audio_duration_and_fills_top(self):
        if not tool_path("ffmpeg") or not tool_path("ffprobe"):
            self.skipTest("ffprobe unavailable; other local checks still run")
        source, target = self.root/"source.mov", self.root/"result.mp4"
        run([tool_path("ffmpeg"),"-y","-v","error","-f","lavfi","-i","color=c=blue:s=80x160:r=10",
             "-f","lavfi","-i","sine=frequency=440:sample_rate=44100","-t","1","-c:v","libx264",
             "-threads","2","-pix_fmt","yuv420p","-c:a","aac",source])
        scene = compose_equal_halves(Image.new("RGB",(80,160),"red"),self.art,120,160)
        encode(scene, {"regions":[]}, target, 10, 1, source, [.5,1])
        duration, info = video_info(target)
        self.assertAlmostEqual(duration,1,places=1)
        self.assertTrue(any(s["codec_type"]=="audio" for s in info["streams"]))
        raw = run([tool_path("ffmpeg"),"-v","error","-threads","1","-i",target,"-frames:v","1",
                   "-f","rawvideo","-pix_fmt","rgb24","-threads","1","pipe:1"])
        frame = np.frombuffer(raw,np.uint8).reshape(160,120,3)
        for y,x in ((3,3),(3,116),(76,3),(76,116)):
            r,g,b = frame[y,x].astype(int)
            self.assertGreater(b, r+100)


if __name__ == "__main__":
    unittest.main()
