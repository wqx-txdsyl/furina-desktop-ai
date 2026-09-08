"""NIGHT-03 Recovery Patch 2A R6A — static semantic ownership map.

Pure geometric region assignment from manually specified coordinates.
Zero colour tests. Zero connected components. Zero morphological ops.
Zero near_prot. Zero removal mask references. Zero default-to-costume.
"""
import hashlib, json
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r6a'
MASTERS = ROOT / 'data/assets_v2/masters'
BASE_P = ROOT / 'data/assets_v2/_base/furina-base.png'
SPEC_DIR = ROOT / 'data/assets_v2/_spec'
REVIEW_REPORT = ROOT / ('data/assets_v2/repair_candidates/night03_patch1/'
                        'NIGHT03_PATCH1_REVIEW_REPORT.md')
MASTER_FILE = 'furina_v2_a16_work_focused.png'

L_OTHER, L_HAIR, L_QUILL, L_GLOVE, L_COSTUME, L_CANE, L_CHAIR = range(7)
LABEL_NAMES = {0:'other', 1:'protected_hair', 2:'protected_quill_paper',
               3:'protected_glove_gold_cuff', 4:'protected_costume',
               5:'remove_cane', 6:'remove_chair'}
LABEL_COLOURS = {0:(0,0,0), 1:(30,80,255), 2:(120,200,120),
                 3:(255,160,60), 4:(230,0,230), 5:(255,40,40), 6:(160,90,40)}

# manually specified geometric regions (from visual analysis of
# 2x/3x/5x grid crops; pixel-space in 1024x1536)
REGIONS = [
    (1, 'poly', [(155,540),(400,540),(400,580),(500,580),(500,620),
                 (600,580),(650,580),(650,620),(700,620),(700,700),
                 (760,700),(760,780),(790,780),(790,870),(750,870),
                 (750,920),(600,920),(550,880),(450,880),(400,870),
                 (300,870),(250,850),(200,820),(155,780)]),
    (1, 'rect', (280, 555, 700, 745)),
    (4, 'rect', (330, 720, 480, 890)),
    (2, 'rect', (320, 940, 400, 1100)),
    (2, 'rect', (330, 1085, 510, 1180)),
    (3, 'poly', [(600,1000),(640,1000),(660,1030),(650,1080),
                 (630,1120),(600,1140),(590,1100),(595,1050)]),
    (4, 'poly', [(380,880),(550,880),(600,920),(620,980),(620,1080),
                 (600,1150),(550,1200),(480,1240),(400,1240),
                 (360,1200),(360,1050),(370,950)]),
    (4, 'rect', (430, 880, 560, 950)),
    (4, 'poly', [(700,1050),(780,1050),(820,1120),(830,1200),
                 (800,1260),(750,1270),(720,1240),(700,1150)]),
    (4, 'poly', [(420,1150),(560,1150),(580,1200),(560,1240),
                 (480,1240),(430,1220),(410,1180)]),
    (4, 'poly', [(400,1220),(520,1220),(530,1300),(480,1350),
                 (420,1350),(395,1300)]),
    (4, 'poly', [(450,1250),(550,1250),(560,1330),(520,1380),
                 (460,1380),(440,1330)]),
    (4, 'rect', (495, 1195, 565, 1262)),
    (4, 'poly', [(380,1290),(500,1290),(520,1350),(510,1400),
                 (450,1400),(390,1360),(375,1320)]),
    (4, 'poly', [(430,1330),(530,1330),(545,1390),(535,1430),
                 (470,1430),(430,1400)]),
    (4, 'poly', [(378,1385),(545,1385),(555,1440),(540,1470),
                 (400,1470),(375,1440)]),
    (5, 'circle', (770, 960, 48)),
    (5, 'rect', (748, 902, 806, 968)),
    (5, 'poly', [(648,995),(700,995),(720,1020),(740,1050),
                 (760,1080),(770,1120),(770,1180),(750,1230),
                 (720,1232),(680,1220),(655,1190),(648,1150),
                 (640,1100),(630,1060),(640,1020)]),
    (5, 'poly', [(602,1155),(716,1155),(722,1170),(710,1250),
                 (700,1300),(690,1350),(678,1400),(668,1430),
                 (656,1449),(596,1449),(590,1420),(596,1380),
                 (606,1330),(618,1280),(630,1230),(645,1180),
                 (655,1155)]),
    (6, 'rect', (410, 1216, 700, 1320)),
    (6, 'rect', (480, 1290, 550, 1450)),
    (6, 'rect', (574, 1281, 700, 1450)),
]


