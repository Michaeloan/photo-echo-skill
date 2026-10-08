"""Full-photo adaptive compositor with explicit legacy crop compatibility.

Original photos are contained without cropping. The canvas follows the source
aspect ratio and adjustable paper height. Existing illustrations remain reusable.
"""
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .artwork import SceneComposition, _resize_rgba

LAYOUT_VERSION = "editorial-equal-halves-1"
FULL_PHOTO_VERSION = "editorial-full-photo-1"
STYLE_VERSION = "subject-first-print-1"
PROMPT_VERSION = "handbook-subject-print-3"


def english_caption(value):
    """Legacy non-English captions are omitted rather than invented/transliterated."""
    return value.strip() if isinstance(value,str) and value.isascii() and all(32<=ord(c)<127 for c in value) else ""


def display_crop(size, target_size, focus=(.5,.5)):
    sw,sh=size;tw,th=target_size
    ratio=tw/th
    if sw/sh < ratio:
        cw,ch=float(sw),sw/ratio
    else:
        cw,ch=sh*ratio,float(sh)
    left=max(0,min(sw-cw,float(focus[0])*sw-cw/2))
    top=max(0,min(sh-ch,float(focus[1])*sh-ch/2))
    return (left,top,left+cw,top+ch)


def _weights(art):
    rgba=np.asarray(art.convert("RGBA"),dtype=np.float32)/255
    luminance=rgba[...,:3]@np.array([.2126,.7152,.0722],dtype=np.float32)
    return rgba[...,3]*(.35+.65*(1-luminance))


