"""Bounded, deterministic asset-local masks."""
import math
import cv2
import numpy as np
from PIL import Image, ImageDraw
ALLOWED = {"float", "wave"}

def number(value, name, lo, hi, default):
    try:
        value = float(default if value is None else value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} 必须为数字") from None
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} 应在 {lo} 到 {hi} 之间")
    return value


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("运动计划必须为对象")
    regions = plan.get("regions", [])
    if not isinstance(regions, list) or len(regions) > 2:
        raise ValueError("最多两个局部运动区域")
    clean = []
    for region in regions:
        if not isinstance(region, dict) or region.get("type", region.get("effect")) not in ALLOWED:
            raise ValueError("只支持局部摆动和水纹")
        if "mask" in region or "script" in region or "code" in region:
            raise ValueError("运动计划不能包含文件路径或代码")
        r = {"type": region.get("type", region.get("effect")),
             "x": number(region.get("x"), "x", 0, 1, 0),
             "y": number(region.get("y"), "y", 0, 1, 0),
             "w": number(region.get("w"), "w", .001, 1, 1),
             "h": number(region.get("h"), "h", .001, 1, 1),
             "amplitude": number(region.get("amplitude"), "amplitude", 0, .2, .02),
             "seed": int(number(region.get("seed"), "seed", 0, 2**31-1, 17))}
        if r["x"] + r["w"] > 1.000001 or r["y"] + r["h"] > 1.000001:
            raise ValueError("运动区域超出插画")
        for key in ("strokes", "protect"):
            if key not in region:
                continue
            strokes = region[key]
            if not isinstance(strokes, list) or len(strokes) > 1000:
                raise ValueError("画笔笔迹数量超限")
            r[key] = []
            for stroke in strokes:
                points = stroke.get("points", [])
                if not isinstance(points, list) or len(points) > 10000:
                    raise ValueError("画笔点数超限")
                radius = number(stroke.get("radius"), "radius", .001, .5, .05)
                r[key].append({"radius": radius, "points": [[number(p[0], "point x", 0, 1, 0),
                    number(p[1], "point y", 0, 1, 0)] for p in points if len(p) == 2]})
        clean.append(r)
    return {"regions": clean, "version": 1}


def region_mask(region, width, height):
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    if "strokes" not in region:
        draw.rectangle((region["x"]*width, region["y"]*height,
            (region["x"]+region["w"])*width, (region["y"]+region["h"])*height), fill=255)
    for key, color in (("strokes", 255), ("protect", 0)):
        for stroke in region.get(key, []):
            radius = stroke["radius"] * min(width, height)
            points = [(p[0]*width, p[1]*height) for p in stroke["points"]]
            if len(points) > 1:
                draw.line(points, fill=color, width=max(1, round(2*radius)))
            for x, y in points:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    data = np.asarray(mask, dtype=np.float32)/255
    # A small feather keeps rigid region edges from visibly tearing.
    return cv2.GaussianBlur(data, (0, 0), max(.5, min(width, height)/240))


def validate_scene_plan(plan):
    """Reject unsupported effects and whole-scene motion for the small scene."""
    clean = validate_plan(plan)
    if len(clean["regions"]) > 2:
        raise ValueError("精简小场景最多两个局部运动区域")
    for region in clean["regions"]:
        if region["type"] not in ("float", "wave"):
            raise ValueError("精简小场景只支持叶端轻摆或水面短线，不添加粒子")
        area = region["w"]*region["h"]
        if "strokes" in region:
            # Brush plans use an enclosing rectangle, often the whole asset.
            # Assess the actual brush footprint rather than rejecting that box.
            extents = [(max(0, x-s["radius"]), max(0, y-s["radius"]),
                        min(1, x+s["radius"]), min(1, y+s["radius"]))
                       for s in region["strokes"] for x, y in s["points"]]
            if not extents:
                raise ValueError("局部运动画笔没有有效笔迹")
            area = (max(e[2] for e in extents)-min(e[0] for e in extents))*(
                    max(e[3] for e in extents)-min(e[1] for e in extents))
        if area > .3:
            raise ValueError("运动区域过大，请只选择叶端或水面短线，不能移动整幅小场景")
        if region["amplitude"] > .02:
            raise ValueError("精简小场景运动幅度不能超过 0.02")
    return clean
