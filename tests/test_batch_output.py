"""User-facing grouping, source-name mapping, partial results and no overwrites."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from render_handbook import main, _publish, _reserve_name


class BatchOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.sources=self.root/"photos";self.sources.mkdir()
        self.art=self.root/"art.png"
        art=Image.new("RGBA",(100,80))
        ImageDraw.Draw(art).ellipse((20,10,80,65),fill=(20,110,140,210))
        art.save(self.art)
    def tearDown(self):self.tmp.cleanup()
    def picture(self,name,folder=None):
        folder=folder or self.sources
        folder.mkdir(parents=True,exist_ok=True)
        image=folder/name
        Image.new("RGB",(120,80),"#168a9b").save(image)
        return image
    def invoke(self,*argv):
        with patch.object(sys,"argv",["render_handbook.py",*argv]),contextlib.redirect_stdout(io.StringIO()) as output:
            code=main()
        return code,json.loads(output.getvalue())
    def manifest(self,jobs):
        path=self.root/"jobs.json"
        path.write_text(json.dumps(jobs,ensure_ascii=False),encoding="utf-8")
        return path
    def test_default_one_folder_beside_inputs_with_source_names(self):
        a,b=self.picture("湖湾.png"),self.picture("树影.jpg")
        before={p:p.read_bytes() for p in (a,b)}
        manifest=self.manifest([{"source":str(p),"art":str(self.art)} for p in (a,b)])
        code,summary=self.invoke("batch","--jobs",str(manifest),"--still","--width","120","--height","160")
        self.assertEqual(code,0)
        output=self.sources/"Photo Echo"
        self.assertEqual(Path(summary["output"]),output.resolve())
        self.assertEqual({p.name for p in output.iterdir() if p.is_file()},{"湖湾_手帐.png","树影_手帐.png"})
        self.assertEqual(summary["success"],2)
        self.assertEqual(len(list(output.glob("*/report.json"))),0)
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)
    def test_sources_in_different_folders_and_identical_stems_stay_together(self):
        a=self.picture("same.jpg")
        b=self.picture("same.png",self.root/"other")
        manifest=self.manifest([{"source":str(p),"art":str(self.art)} for p in (a,b)])
        code,summary=self.invoke("batch","--jobs",str(manifest),"--still")
        output=self.sources/"Photo Echo"
        self.assertEqual(code,0)
        self.assertTrue((output/"same_手帐.png").is_file())
        self.assertTrue((output/"same_2_手帐.png").is_file())
        self.assertFalse((b.parent/"Photo Echo").exists())
    def test_relative_manifest_paths_and_failed_item_do_not_block_other_photos(self):
        a=self.picture("good.png")
        manifest=self.manifest([{"source":"missing.png","art":"art.png"},
            {"source":str(a.relative_to(self.root)),"art":"art.png"}])
        output=self.root/"result"
        code,summary=self.invoke("batch","--jobs",str(manifest),"--out",str(output),"--still")
        self.assertEqual(code,2)
        self.assertEqual(summary["status"],"partial")
        self.assertEqual((summary["success"],summary["failed"],summary["unprocessed"]),(1,1,0))
        self.assertEqual({p.name for p in output.iterdir() if p.is_file()},{"good_手帐.png"})
    def test_single_focus_survives_shared_output_wrapper(self):
        source=self.sources/"portrait.png"
        image=Image.new("RGB",(100,300),"red")
        ImageDraw.Draw(image).rectangle((0,150,99,299),fill="blue");image.save(source)
        code,summary=self.invoke("render","--source",str(source),"--art",str(self.art),
            "--focus",".5","1","--still","--width","120","--height","160")
        self.assertEqual(code,0)
        with Image.open(Path(summary["output"])/"portrait_手帐.png") as result:
            self.assertEqual(result.getpixel((0,0)),(0,0,255))
    def test_publication_rolls_back_partial_new_files_without_overwriting_existing(self):
        output=self.root/"result";output.mkdir()
        cache=self.root/"cache";cache.mkdir()
        (cache/"cover.png").write_bytes(b"cover")
        (cache/"video.mp4").write_bytes(b"video")
        (output/"old.png").write_bytes(b"keep")
        import render_handbook
        link=render_handbook.os.link
        def collision(source,target):
            if Path(target).suffix==".mp4":raise FileExistsError("collision")
            return link(source,target)
        with patch("render_handbook.os.link",side_effect=collision):
            with self.assertRaises(ValueError):
                _publish(output,cache,"photo",{"files":{"cover":"cover.png","video":"video.mp4"}})
        self.assertEqual({p.name for p in output.iterdir()},{"old.png"})
        self.assertEqual((output/"old.png").read_bytes(),b"keep")
    def test_cancel_preserves_completed_photo_and_reports_remaining(self):
        pictures=[self.picture(f"{i}.png") for i in range(3)]
        manifest=self.manifest([{"source":str(p),"art":str(self.art)} for p in pictures])
        import render_handbook
        original=render_handbook._render_one
        count=0
        def stop(args):
            nonlocal count
            count+=1
            if count==2:raise KeyboardInterrupt()
            return original(args)
        with patch("render_handbook._render_one",side_effect=stop):
            code,summary=self.invoke("batch","--jobs",str(manifest),"--still")
        self.assertEqual(code,130)
        self.assertEqual(summary["status"],"interrupted")
        self.assertEqual((summary["success"],summary["unprocessed"]),(1,1))
        self.assertEqual(summary["interrupted"],1)
        self.assertEqual({p.name for p in Path(summary["output"]).iterdir() if p.is_file()},{"0_手帐.png"})


if __name__=="__main__":unittest.main()
