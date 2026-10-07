"""Original scene preparation and continuous asset-local animation."""
from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from .continuous_motion import local_motion as continuous_local_motion
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

def local_motion(art, plan, seconds, duration=3):
    return continuous_local_motion(art, plan, seconds, duration)

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