def _font(size,caption):
    explicit = os.environ.get("PHOTO_ECHO_FONT") or os.environ.get("LIVE_HANDBOOK_FONT")
    if explicit:
        return ImageFont.truetype(explicit,size)
    cjk = any(ord(c)>127 for c in caption)
    candidates = (["C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"] if cjk else
        ["C:/Windows/Fonts/couri.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    path = next((Path(value) for value in candidates if Path(value).is_file()), None)
    if cjk and path is None:
        raise ValueError("中文标题需要CJK字体；设置PHOTO_ECHO_FONT，或传 --caption 空标题")
    return ImageFont.truetype(str(path),size) if path else ImageFont.load_default()


def compose_equal_halves(original,art,width=1080,height=1440,header_focus=None,
                         motif_scale=1,caption="",motif_anchor=None,*,photo_height=None,full_photo=False):
    if width < 64 or height < 64 or width%2 or height%4:
        raise ValueError("上下等分画布尺寸无效")
    original=ImageOps.exif_transpose(original).convert("RGB")
    focus=header_focus or [.5,.5]
    if not isinstance(focus,(list,tuple)) or len(focus)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in focus):
        raise ValueError("照片焦点须为0至1的两个坐标")
    if type(motif_scale) not in (int,float) or not math.isfinite(motif_scale) or not .05<=motif_scale<=4:
        raise ValueError("插画大小应在5%至400%之间")
    if not isinstance(caption,str) or len(caption)>32 or any(ord(c)<32 for c in caption):
        raise ValueError("手帐标题不能超过32字或包含换行")
    half=photo_height if photo_height is not None else height//2
    if not 0 < half < height:
        raise ValueError("照片区高度无效")
    paper_h=height-half
    crop=(0,0,*original.size) if full_photo else display_crop(original.size,(width,half),focus)
    photo=(ImageOps.contain(original,(width,half),Image.Resampling.LANCZOS) if full_photo else
           original.resize((width,half),Image.Resampling.LANCZOS,box=crop))
    photo_x,photo_y=(width-photo.width)//2,(half-photo.height)//2
    rng=np.random.default_rng(720)
    grain=rng.normal(0,.32,(paper_h,width,1))
    paper=Image.fromarray(np.clip(np.round(np.array([249,248,244])+grain),0,255).astype(np.uint8),"RGB")
    page=Image.new("RGBA",(width,height),(249,248,244,255))
    page.paste(photo,(photo_x,photo_y));page.paste(paper,(0,half))
    art=art.convert("RGBA")
    weights=_weights(art);mass=float(weights.sum())
    if mass<=.01:
        raise ValueError("插画没有可见内容")
    scale=min(width*.43/art.width,paper_h*.42/art.height,math.sqrt(.045*width*paper_h/mass))*motif_scale
    # A larger user setting still stays within the paper's usable bounds.
    scale=min(scale,width*.64/art.width,paper_h*.60/art.height)
    ink=_resize_rgba(art,(max(1,round(art.width*scale)),max(1,round(art.height*scale))))
    fitted=_weights(ink);yy,xx=np.mgrid[:ink.height,:ink.width];total=float(fitted.sum())
    cx,cy=float((fitted*xx).sum()/total),float((fitted*yy).sum()/total)
    margin=max(3,round(width*84/1080));top_gap=max(3,round(paper_h*.16))
    anchor=max(.38,min(.62,focus[0] if motif_anchor is None else motif_anchor))
    ax=max(margin,min(width-margin-ink.width,round(width*anchor-cx)))
    font_size=max(6,min(round(width*18/1080),round(paper_h*.09)));text_gap=max(3,round(paper_h*.045))
    bottom_margin=max(4,round(paper_h*.10))
    ay=max(half+top_gap,min(height-ink.height-text_gap-font_size-bottom_margin,round(half+paper_h*.55-cy)))
    ty=ay+ink.height+text_gap
    tx=ax
    if caption:
        font=_font(font_size,caption);draw=ImageDraw.Draw(page)
        # Short headlines at very small preview sizes are fitted, never cropped.
        while draw.textbbox((0,0),caption,font=font)[2] > width-2*margin and font_size>5:
            font_size-=1;font=_font(font_size,caption)
        tw=draw.textbbox((0,0),caption,font=font)[2]
        tx=max(margin,min(width-margin-tw,round(ax+cx-tw/2)))
        draw.text((tx,ty),caption,font=font,fill=(111,108,103,255))
    sw,sh=original.size
    meta={"layout_version":FULL_PHOTO_VERSION if full_photo else LAYOUT_VERSION,"canvas":[width,height],
          "original_rect":[photo_x,photo_y,photo.width,photo.height],
          "paper_rect":[0,half,width,paper_h],"art_rect":[ax,ay,*ink.size],"split":half/height,
          "outer_frame":False,"photo_full_bleed":photo.width==width and photo.height==half,"source_size":[sw,sh],
          "header_crop_pixels":list(crop),"header_crop_normalized":[crop[0]/sw,crop[1]/sh,crop[2]/sw,crop[3]/sh],
          "header_focus":list(focus),"motif_scale":motif_scale,"caption":caption,"caption_position":[tx,ty],
          "photo_complete":full_photo,"aspect_policy":"完整原图等比缩放，画布比例随原图及留白高度变化" if full_photo else "固定窗口等比裁切"}
    return SceneComposition(page,ink,meta)


def full_photo_size(size,width=1080,paper_ratio=2/3):
    """Adapt the canvas, not the photograph; round only for video encoding."""
    sw,sh=size
    if sw<=0 or sh<=0 or type(width) not in (int,float) or not math.isfinite(width) or not 64<=width<=2160:
        raise ValueError("自由比例画布尺寸无效")
    if type(paper_ratio) not in (int,float) or not math.isfinite(paper_ratio) or not .1<=paper_ratio<=3:
        raise ValueError("插画区高度须为画布宽度的10%至300%")
    scale=min(1,2880/(width*(sh/sw+paper_ratio)))
    w=max(64,int(width*scale)//2*2)
    paper_h=max(20,round(w*paper_ratio))
    photo_h=max(2,min(2880-paper_h,round(w*sh/sw)))
    h=max(64,min(2880,(photo_h+paper_h+3)//4*4))
    return w,h,photo_h


def compose_full_photo(original,art,width=1080,paper_ratio=2/3,motif_scale=1,caption="",caption_language="english",height=None):
    original=ImageOps.exif_transpose(original).convert("RGB")
    w,h,photo_h=full_photo_size(original.size,width,paper_ratio)
    if height is not None:
        if type(height) is not int or not 64<=height<=2880 or height%4:
            raise ValueError("Explicit canvas height must be 64–2880 and divisible by four")
        w,h=int(width)//2*2,height
        photo_h=h-min(h-2,max(20,round(w*paper_ratio)))
    if caption_language not in ("english","original"):
        raise ValueError("Unknown caption language policy")
    caption=english_caption(caption) if caption_language=="english" else caption
    composition=compose_equal_halves(original,art,w,h,[.5,.5],motif_scale,caption,
                                     photo_height=photo_h,full_photo=True)
    composition.meta["paper_ratio"]=paper_ratio
    composition.meta["canvas_policy"]="explicit" if height is not None else "adaptive"
    return composition
