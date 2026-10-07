"""Continuous local deformation with feathered displacement, not image crossfade."""
import math
import numpy as np
import cv2
from PIL import Image
from .animation import region_mask, validate_plan

VERSION = "continuous-local-motion-1"


def _smooth(value):
    value = np.clip(value, 0, 1)
    return value*value*(3-2*value)


def local_motion(art, plan, seconds, duration=3):
    if not math.isfinite(seconds) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("动画时间无效")
    clean = validate_plan(plan or {})
    if len(clean["regions"]) > 2:
        raise ValueError("最多两个局部区域")
    for region in clean["regions"]:
        if region["type"] not in {"float", "wave"} or region["amplitude"]>.02:
            raise ValueError("只支持小幅局部摆动和水纹")
        area = region["w"]*region["h"]
        if "strokes" in region:
            extents = [(max(0,x-s["radius"]),max(0,y-s["radius"]),
                        min(1,x+s["radius"]),min(1,y+s["radius"]))
                       for s in region["strokes"] for x,y in s["points"]]
            if not extents:
                raise ValueError("运动画笔没有有效笔迹")
            area = (max(e[2] for e in extents)-min(e[0] for e in extents))*(max(e[3] for e in extents)-min(e[1] for e in extents))
        if area>.3:
            raise ValueError("运动区域过大，不能移动整幅小景")
    source_u8 = np.asarray(art.convert("RGBA"))
    if not clean["regions"]:
        return art.copy()
    height, width = source_u8.shape[:2]
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    phase = 2*math.pi*(seconds/duration % 1)
    if abs(phase)<1e-10:
        return art.copy()
    # A single shared protection field also covers intersecting regions.
    protected = np.zeros((height, width), np.float32)
    for region in clean["regions"]:
        if region.get("protect"):
            protected = np.maximum(protected, region_mask({"x":0,"y":0,"w":1,"h":1,
                "strokes":region["protect"]}, width, height))
    protection_free = protected < .05
    protection_distance = cv2.distanceTransform(protection_free.astype(np.uint8), cv2.DIST_L2, 5)
    mx, my = np.zeros_like(xx), np.zeros_like(yy)
    support = np.zeros_like(xx, dtype=bool)
    for index, region in enumerate(clean["regions"]):
        left, top = region["x"]*width, region["y"]*height
        rw, rh = region["w"]*width, region["h"]*height
        u, v = (xx-left)/rw, (yy-top)/rh
        inside = (u>0)&(u<1)&(v>0)&(v<1)
        edge = np.minimum(np.minimum(u,1-u),np.minimum(v,1-v))
        # Velocity/displacement tends smoothly to zero at the boundary.
        feather = _smooth(edge/.22)
        mask = region_mask(region, width, height)*feather*inside
        if protected.any():
            mask *= _smooth(protection_distance/max(2, min(rw,rh)*.12))
            mask[~protection_free] = 0
        support |= mask>1e-6
        amplitude = min(6., region["amplitude"]*min(width,height), .12*min(rw,rh))
        seed_phase = ((region.get("seed",17)*.173+index*.91)%(2*math.pi))
        if region["type"]=="wave":
            # Traveling waves: no twice-per-loop stop-and-reverse envelope.
            spatial = 3.2*math.pi*v+.55*np.sin(2*math.pi*u)+seed_phase
            dx = amplitude*(np.sin(spatial-phase)-np.sin(spatial))
            dy = amplitude*.16*(np.cos(2*math.pi*u-phase)-np.cos(2*math.pi*u))
        else:
            # Unequal branch response; roots remain pinned at the lower edge.
            flex = (1-np.clip(v,0,1))**1.5
            swing = .82*math.sin(phase)+.18*(np.sin(2*phase+seed_phase+.55*u)-np.sin(seed_phase+.55*u))
            dx = amplitude*flex*swing
            dy = amplitude*.10*flex*np.sin(phase)*(u-.5)
        mx += mask*dx
        my += mask*dy
    if not support.any():
        return art.copy()
    # Bound local strain instead of merely increasing motion until lines fold.
    gx, gy = np.gradient(mx), np.gradient(my)
    strain = float(np.sqrt(gx[0]**2+gx[1]**2+gy[0]**2+gy[1]**2).max())
    if strain>.4:
        mx *= .4/strain
        my *= .4/strain
    rgba = source_u8.astype(np.float32)/255
    alpha = rgba[...,3:4]
    premult = np.concatenate((rgba[...,:3]*alpha,alpha),axis=2)
    # Resample once. Blending two separately drawn line sets creates ghost lines.
    warped = cv2.remap(premult, xx-mx, yy-my, cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    rgb = np.divide(warped[...,:3],np.maximum(warped[...,3:4],1/255))
    result = np.clip(np.round(np.concatenate((rgb,warped[...,3:4]),axis=2)*255),0,255).astype(np.uint8)
    result[~support] = source_u8[~support]
    return Image.fromarray(result,"RGBA")
