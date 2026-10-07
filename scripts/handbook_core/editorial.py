"""Generic production compositor for the approved equal-halves handbook.

The source photograph fills the top rectangle. Only a local display crop is
used; retained photographic pixels are never sent back for AI repainting.
"""
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .artwork import SceneComposition, _resize_rgba

LAYOUT_VERSION = "editorial-equal-halves-1"
STYLE_VERSION = "subject-first-print-1"
PROMPT_VERSION = "handbook-subject-print-3"


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
                         motif_scale=1,caption="",motif_anchor=None):
    if width < 64 or height < 64 or width%2 or height%4:
        raise ValueError("上下等分画布尺寸无效")
    original=ImageOps.exif_transpose(original).convert("RGB")
    focus=header_focus or [.5,.5]
    if not isinstance(focus,(list,tuple)) or len(focus)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in focus):
        raise ValueError("照片焦点须为0至1的两个坐标")
    if type(motif_scale) not in (int,float) or not math.isfinite(motif_scale) or not .7<=motif_scale<=1.3:
        raise ValueError("插画大小应在70%至130%之间")
    if not isinstance(caption,str) or len(caption)>32 or any(ord(c)<32 for c in caption):
        raise ValueError("手帐标题不能超过32字或包含换行")
    half=height//2
    crop=display_crop(original.size,(width,half),focus)
    photo=original.resize((width,half),Image.Resampling.LANCZOS,box=crop)
    rng=np.random.default_rng(720)
    grain=rng.normal(0,.32,(half,width,1))
    paper=Image.fromarray(np.clip(np.round(np.array([249,248,244])+grain),0,255).astype(np.uint8),"RGB")
    page=Image.new("RGBA",(width,height))
    page.paste(photo,(0,0));page.paste(paper,(0,half))
    art=art.convert("RGBA")
    weights=_weights(art);mass=float(weights.sum())
    if mass<=.01:
        raise ValueError("插画没有可见内容")
    scale=min(width*.43/art.width,half*.42/art.height,math.sqrt(.045*width*half/mass))*motif_scale
    # A larger user setting still stays within the paper's usable bounds.
    scale=min(scale,width*.64/art.width,half*.60/art.height)
    ink=_resize_rgba(art,(max(1,round(art.width*scale)),max(1,round(art.height*scale))))
    fitted=_weights(ink);yy,xx=np.mgrid[:ink.height,:ink.width];total=float(fitted.sum())
    cx,cy=float((fitted*xx).sum()/total),float((fitted*yy).sum()/total)
    margin=max(3,round(width*84/1080));top_gap=max(3,round(half*.16))
    anchor=max(.38,min(.62,focus[0] if motif_anchor is None else motif_anchor))
    ax=max(margin,min(width-margin-ink.width,round(width*anchor-cx)))
    font_size=max(6,round(width*18/1080));text_gap=max(3,round(half*.045))
    bottom_margin=max(4,round(half*.10))
    ay=max(half+top_gap,min(height-ink.height-text_gap-font_size-bottom_margin,round(half+half*.55-cy)))
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
    meta={"layout_version":LAYOUT_VERSION,"canvas":[width,height],"original_rect":[0,0,width,half],
          "paper_rect":[0,half,width,half],"art_rect":[ax,ay,*ink.size],"split":.5,
          "outer_frame":False,"photo_full_bleed":True,"source_size":[sw,sh],
          "header_crop_pixels":list(crop),"header_crop_normalized":[crop[0]/sw,crop[1]/sh,crop[2]/sw,crop[3]/sh],
          "header_focus":list(focus),"motif_scale":motif_scale,"caption":caption,"caption_position":[tx,ty]}
    return SceneComposition(page,ink,meta)
