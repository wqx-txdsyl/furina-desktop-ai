"""NIGHT-01 Art Alpha tooling (standalone — imports nothing from furina/, no backend changes).

Subcommands:
    generate --ids a01,a02   img2img generate raw candidates via Agnes (magenta background)
    process  --ids all       chroma-key -> transparent RGBA, normalize canvas, measure anchors
    sheet    --ids all       build side-by-side comparison sheets (candidate vs BASE)
    manifest                 rebuild metadata/manifest_v2.json from per-asset metadata files
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "data" / "assets_v2"
BASE = V2 / "_base" / "furina-base.png"
RAW = V2 / "raw"
CAND = V2 / "review" / "candidates"
REVIEW = V2 / "review"
META = V2 / "metadata"
MASTERS = V2 / "masters"

API = "https://apihub.agnes-ai.com/v1/images/generations"
MODEL = "agnes-image-2.1-flash"

CANVAS_W, CANVAS_H = 1024, 1536
BASELINE_Y = 1468  # ground contact line
CENTER_X = 512

# ------------------------------------------------------------------ prompts

IDENTITY_LOCK = """Furina from Genshin Impact, premium chibi anime illustration, extreme 2.2-heads-tall chibi proportions: her head is nearly half of her total height, with a tiny short body, very short arms and stubby short legs. Near-white hair with pale ice-blue inner shading and light sky-blue accent streaks, voluminous wavy bob, full jagged fringe over the eyebrows, one thick curved ahoge hooking to the left, long wavy pale-blue side tail flowing down past the hip on HER LEFT side (appearing on the RIGHT side of the image when she faces the viewer). Large deep-blue eyes with top-down gradient iris (deep blue to pale cyan) and bright dual highlights, thin light eyebrows, tiny low mouth, small pointed chin, soft round cheeks. Dark navy top hat worn tilted to her left, decorated with gold crown ornaments, hanging teardrop blue gems, white frilled ornament and blue gem pin. Navy swallowtail jacket with white shirt inset, two gold buttons, blue ascot pinned by one large round blue gem brooch, dark blue gloves, large blue back bow, white shorts, blue-white striped hem trim, dark thigh strap with hanging teardrop gem on her right thigh, light-blue ruffled sock covers over navy shoes. Same character design in every image."""

STYLE_LOCK = """Clean hard-cel anime shading, flat fills, one hard shadow per form with hue-shifted blue shadow tones, crisp uniform dark blue-gray outlines, geometric white highlights, medium-high saturation, closed navy-and-ice-blue color palette, gold accents only on small ornaments. High-quality anime sticker-grade finish, 2D flat illustration."""

CAMERA_LOCK = """Full-body shot, eye-level camera, mild telephoto flattening, no perspective distortion, character centered and filling about ninety percent of the frame height, entire silhouette visible including hat top and shoe soles, nothing cropped."""

TRANSPARENCY_LOCK = """The entire background must be one solid flat bright magenta #FF00FF color with no gradient, no vignette, no darker shading, no room, no floor, no furniture, no shadow on the ground, no props other than her cane, no watermark, no text, no border — a flat magenta cutout sheet."""

NEGATIVE_BLOCK = ("realistic proportions, tall body, long legs, small head, normal proportions, non-chibi, "
    "oversized head beyond chibi, toddler, "
    "photorealistic, 3D render, Nendoroid figure, painterly brush strokes, watercolor, sketch lines, "
    "thick outline western cartoon, extra ahoge, missing ahoge, straight untilted hat, missing hat, "
    "alt costume, dress replacing jacket, missing brooch, missing thigh strap, simplified costume, "
    "different hair color, saturated all-blue hair, huge eyes, gradient background, colored environment, "
    "dark background, purple background, vignette, indoor background, "
    "bloom, glow, rim light, text, watermark, cropped feet, cropped hat, multiple characters, "
    "extra characters, hands with five detailed fingers, hair tail on the wrong side, mirrored hair, "
    "long hair tail on her right side")