def rect_mask(shape, box):
    m = np.zeros(shape[:2], bool)
    m[box[1]:box[3], box[0]:box[2]] = True
    return m


def poly_mask(shape, pts):
    img = Image.new('L', (shape[1], shape[0]), 0)
    ImageDraw.Draw(img).polygon([tuple(p) for p in pts], fill=255)
    return np.array(img) > 128


def circle_mask(shape, cx, cy, rad):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return ((xx - cx)**2 + (yy - cy)**2) <= rad**2


def checker_fn(h, w, c=24):
    yy, xx = np.mgrid[0:h, 0:w]
    t = ((xx // c) + (yy // c)) % 2 == 0
    return np.where(t[..., None], 200, 150).astype(np.uint8)


def sha256_path(p, text_lf=False):
    import hashlib
    hsh = hashlib.sha256()
    if text_lf:
        hsh.update(Path(p).read_bytes().replace(b'\r\n', b'\n'))
        return hsh.hexdigest()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            hsh.update(chunk)
    return hsh.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'mask_plan').mkdir(parents=True, exist_ok=True)
    master = np.array(Image.open(MASTERS / MASTER_FILE).convert('RGBA'))
    h, w = master.shape[:2]
    alpha = master[..., 3] > 8

    ownership = np.zeros((h, w), np.uint8)
    for label, shape_type, shape_data in REGIONS:
        if shape_type == 'rect':
            m = rect_mask((h, w), shape_data)
        elif shape_type == 'poly':
            m = poly_mask((h, w), shape_data)
        elif shape_type == 'circle':
            m = circle_mask((h, w), *shape_data)
        ownership[m & alpha] = label

    vis = (ownership * 30).clip(0, 255).astype(np.uint8)
    Image.fromarray(vis, 'L').save(OUT / 'a16_ownership_source.png')
    np.save(OUT / 'a16_ownership_source.npy', ownership)

    ov = np.zeros((h, w, 3), np.uint8)
    for lb in range(7):
        ov[ownership == lb] = LABEL_COLOURS[lb]
    af = master[..., 3:4].astype(np.float32) / 255.0
    blend = (ov.astype(np.float32) * af
             + master[..., :3].astype(np.float32) * (1 - af)
             ).clip(0, 255).astype(np.uint8)
    Image.fromarray(blend).save(OUT / 'a16_ownership_overlay.png')

    for lb_name, lb_val in LABEL_NAMES.items():
        if lb_val == 0:
            continue
        m = ownership == lb_val
        cut = master.copy()
        cut[..., 3][~m] = 0
        bgc = checker_fn(h, w).astype(np.float32)
        af2 = cut[..., 3:4].astype(np.float32) / 255.0
        comp = (cut[..., :3].astype(np.float32) * af2
                + bgc * (1 - af2)).clip(0, 255).astype(np.uint8)
        Image.fromarray(comp).save(OUT / f'a16_{lb_name}_isolated_cutout.png')

    cane_m = ownership == L_CANE
    chair_m = ownership == L_CHAIR
    for tag, kill in [('cane', cane_m), ('chair', chair_m),
                      ('cane_chair', cane_m | chair_m)]:
        cut = master.copy()
        cut[..., 3][kill] = 0
        for bg_name, bg_rgb in [('checker', None), ('dark', (32,32,32)),
                                 ('light', (240,240,240))]:
            if bg_rgb is None:
                bgc = checker_fn(h, w).astype(np.float32)
            else:
                bgc = np.full((h, w, 3), bg_rgb, np.float32)
            af2 = cut[..., 3:4].astype(np.float32) / 255.0
            comp = (cut[..., :3].astype(np.float32) * af2
                    + bgc * (1 - af2)).clip(0, 255).astype(np.uint8)
            Image.fromarray(comp).save(
                OUT / f'a16_{tag}_cutout_{bg_name}_100.png')
            rx0, ry0, rx1, ry1 = (410, 905, 815, 1470)
            for z in (2, 4):
                sub = Image.fromarray(comp[ry0:ry1, rx0:rx1]).resize(
                    ((rx1-rx0)*z, (ry1-ry0)*z), Image.NEAREST)
                sub.save(OUT / f'a16_{tag}_cutout_{bg_name}_{z*100}.png')

    for lb_name, lb_val in LABEL_NAMES.items():
        if lb_val == 0 or lb_name in ('remove_cane', 'remove_chair'):
            continue
        m = ownership == lb_val
        ov_i = master[..., :3].copy()
        col = np.array(LABEL_COLOURS.get(lb_val, (255,255,255)), np.float32)
        ov_i[m] = (ov_i[m].astype(np.float32) * 0.45
                   + col * 0.55).clip(0,255).astype(np.uint8)
        Image.fromarray(ov_i).save(OUT / f'a16_{lb_name}_overlay.png')

    inputs = {}
    for p in sorted(SPEC_DIR.glob('*.md')):
        inputs[f'_spec/{p.name}'] = sha256_path(p, text_lf=True)
    inputs['BASE'] = sha256_path(BASE_P)
    inputs['PATCH1_REVIEW_REPORT'] = sha256_path(REVIEW_REPORT, text_lf=True)

    census = {}
    for lb in range(7):
        cnt = int((ownership == lb).sum())
        if cnt:
            census[LABEL_NAMES[lb]] = cnt

    plan = {
        'task': 'NIGHT03_RECOVERY_PATCH2A_R6A_STATIC_OWNERSHIP',
        'base_sha': '1b402f9ec8ad79620fb78e0f70cf34c03196d083',
        'method': 'pure geometric region assignment from manually '
                  'specified coordinates; zero colour tests, zero '
                  'connected components, zero morphological ops, zero '
                  'near_prot, zero removal mask references, zero '
                  'default-to-costume',
        'inputs': inputs,
        'assets': {'a16': {
            'master_file': f'data/assets_v2/masters/{MASTER_FILE}',
            'master_sha256': sha256_path(MASTERS / MASTER_FILE),
            'ownership_labels': census,
        }},
    }
    canonical = json.dumps({k: v for k, v in plan.items()},
                           sort_keys=True, ensure_ascii=True,
                           separators=(',', ':'))
    sha = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    plan['MASK_PLAN_SHA256'] = sha
    (OUT / 'mask_plan' / 'night03_patch2a_r6a_mask_plan.json').write_text(
        json.dumps(plan, indent=1, sort_keys=True), encoding='utf-8')

    report = "# NIGHT03_PATCH2A_R6A — Static Semantic Ownership Map\n\n"
    report += f"- MASK_PLAN_SHA256 = {sha}\n"
    report += "- method: pure geometric, zero colour tests\n\n"
    report += "| label | px |\n|---|---:|\n"
    for lb in range(7):
        cnt = int((ownership == lb).sum())
        if cnt:
            report += f"| {LABEL_NAMES[lb]} | {cnt} |\n"
    report += "\nSTATUS = READY_FOR_NIGHT03_PATCH2A_R6A_STATIC_OWNERSHIP_REVIEW\n"
    (OUT.parent / 'NIGHT03_PATCH2A_R6A_REPORT.md').write_text(
        report, encoding='utf-8')
    print(f'R6A OK MASK_PLAN_SHA256={sha}')
    for lb in range(7):
        cnt = int((ownership == lb).sum())
        if cnt:
            print(f'  {LABEL_NAMES.get(lb, "other")}: {cnt}')


if __name__ == '__main__':
    main()
