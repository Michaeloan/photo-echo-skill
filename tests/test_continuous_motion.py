"""Local motion geometry invariants, no external models or media required."""
import unittest
import numpy as np
from PIL import Image, ImageDraw
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from handbook_core.continuous_motion import local_motion


class ContinuousMotionTests(unittest.TestCase):
    def setUp(self):
        self.art = Image.new("RGBA",(180,160))
        draw=ImageDraw.Draw(self.art)
        draw.line((90,25,90,135),fill=(30,90,140,255),width=2)
        draw.line((40,98,145,100),fill=(20,120,150,180),width=2)
        self.region={"type":"wave","x":.25,"y":.35,"w":.5,"h":.5,"amplitude":.02}
    def test_loop_is_exact_and_original_input_not_mutated(self):
        before=self.art.tobytes()
        first=local_motion(self.art,{"regions":[self.region]},0)
        last=local_motion(self.art,{"regions":[self.region]},3)
        self.assertEqual(first.tobytes(),before)
        self.assertEqual(first.tobytes(),last.tobytes())
        self.assertEqual(self.art.tobytes(),before)
    def test_pixels_outside_region_and_protected_stem_are_exact(self):
        region={**self.region,"protect":[{"radius":.025,"points":[[.5,.2],[.5,.85]]}]}
        first=np.array(self.art)
        moving=np.array(local_motion(self.art,{"regions":[region]},.9))
        allowed=np.zeros(first.shape[:2],bool)
        allowed[56:136,45:135]=True
        self.assertTrue(np.array_equal(first[~allowed],moving[~allowed]))
        self.assertTrue(np.array_equal(first[70:120,88:93],moving[70:120,88:93]))
        self.assertFalse(np.array_equal(first,moving))
    def test_warped_line_has_one_connected_stroke_without_crossfade_ghost(self):
        region={"type":"wave","x":.25,"y":.2,"w":.5,"h":.55,"amplitude":.02}
        rgba=np.array(local_motion(self.art,{"regions":[region]},.75))
        for y in (60,70,80):
            foreground=np.flatnonzero(rgba[y,:,3]>40)
            self.assertGreater(len(foreground),0)
            self.assertEqual(foreground[-1]-foreground[0]+1,len(foreground))
            self.assertLessEqual(len(foreground),4)
    def test_half_cycle_does_not_force_all_water_to_return_to_neutral(self):
        moving=local_motion(self.art,{"regions":[self.region]},1.5)
        self.assertNotEqual(moving.tobytes(),self.art.tobytes())
    def test_unsupported_or_whole_scene_motion_rejected_even_at_loop_start(self):
        for region in ({**self.region,"type":"particles"},{**self.region,"w":1,"h":1,"x":0,"y":0},
                       {**self.region,"amplitude":.1}):
            with self.assertRaises(ValueError):
                local_motion(self.art,{"regions":[region]},0)


if __name__=="__main__":unittest.main()