# id: (semantic_state, action_block, expression_block, gaze_block, target_content_height_px)
ASSETS = {
    "a01": ("stand_neutral_front",
        "Standing straight facing the viewer, relaxed shoulders, her right hand holding her cane at her side, her left hand resting open at her side.",
        "Neutral calm expression, soft brows, small gentle closed-mouth smile.", "Looking at the viewer.", 1408),
    "a02": ("stand_neutral_slight_left",
        "Standing facing the viewer, body and head turned very slightly toward her right (viewer's left), cane at her side.",
        "Neutral calm expression, soft brows, small closed-mouth smile.", "Looking at the viewer.", 1408),
    "a03": ("stand_neutral_slight_right",
        "Standing facing the viewer, body and head turned very slightly toward her left (viewer's right), long side tail visible on her left, cane at her side.",
        "Neutral calm expression, soft brows, small closed-mouth smile.", "Looking at the viewer.", 1408),
    "a04": ("stand_relaxed_idle",
        "Standing in a relaxed idle pose, weight shifted to one hip, shoulders loose, one hand holding the cane lightly.",
        "Relaxed at-ease expression, soft brows, faint content smile.", "Looking at the viewer.", 1408),
    "a05": ("stand_confident_proud",
        "Standing tall with her chin slightly lifted, one hand on her hip, the other holding the cane like a scepter, theatrical proud stance.",
        "Confident proud expression, one brow slightly raised, small knowing smirk.", "Looking at the viewer.", 1408),
    "a06": ("stand_gentle_happy",
        "Standing facing the viewer with both hands loosely clasped in front of her waist near the cane.",
        "Gently happy expression, soft raised brows, warm open smile showing a hint of teeth.", "Looking at the viewer.", 1408),
    "a07": ("stand_annoyed",
        "Standing with her arms folded, cane hooked in the crook of her elbow, chin slightly turned away.",
        "Mildly offended expression, brows tilted inward, small pout, cheeks slightly puffed.", "Looking away slightly, toward her right.", 1408),
    "a08": ("stand_embarrassed",
        "Standing caught off guard, leaning back a little, both hands raised slightly in front of her chest, cane dangling from her right wrist by its ribbon.",
        "Embarrassed flustered expression, wide eyes, small open mouth, light blush on her cheeks.", "Looking at the viewer.", 1408),
    "a09": ("stand_curious_leaning",
        "Standing while leaning her upper body slightly forward with both hands behind her back, cane tucked under one arm, head tilted a little.",
        "Curious attentive expression, raised brows, small interested open mouth.", "Looking at the viewer.", 1408),
    "a10": ("stand_sleepy",
        "Standing with drooping shoulders, her head tilted down and to one side, both hands holding the cane in front of her like a walking stick.",
        "Sleepy low-energy expression, eyelids half lowered, mouth a tiny sleepy shape.", "Looking down, eyelids heavy.", 1408),
    "a11": ("sit_floor",
        "Sitting on the ground with her legs folded together to one side, hands resting on her lap around the cane laid across her knees.",
        "Calm expression, relaxed brows, gentle small closed-mouth smile.", "Looking at the viewer.", 1024),
    "a12": ("walk_key_pose",
        "Mid-step walking pose, one foot forward just touching the ground, arms swinging naturally, her right hand holding the cane.",
        "Pleasant neutral expression, soft brows, small smile.", "Looking ahead at the viewer.", 1408),
    "a13": ("pet_response",
        "Standing while leaning her head slightly into an unseen hand petting her hair, eyes softened, one hand raised near the hand.",
        "Pleased melting expression, eyes soft and half-closed, small happy smile, faint blush.", "Looking slightly upward.", 1408),
    "a14": ("poke_response",
        "Standing and twisting slightly away from an unseen poke at her side, shoulders raised, one hand jumping toward her waist, cane in the other hand.",
        "Surprised mild protest expression, brows raised, small round open mouth, light blush.", "Looking at the viewer.", 1408),
    "a15": ("lifted_drag_response",
        "Lifted into the air under the arms by an unseen grip, legs dangling, toes pointed, cane slipping from her hand still attached by a ribbon to her wrist.",
        "Startled protest expression, wide eyes, small open mouth, faint blush.", "Looking at the viewer.", 1152),
    "a16": ("work_focused",
        "Seated at an unseen writing slope, leaning forward and writing on a paper with a feather quill, her cane leaning beside her, fully absorbed in the task.",
        "Focused working expression, brows drawn in concentration, mouth a small firm line.", "Looking down at the paper.", 1152),
    "a17": ("speak_presenting",
        "Standing with one hand raised palm-up in a presentational gesture at chest height, the other holding the cane like an orator, chin lifted.",
        "Speaking expression, mouth open mid-sentence and articulate, animated confident brows.", "Looking at the viewer.", 1408),
    "a18": ("stand_quiet_reflective",
        "Standing still with both hands wrapped around the head of her cane in front of her, gaze lowered, posture quiet and contained.",
        "Quiet reflective expression, neutral brows, small thoughtful closed mouth.", "Looking slightly downward, past the viewer.", 1408),
    "a19": ("eating",
        "Sitting and holding a small dessert cake with both hands, taking a small bite, cane set beside her.",
        "Delighted small expression, happy raised brows, mouth occupied with a small bite, faint blush.", "Looking at the dessert.", 1024),
    "a20": ("playing",
        "Standing mid-playful twirl on one foot, skirt-like coattails flaring, one hand holding her hat, the other out for balance, cane left aside out of frame.",
        "Playful joyful expression, bright eyes, open happy smile.", "Looking at the viewer.", 1408),
}


