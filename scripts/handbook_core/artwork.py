"""Prepare small scene layers and keep motion inside their masks."""
from dataclasses import dataclass
import math
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from .animation import region_mask, validate_plan
MAX_SCENE_PIXELS = 8_000_000

def prepare_scene(image):
    """Preserve genuine alpha; gently unmatte clean paper without hard ink cuts.

    Background is estimated from corners. Only border-connected near-background
    pixels are definitely removed; faint enclosed strokes remain translucent.
    This is a conservative preparation helper, not semantic segmentation.
    """
    if image.width*image.height > MAX_SCENE_PIXELS:
        raise ValueError("小场景原稿不能超过800万像素，请先缩小插画原稿；原照片无需缩小")
    image = ImageOps.exif_transpose(image).convert("RGBA")
    data = np.asarray(image).astype(np.float32)
    if data[..., 3].min() >= 254:
        rgb = data[..., :3]
        h, w = rgb.shape[:2]
        corner = max(1, min(h, w)//20)
        samples = np.concatenate([rgb[:corner, :corner].reshape(-1, 3),
            rgb[:corner, -corner:].reshape(-1, 3), rgb[-corner:, :corner].reshape(-1, 3),
            rgb[-corner:, -corner:].reshape(-1, 3)])
        paper = np.median(samples, axis=0)
        # Refuse to treat a colored/photographic background as white paper.
        if np.min(paper) < 225 or np.max(np.std(samples, axis=0)) > 12:
            raise ValueError("插画底色不均匀或不是浅白底，请保留原稿并检查，不能自动抠成贴纸")
        distance = np.max(np.abs(rgb-paper), axis=2)
        threshold = max(.8, min(2.5, float(np.percentile(np.max(np.abs(samples-paper), axis=1), 90))+.5))
        eligible = (distance <= threshold).astype(np.uint8)
        _, labels = cv2.connectedComponents(eligible, connectivity=8)
        border_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        border_labels = border_labels[border_labels != 0]
        background = np.isin(labels, border_labels)
        alpha = np.clip(distance/45, 0, 1)
        alpha[background] = 0
        # Unmatte avoids carrying a white halo onto the ivory local paper.
        safe_alpha = np.maximum(alpha[..., None], 1/255)
        unmatte = (rgb-paper*(1-alpha[..., None]))/safe_alpha
        data[..., :3] = np.clip(unmatte, 0, 255)
        data[..., 3] = alpha*255
        image = Image.fromarray(np.round(data).astype(np.uint8), "RGBA")
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("原稿没有可见的小场景")
    # Retain breathing room, including the softest strokes, not a >12 cutoff.
    pad = max(2, min(image.size)//80)
    x0, y0, x1, y1 = bounds
    return image.crop((max(0, x0-pad), max(0, y0-pad),
                       min(image.width, x1+pad), min(image.height, y1+pad)))


def _resize_rgba(image, size):
    # Pillow RGBa uses premultiplied alpha, preventing dark fringe interpolation.
    return image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def _protect_mask(region, width, height):
    image = Image.new("L", (width, height))
    draw = ImageDraw.Draw(image)
    for stroke in region.get("protect", []):
        radius = stroke["radius"]*min(width, height)
        points = [(x*width, y*height) for x, y in stroke["points"]]
        if len(points) > 1:
            draw.line(points, fill=255, width=max(1, round(radius*2)))
        for x, y in points:
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    return np.asarray(image) > 0


def local_motion(art, plan, seconds, duration=3):
    """Only move approved asset-local pixels; never move the whole paper/scene."""
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(seconds):
        raise ValueError("动画时间无效")
    plan = validate_plan(plan or {})
    if not plan["regions"]:
        return art.copy()
    source = np.asarray(art.convert("RGBA")).astype(np.float32)/255
    alpha = source[..., 3:4]
    premult = np.concatenate([source[..., :3]*alpha, alpha], axis=2)
    out = premult.copy()
    h, w = out.shape[:2]
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    phase = 2*math.pi*(seconds/duration % 1)
    # Green protection is global to the scene, even where two effects overlap.
    protected = np.zeros((h, w), dtype=bool)
    for region in plan["regions"]:
        protected |= _protect_mask(region, w, h)
    for region in plan["regions"]:
        if region["type"] not in {"wave", "float"}:
            raise ValueError("当前小场景只支持局部水纹或轻摆，不添加无来源粒子")
        mask = region_mask(region, w, h)
        # Keep all pixels outside the requested rectangle exact, even after feathering.
        inside = ((xx >= region["x"]*w) & (xx < (region["x"]+region["w"])*w)
                  & (yy >= region["y"]*h) & (yy < (region["y"]+region["h"])*h))
        mask *= inside
        mask[protected] = 0
        amplitude = min(3.0, region["amplitude"]*min(w, h))
        if region["type"] == "wave":
            dx = np.sin(yy/max(1, h)*math.pi*4+phase)*math.sin(phase)*amplitude
            dy = np.zeros_like(dx)
        else:
            # Anchored in space: the region's root remains still.
            anchor = np.clip((yy-region["y"]*h)/max(1, region["h"]*h), 0, 1)
            dx = math.sin(phase)*amplitude*(1-anchor)**2
            dy = np.zeros_like(dx)
        changed = cv2.remap(premult, xx-dx, yy-dy, cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        out = out*(1-mask[..., None])+changed*mask[..., None]
    rgb = np.divide(out[..., :3], np.maximum(out[..., 3:4], 1/255))
    straight = np.concatenate([rgb, out[..., 3:4]], axis=2)
    return Image.fromarray(np.clip(np.round(straight*255), 0, 255).astype(np.uint8), "RGBA")


@dataclass(frozen=True)
class SceneComposition:
    """Pre-fitted original and art, reused for every frame of an export."""
    page: Image.Image
    art: Image.Image
    meta: dict

    def frame(self, seconds=0, duration=3, plan=None):
        moving = local_motion(self.art, plan, seconds, duration)
        page = self.page.copy()
        x, y, _, _ = self.meta["art_rect"]
        page.alpha_composite(moving, (x, y))
        return page.convert("RGB")