def build_prompt(asset_id: str) -> str:
    sem, action, expr, gaze, _h = ASSETS[asset_id]
    return (TRANSPARENCY_LOCK + " " + IDENTITY_LOCK + " " + STYLE_LOCK + " " + CAMERA_LOCK + " "
            + action + " " + expr + " " + gaze)


# ------------------------------------------------------------------ generate

def api_key() -> str:
    key = os.environ.get("AGNES_API_KEY", "")
    if key:
        return key
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("AGNES_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def generate(ids: list[str], seed_base: int = 20260827, bump: int = 0) -> None:
    key = api_key()
    if not key:
        sys.exit("AGNES_API_KEY not found — cannot generate")
    init = data_uri(BASE)
    with httpx.Client(timeout=360.0) as http:
        for aid in ids:
            sem, action, expr, gaze, _h = ASSETS[aid]
            prompt = build_prompt(aid)
            seed = seed_base + int(aid[1:]) + bump * 1000
            payload = {
                "model": MODEL, "prompt": prompt, "size": "2K", "ratio": "2:3",
                "seed": seed,
                "extra_body": {"image": [init], "response_format": "b64_json"},
            }
            t0 = time.time()
            r = http.post(API, headers={"Authorization": f"Bearer {key}",
                                        "Content-Type": "application/json"}, json=payload)
            print(f"[{aid}] HTTP {r.status_code} in {time.time()-t0:.1f}s")
            r.raise_for_status()
            item = r.json()["data"][0]
            if item.get("b64_json"):
                img = Image.open(io.BytesIO(base64.b64decode(item["b64_json"])))
            else:
                dl = http.get(item["url"]); dl.raise_for_status()
                img = Image.open(io.BytesIO(dl.content))
            out = RAW / f"{aid}_{sem}_seed{seed}.png"
            img.save(out)
            prov = {
                "asset_id": aid, "semantic_state": sem, "model": MODEL, "seed": seed,
                "size": "2K", "ratio": "2:3", "mode": "img2img",
                "init_image": str(BASE.relative_to(ROOT)),
                "init_image_md5": hashlib.md5(BASE.read_bytes()).hexdigest(),
                "prompt_md5": hashlib.md5(prompt.encode()).hexdigest(),
                "action_block": action, "expression_block": expr, "gaze_block": gaze,
                "negative_prompt": NEGATIVE_BLOCK,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "raw_file": out.name, "revised_prompt": item.get("revised_prompt"),
            }
            (RAW / f"{aid}_{sem}_seed{seed}.prov.json").write_text(
                json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[{aid}] saved {out.name} {img.size}")


# ------------------------------------------------------------------ process

def key_magenta(img: Image.Image) -> Image.Image:
    """Hue-based magenta matte: kill anything in the magenta family (r>g and b>g),
    feather 1px, despill the boundary. Character palette never has r&b above g."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mn = np.minimum(r, b)
    rel = (mn - g) / np.maximum(mn, 1.0)
    mag = (r - g > 20) & (b - g > 20)
    alpha = np.where(mag, np.clip((0.30 - rel) / 0.15, 0.0, 1.0), 1.0)
    # 1px dilation of the killed area to erode the magenta fringe
    dead = alpha < 0.1
    dil = dead.copy()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        dil |= np.roll(np.roll(dead, dy, axis=0), dx, axis=1)
    alpha = alpha * (~dil)
    # despill surviving boundary pixels
    spill = mag & (alpha > 0)
    g2 = np.where(spill, np.maximum(g, mn * 0.85), g)
    out = np.zeros(a.shape[:2] + (4,), dtype=np.uint8)
    out[..., 0] = np.clip(r, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(g2, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(b, 0, 255).astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def normalize(img: Image.Image, target_h: int) -> tuple[Image.Image, dict]:
    """Crop to content, scale to target content height, place baseline & center-x."""
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("fully transparent after keying")
    content = img.crop(bbox)
    scale = target_h / content.height
    new_size = (max(1, round(content.width * scale)), target_h)
    content = content.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    px = CENTER_X - content.width // 2
    py = BASELINE_Y - content.height
    canvas.paste(content, (px, py), content)
    anchors = {
        "anchor_x": round((px + content.width / 2) / CANVAS_W, 4),
        "anchor_y": round(BASELINE_Y / CANVAS_H, 4),
        "content_px": [px, py, content.width, content.height],
        "scale_from_raw": round(scale, 4),
    }
    return canvas, anchors


def process(ids: list[str]) -> None:
    CAND.mkdir(parents=True, exist_ok=True)
    for aid in ids:
        sem, _a, _e, _g, target_h = ASSETS[aid]
        raws = sorted(RAW.glob(f"{aid}_{sem}_*.png"))
        if not raws:
            print(f"[{aid}] no raw file, skip")
            continue
        raw = raws[-1]
        prov = json.loads(raw.with_suffix(".prov.json").read_text(encoding="utf-8"))
        keyed = key_magenta(Image.open(raw))
        canvas, geo = normalize(keyed, target_h)
        out = CAND / f"furina_v2_{aid}_{sem}.png"
        canvas.save(out)
        meta = {
            "asset_id": f"furina_v2_{aid}_{sem}",
            "alpha_id": aid,
            "category": "POSTURE",
            "semantic_state": sem,
            "canvas_width": CANVAS_W, "canvas_height": CANVAS_H,
            "ground_baseline_y": BASELINE_Y,
            "geometry": geo,
            "contact": "feet_ground" if "stand" in sem or "walk" in sem else
                       "sit_surface" if "sit" in sem or "eating" in sem else
                       "drag_midair" if "lift" in sem else "task_contact",
            "loop": False, "interruptible": True,
            "source_generation": prov,
            "base_identity_version": "furina-base-2026-08",
            "style_version": "FURINA-STYLE-LOCK-V2",
            "review_status": "PENDING", "review_notes": "",
            "candidate_file": str(out.relative_to(ROOT)),
        }
        (CAND / f"furina_v2_{aid}_{sem}.meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        cov = coverage(canvas)
        print(f"[{aid}] keyed -> {out.name} opaque={cov:.3f}")


def coverage(img: Image.Image) -> float:
    a = np.asarray(img.getchannel("A"))
    return float((a > 128).mean())


# ------------------------------------------------------------------ sheet

def sheet(ids: list[str]) -> None:
    base_small = Image.open(BASE).convert("RGBA")
    for aid in ids:
        sem = ASSETS[aid][0]
        cand_path = CAND / f"furina_v2_{aid}_{sem}.png"
        if not cand_path.exists():
            print(f"[{aid}] no candidate, skip sheet")
            continue
        cand = Image.open(cand_path).convert("RGBA")
        H = 640
        left = base_small.resize((round(base_small.width * H / base_small.height), H), Image.LANCZOS)
        right = cand.resize((round(cand.width * H / cand.height), H), Image.LANCZOS)
        pad = 24
        board = Image.new("RGB", (left.width + right.width + pad * 3, H + pad * 2), (40, 40, 48))
        board.paste(left, (pad, pad), left)
        board.paste(right, (left.width + pad * 2, pad), right)
        d = ImageDraw.Draw(board)
        d.text((pad, 4), f"BASE | {aid} {sem}", fill=(230, 230, 230))
        out = REVIEW / f"sheet_{aid}_{sem}.png"
        board.save(out)
        print(f"[{aid}] sheet -> {out.name}")


# ------------------------------------------------------------------ manifest

def manifest() -> None:
    entries = []
    for f in sorted(MASTERS.glob("furina_v2_*.meta.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        entries.append(m)
    doc = {
        "character": "furina", "version": "v2-alpha",
        "base_identity": {"file": "_base/furina-base.png",
                          "identity_version": "furina-base-2026-08",
                          "style_version": "FURINA-STYLE-LOCK-V2"},
        "categories": {}, "entries": entries,
    }
    for e in entries:
        c = e.get("category", "POSTURE")
        slot = doc["categories"].setdefault(c, {"planned": 0, "accepted": 0})
        if e.get("review_status") == "ACCEPT":
            slot["accepted"] += 1
    out = META / "manifest_v2.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"manifest -> {out} ({len(entries)} entries)")


def resolve(ids: str) -> list[str]:
    if ids == "all":
        return list(ASSETS)
    return [s.strip() for s in ids.split(",") if s.strip()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "process", "sheet", "manifest"])
    ap.add_argument("--ids", default="all")
    ap.add_argument("--bump", type=int, default=0)
    n = ap.parse_args()
    if n.cmd == "generate":
        generate(resolve(n.ids), bump=n.bump)
    elif n.cmd == "process":
        process(resolve(n.ids))
    elif n.cmd == "sheet":
        sheet(resolve(n.ids))
    else:
        manifest()
