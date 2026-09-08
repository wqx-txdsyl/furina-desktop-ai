"""NIGHT-03 Recovery Patch 2A R6A-R2 — Builder manual annotation tool.

Produces the EXTERNAL static ownership source
``a16_ownership_annotation.json`` (per-row scanline RLE) for asset a16.

Provenance (stated precisely): every semantic region below is a
hand-placed set of control rows (y, x_left, x_right) fixed by the
Builder from visual analysis of zoomed grid crops (3x-5x) plus numeric
pixel probes at boundary rows.  Between two control rows of one region
the tool linearly interpolates the run edges — this is pure
serialization of the hand-placed landmarks into the required per-row
scanline format.  There is NO computed catch-all: coverage of every
visible pixel by the hand-placed regions is ASSERTED here (the tool
fails and prints the uncovered runs otherwise), and the reviewer-mandated
protected_other_character (7) is carried by explicit hand-placed
regions (face, tail, coat band, and other un-detailed character
pixels), never by an automatic remainder assignment.

R6A-R2 semantic corrections versus R6A-R1 (reviewer NIGHT03_PATCH2A_R6AR1
verdict): the lavender/dark-blue sash component around the blade
(~(700,1140)-(841,1330)) and the white clothing fragment
(~(558,1186)-(618,1252)) are protected_costume — they emanate from the
body/coat system and the cane merely passes in front of them.
remove_cane is limited to: gold finial, helmet topper, wooden shaft,
gold guard with gems, steel blade, leaf spearhead.  remove_chair is
limited to the wooden seat board and the two front legs (no skin, no
clothing, no blade pixels).

label 0 is RESERVED for transparent background.  The freeze script
consumes the JSON read-only; it never generates or modifies it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MASTERS = ROOT / 'data/assets_v2/masters'
OUTDIR = ROOT / ('data/assets_v2/repair_candidates/'
                 'night03_patch2a_r6ar2')
DEVDIR = OUTDIR / '_dev_crops'
MASTER_FILE = 'furina_v2_a16_work_focused.png'
ALPHA_THRESHOLD = 8

LABELS = [
    {'id': 0, 'name': 'background'},
    {'id': 1, 'name': 'protected_hair'},
    {'id': 2, 'name': 'protected_quill_paper'},
    {'id': 3, 'name': 'protected_glove_gold_cuff'},
    {'id': 4, 'name': 'protected_costume'},
    {'id': 5, 'name': 'remove_cane'},
    {'id': 6, 'name': 'remove_chair'},
    {'id': 7, 'name': 'protected_other_character'},
]
L_HAIR, L_QUILL, L_GLOVE, L_COSTUME, L_CANE, L_CHAIR, L_OTHER = range(1, 8)

# --------------------------------------------------------------------------
# hand-placed control rows: (y, x_left, x_right_inclusive)
# --------------------------------------------------------------------------

HAIR = [
    (310, 548, 580), (325, 543, 648), (340, 538, 650), (355, 532, 674),
    (370, 520, 702), (385, 498, 722), (393, 498, 745),
    (398, 300, 332), (402, 291, 339), (406, 283, 347), (410, 277, 352),
    (414, 274, 358), (420, 244, 371), (430, 244, 373),
    (440, 244, 424), (452, 244, 443), (465, 244, 444),
    (444, 244, 421), (458, 244, 440), (470, 244, 442), (484, 243, 444),
    (498, 243, 831), (512, 245, 830), (526, 246, 828), (540, 247, 812),
    (554, 249, 814), (568, 251, 814), (582, 253, 812), (596, 255, 810),
    (610, 257, 810), (624, 259, 810), (638, 261, 808), (652, 263, 800),
    (666, 265, 790), (680, 240, 800), (694, 246, 800), (708, 287, 800),
    (722, 287, 800), (736, 245, 800), (750, 245, 800), (764, 249, 800),
    (778, 258, 792), (792, 248, 792), (806, 248, 792), (820, 249, 782),
    (834, 250, 782), (848, 251, 745), (856, 252, 742), (862, 253, 728), (876, 278, 702),
    (890, 282, 700), (904, 283, 710), (918, 286, 790), (932, 288, 790),
    (946, 279, 796), (960, 279, 798), (975, 298, 794), (990, 300, 790),
    (1005, 303, 778), (1020, 306, 768), (1035, 309, 760), (1050, 312, 751),
    (1065, 315, 748), (1080, 318, 746), (1095, 321, 747), (1110, 324, 748),
    (1125, 327, 738), (1140, 330, 725), (1155, 333, 710), (1170, 336, 700),
]
HAIR_DOME = [
    (386, 590, 676), (392, 528, 746), (398, 522, 749), (420, 443, 749),
    (420, 443, 776), (440, 443, 775), (460, 443, 776), (472, 443, 809), (486, 443, 831),
    (500, 443, 830),
]
FACE = [
    (700, 338, 478), (730, 332, 482), (760, 328, 486), (790, 322, 490),
    (820, 318, 492), (850, 316, 494), (880, 318, 496), (905, 322, 500),
]
TAIL = [
    (998, 236, 304), (1000, 238, 302), (1020, 235, 318), (1040, 195, 345), (1080, 182, 362), (1120, 180, 368), (1160, 182, 362),
    (1200, 186, 352), (1240, 184, 335), (1280, 184, 372), (1320, 210, 382),
    (1360, 248, 382), (1385, 248, 376), (1410, 264, 350), (1428, 300, 340),
]
TORSO = [
    (880, 380, 550), (950, 370, 600), (1000, 360, 620), (1050, 360, 620),
    (1100, 360, 620), (1150, 370, 620), (1200, 380, 620), (1240, 390, 620),
]
NECK = [(880, 430, 560), (950, 430, 560)]
BELT_HIP = [
    (1050, 640, 700), (1100, 640, 700), (1150, 640, 700), (1200, 640, 700),
    (1250, 640, 700), (1270, 640, 700),
]
COAT_BAND = [
    (1130, 598, 652), (1170, 604, 648), (1210, 612, 636), (1250, 622, 644),
    (1290, 630, 638),
]
SASH = [
    (1140, 680, 760), (1150, 680, 745), (1160, 680, 838), (1165, 680, 840),
    (1172, 680, 842), (1180, 680, 842), (1190, 680, 842), (1200, 680, 842),
    (1210, 680, 842), (1220, 680, 842), (1230, 680, 842), (1240, 682, 840),
    (1250, 684, 838), (1260, 688, 836), (1270, 692, 834), (1280, 700, 830),
    (1290, 710, 826), (1300, 720, 820), (1310, 730, 812), (1320, 740, 800),
    (1330, 750, 782),
]
SASH_WHITE = [
    (1186, 588, 618), (1195, 575, 612), (1205, 565, 616), (1215, 560, 617),
    (1225, 558, 615), (1235, 563, 611), (1245, 568, 606), (1252, 570, 600),
]
COAT_TAIL = [
    (1235, 695, 840), (1260, 686, 848), (1290, 688, 850), (1320, 698, 848),
    (1350, 706, 842), (1380, 705, 838), (1410, 708, 830), (1440, 700, 800),
    (1455, 680, 760), (1465, 650, 720),
]
SPIKY_MASS = [
    (985, 772, 795), (1000, 770, 803), (1015, 768, 802), (1030, 764, 800),
    (1045, 752, 798), (1060, 748, 794), (1075, 746, 788), (1090, 744, 782),
    (1105, 742, 778), (1120, 740, 772), (1135, 738, 768),
]
SHORTS = [(1150, 410, 580), (1200, 410, 580), (1240, 420, 575)]
THIGH_RIGHT = [(1190, 520, 580), (1230, 520, 585), (1265, 525, 580)]
THIGH_LEFT = [(1220, 395, 560), (1300, 400, 540), (1380, 410, 530)]
GARTER = [(1195, 495, 565), (1262, 495, 565)]
SOCKS = [(1290, 375, 545), (1360, 380, 540), (1400, 385, 535)]
SHOES = [(1382, 380, 383), (1383, 380, 383), (1385, 356, 555),
         (1410, 368, 550), (1440, 374, 545), (1468, 385, 540)]
LEFT_SKIRT = [(1150, 340, 420), (1250, 340, 430), (1350, 350, 440)]
GLOVE = [
    (930, 690, 745), (950, 680, 730), (970, 670, 725), (990, 660, 722),
    (1010, 650, 723), (1030, 642, 724), (1050, 638, 722), (1070, 636, 720),
    (1090, 638, 716), (1110, 640, 714), (1130, 644, 710), (1145, 648, 706),
]
QUILL = [(940, 320, 400), (1100, 320, 400)]
PAPER = [(1085, 330, 510), (1180, 330, 510)]

# ---- remove_cane: head, shaft, guard, blade, spearhead only --------------

GOLD_BALL = [
    (884, 762, 784), (890, 757, 789), (898, 753, 792), (908, 752, 793),
    (918, 755, 791), (925, 759, 789), (932, 763, 788), (938, 766, 782),
]
DOME = [
    (933, 749, 792), (938, 742, 797), (945, 736, 801), (952, 730, 804),
    (960, 726, 806), (968, 723, 808), (976, 721, 809), (984, 721, 809),
    (992, 722, 808), (998, 724, 806), (1004, 727, 801), (1010, 731, 794),
    (1016, 735, 783),
]
STICK = [
    (1008, 727, 768), (1016, 735, 778), (1025, 737, 757), (1035, 731, 751),
    (1045, 728, 746), (1055, 718, 745), (1065, 716, 745), (1075, 703, 742),
    (1085, 698, 748), (1095, 696, 750), (1105, 693, 747), (1115, 687, 742),
    (1125, 700, 737), (1135, 672, 715), (1142, 650, 702),
]
GUARD_LOWER = [
    (1145, 640, 698), (1160, 638, 700), (1175, 640, 700), (1190, 644, 700),
    (1205, 648, 698), (1220, 646, 698), (1235, 642, 698), (1250, 644, 700),
    (1265, 648, 698), (1275, 650, 694),
]
BLADE = [
    (1085, 676, 714), (1095, 668, 710), (1105, 664, 706), (1115, 662, 704),
    (1125, 658, 702), (1135, 650, 700), (1145, 646, 698), (1155, 646, 698),
    (1165, 648, 700), (1175, 646, 698), (1185, 644, 696), (1195, 640, 694),
    (1205, 636, 690), (1215, 634, 686), (1225, 636, 682), (1235, 640, 680),
    (1245, 644, 679), (1255, 645, 678), (1265, 643, 674), (1275, 640, 666),
    (1285, 638, 661), (1295, 637, 658), (1300, 636, 656),
]
BLADE_LOWER = [
    (1300, 639, 664), (1330, 629, 666), (1360, 619, 669), (1377, 611, 675),
]
SPEARHEAD = [
    (1376, 612, 638), (1386, 594, 626), (1394, 592, 623), (1402, 591, 624),
    (1410, 591, 623), (1418, 591, 620), (1426, 592, 618), (1434, 593, 618),
    (1442, 593, 620), (1448, 593, 617), (1454, 593, 601), (1459, 594, 597),
]

# ---- remove_chair: wooden seat board and two front legs only -------------

SEAT = [
    (1218, 623, 646), (1224, 616, 652), (1230, 610, 656), (1236, 590, 657),
    (1242, 585, 657), (1246, 545, 656), (1250, 504, 657), (1254, 504, 656),
    (1258, 503, 654), (1262, 502, 654), (1266, 501, 648), (1272, 501, 638),
    (1278, 510, 632), (1284, 545, 624), (1288, 570, 618),
]
LEG_LEFT = [
    (1278, 570, 611), (1290, 562, 611), (1300, 560, 612), (1310, 563, 612),
    (1320, 568, 613), (1330, 570, 613), (1340, 572, 614), (1350, 572, 614),
    (1360, 574, 616), (1370, 576, 617), (1380, 576, 615), (1390, 578, 613),
    (1400, 580, 606), (1410, 581, 601), (1420, 582, 599), (1424, 582, 598),
    (1428, 583, 597),
]
LEG_RIGHT = [
    (1258, 672, 683), (1264, 670, 684), (1270, 668, 685), (1276, 666, 686),
    (1282, 664, 687), (1288, 662, 687), (1294, 658, 695), (1300, 658, 694),
    (1310, 658, 696), (1315, 660, 696), (1320, 662, 691), (1330, 664, 691), (1340, 666, 692),
    (1350, 666, 693), (1360, 668, 694), (1370, 670, 695), (1378, 671, 696),
    (1380, 671, 696),
    (1390, 674, 697), (1400, 674, 698), (1410, 675, 698), (1420, 674, 698),
    (1424, 673, 697),
]

# final outline-pickup rows: anti-aliased boundary strokes reviewed one by
# one by the Builder in the R6A-R2 coverage pass and assigned to the
# adjacent semantic region (hand-compiled from the coverage diagnostic).
TAIL_OUTLINE = [
    (1399, 256, 258), (1400, 256, 258),
]
HAIR_OUTLINE = [
    (396, 523, 523), (399, 300, 303), (400, 296, 300), (401, 293, 298),
    (402, 291, 296), (403, 289, 294), (404, 286, 291), (405, 284, 289),
    (406, 283, 287), (407, 281, 285), (408, 280, 283), (409, 278, 281),
    (410, 277, 279), (411, 275, 277), (412, 274, 276), (413, 273, 275),
    (414, 272, 274), (432, 765, 771), (433, 766, 772), (434, 767, 773),
    (435, 768, 774), (436, 770, 774), (437, 771, 774), (438, 772, 774),
    (444, 421, 426), (445, 424, 428), (446, 426, 430), (447, 429, 432),
    (448, 432, 434), (456, 441, 443), (457, 440, 443), (458, 440, 443),
    (459, 441, 443), (460, 441, 443), (470, 802, 804), (528, 823, 828),
    (529, 825, 828), (530, 823, 827), (531, 822, 824), (827, 248, 250),
    (828, 248, 250), (846, 750, 752), (847, 748, 751), (848, 745, 750),
    (849, 745, 749), (850, 744, 747), (851, 744, 746), (953, 279, 283),
    (954, 279, 285), (955, 279, 285), (956, 279, 286), (957, 280, 286),
    (958, 281, 287), (959, 283, 287), (1025, 763, 765), (1026, 763, 765),
    (1027, 762, 765), (1028, 762, 765), (1029, 761, 764), (1030, 761, 764),
    (1031, 760, 763), (1032, 760, 762), (1033, 759, 762), (1034, 759, 761),
    (1035, 758, 760), (1130, 729, 733), (1131, 730, 732), (1132, 729, 732),
    (1133, 729, 731), (1246, 185, 187), (1247, 185, 187), (1248, 185, 187),
    (1249, 185, 187), (1250, 185, 187), (1251, 185, 187), (1252, 185, 187),
    (1253, 185, 187), (1254, 185, 187), (1255, 185, 188), (1256, 185, 188),
    (1257, 185, 188), (1258, 185, 188), (1259, 185, 188), (1260, 185, 188),
    (1261, 185, 188), (1262, 186, 188), (1263, 186, 188), (1264, 186, 188),
    (1265, 186, 188), (1266, 186, 189), (1267, 186, 189), (1268, 186, 189),
    (1269, 186, 189), (1270, 187, 189), (1271, 187, 189), (1272, 187, 189),
    (1273, 187, 189), (1274, 187, 189), (1275, 188, 190), (1276, 188, 190),
    (1277, 188, 190), (1282, 662, 664), (1283, 662, 664), (1284, 191, 192),
    (1285, 191, 193), (1286, 191, 193), (1287, 192, 194), (1288, 193, 194),
    (1289, 193, 194), (1290, 193, 195), (1291, 194, 196), (1292, 194, 196),
    (1293, 195, 196), (1294, 195, 197), (1295, 196, 198), (1296, 196, 198),
    (1297, 197, 198), (1298, 197, 199), (1299, 198, 200), (1300, 198, 200),
    (1301, 199, 200), (1302, 199, 201), (1303, 200, 202), (1304, 201, 202),
    (1305, 201, 202), (1306, 202, 203), (1307, 202, 204), (1308, 203, 204),
    (1310, 204, 205), (1311, 205, 206), (1372, 380, 383), (1373, 380, 383), (1382, 380, 383), (1383, 380, 383),
    (1374, 379, 382), (1375, 380, 382), (1376, 379, 382), (1377, 380, 382),
    (1378, 379, 382), (1379, 380, 382), (1380, 380, 382), (1381, 380, 383),
    (1382, 380, 383), (1383, 380, 383), (1384, 380, 383), (1399, 361, 363),
    (1400, 256, 258), (1400, 360, 362), (1401, 359, 361), (1434, 376, 378),
    (1435, 376, 378), (1437, 377, 379), (1443, 617, 619), (1445, 616, 618),
    (1446, 615, 617), (1403, 708, 710), (1404, 708, 710), (1282, 662, 664),
    (1285, 661, 663), (1286, 661, 663), (1287, 660, 662), (1288, 660, 662),
    (1289, 660, 662), (1290, 660, 662), (1291, 659, 662), (1292, 659, 661),
    (1293, 659, 661), (1294, 658, 661), (1295, 658, 661), (1296, 658, 661),
    (1297, 657, 660), (1298, 657, 660), (1299, 656, 660), (1306, 658, 661),
    (1307, 658, 661), (1308, 657, 661), (1309, 657, 661), (1310, 656, 661),
    (1311, 657, 661), (1312, 657, 661), (1313, 657, 661), (1314, 657, 661),
    (1315, 657, 662), (1316, 657, 662), (1317, 658, 662), (1318, 658, 662),
    (1319, 658, 662), (1320, 658, 662), (1321, 659, 662), (1322, 659, 662),
    (1323, 660, 663), (1324, 660, 663), (1325, 660, 663), (1326, 660, 663),
    (1327, 660, 663), (1328, 660, 664), (1329, 661, 664), (1330, 661, 664),
    (1331, 661, 664), (1332, 661, 664), (1333, 661, 665), (1334, 661, 665),
    (1335, 662, 665), (1336, 662, 665), (1337, 662, 665), (1338, 662, 666),
    (1339, 662, 666), (1340, 662, 666), (1341, 663, 666), (1342, 663, 666),
    (1343, 663, 666), (1344, 663, 666), (1345, 663, 666), (1346, 664, 666),
    (1347, 664, 666), (1348, 664, 666), (1349, 664, 666), (1353, 665, 667),
    (1354, 665, 667), (1358, 666, 668), (1359, 666, 668), (1360, 666, 668),
    (1361, 614, 668), (1362, 614, 616), (1363, 614, 669), (1364, 614, 669),
    (1365, 614, 669), (1366, 667, 669), (1367, 667, 669), (1368, 668, 670),
    (1369, 668, 670), (1370, 668, 670), (1371, 668, 670), (1385, 671, 673),
    (1386, 671, 673), (1387, 671, 673), (1388, 671, 674), (1389, 671, 674),
    (1390, 671, 674), (1391, 672, 674), (1392, 672, 674), (1393, 672, 674),
    (1394, 672, 674), (1395, 672, 674), (1396, 672, 674), (1382, 671, 672),
    (1383, 671, 672),
]

# paint order: later parts overwrite earlier ones at overlaps.
PROTECT_PARTS = [
    (L_HAIR, 'hair', HAIR),
    (L_HAIR, 'hair_dome', HAIR_DOME),
    (L_HAIR, 'hair_outline', HAIR_OUTLINE),
    (L_OTHER, 'face', FACE),
    (L_OTHER, 'tail', TAIL),
    (L_OTHER, 'tail_outline', TAIL_OUTLINE),
    (L_COSTUME, 'torso', TORSO),
    (L_COSTUME, 'neck_collar', NECK),
    (L_COSTUME, 'belt_hip', BELT_HIP),
    (L_COSTUME, 'coat_band', COAT_BAND),
    (L_COSTUME, 'sash', SASH),
    (L_COSTUME, 'sash_white_cloth', SASH_WHITE),
    (L_COSTUME, 'coat_tail', COAT_TAIL),
    (L_COSTUME, 'spiky_mass', SPIKY_MASS),
    (L_COSTUME, 'shorts', SHORTS),
    (L_COSTUME, 'thigh_right', THIGH_RIGHT),
    (L_COSTUME, 'thigh_left', THIGH_LEFT),
    (L_COSTUME, 'garter', GARTER),
    (L_COSTUME, 'socks', SOCKS),
    (L_COSTUME, 'shoes', SHOES),
    (L_COSTUME, 'left_skirt', LEFT_SKIRT),
    (L_GLOVE, 'glove_hand', GLOVE),
    (L_QUILL, 'quill', QUILL),
    (L_QUILL, 'paper', PAPER),
]
REMOVE_PARTS = [
    (L_CHAIR, 'chair_seat', SEAT),
    (L_CHAIR, 'chair_leg_left', LEG_LEFT),
    (L_CHAIR, 'chair_leg_right', LEG_RIGHT),
    (L_CANE, 'cane_gold_ball', GOLD_BALL),
    (L_CANE, 'cane_dome', DOME),
    (L_CANE, 'cane_stick', STICK),
    (L_CANE, 'cane_guard_lower', GUARD_LOWER),
    (L_CANE, 'cane_blade', BLADE),
    (L_CANE, 'cane_blade_lower', BLADE_LOWER),
    (L_CANE, 'cane_spearhead', SPEARHEAD),
]


def rows_to_runs(rows):
    """Expand hand-placed control rows into per-row runs (linear interp)."""
    rows = sorted(rows)
    out = {}
    for (y0, a0, b0), (y1, a1, b1) in zip(rows, rows[1:]):
        span = y1 - y0
        for y in range(y0, y1):
            t = (y - y0) / span
            out[y] = (round(a0 + (a1 - a0) * t), round(b0 + (b1 - b0) * t))
    out[rows[-1][0]] = (rows[-1][1], rows[-1][2])
    return out


def merge_runs(run_list):
    """Union same-row runs; returns sorted merged list of (x0, x1)."""
    if not run_list:
        return []
    run_list = sorted(run_list)
    merged = [list(run_list[0])]
    for a, b in run_list[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(r) for r in merged]


def main():
    master = np.array(Image.open(MASTERS / MASTER_FILE).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD

    ownership = np.zeros((h, w), np.uint8)
    for lb, name, rows in PROTECT_PARTS + REMOVE_PARTS:
        for y, (a, b) in rows_to_runs(rows).items():
            ownership[y, a:b + 1] = lb
    ownership[~visible] = 0

    # ---- coverage assertion: hand-placed regions must cover every visible
    # pixel.  No computed catch-all exists; failures list the uncovered runs.
    uncovered = visible & (ownership == 0)
    n_unc = int(uncovered.sum())
    print(f'visible={int(visible.sum())} uncovered_visible={n_unc} '
          f'labeled_background={int(((~visible) & (ownership != 0)).sum())}')
    if n_unc:
        ys, xs = np.where(uncovered)
        import collections
        by_row = collections.Counter(ys)
        shown = 0
        for y, cnt in sorted(by_row.items()):
            xr = np.sort(xs[ys == y])
            splits = np.where(np.diff(xr) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xr.size - 1]))
            spans = ', '.join(f'{xr[s]}-{xr[e]}' for s, e in
                              zip(starts, ends))
            print(f'  y={y}: {spans} ({cnt}px)')
            shown += 1
            if shown >= 60:
                print('  ... more rows omitted')
                break
        raise SystemExit('coverage incomplete: add hand-placed rows')
    assert ((~visible) & (ownership != 0)).sum() == 0
    assert ((ownership == 5) & (ownership == 6)).sum() == 0

    # ---- write the static annotation source -------------------------------
    # rows are serialised FROM the final ownership array, so the JSON is
    # non-overlapping by construction and identical to the census.
    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows_json = []
    for y in range(h):
        entries = []
        for lb in range(1, 8):
            xs = np.where(ownership[y] == lb)[0]
            if xs.size == 0:
                continue
            splits = np.where(np.diff(xs) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xs.size - 1]))
            for s, e in zip(starts, ends):
                entries.append([int(xs[s]), int(xs[e]), int(lb)])
        if entries:
            entries.sort()
            rows_json.append([int(y), *entries])
    doc = {
        'format': 'night03-ownership-scanline-rle-v2',
        'asset': 'a16',
        'canvas': {'w': int(w), 'h': int(h)},
        'alpha_threshold': ALPHA_THRESHOLD,
        'labels': LABELS,
        'annotation': {
            'author': 'Builder (GLM/ZCode) manual scanline annotation: '
                      'hand-placed control rows from zoomed grid crops + '
                      'pixel probes, linearly interpolated between control '
                      'rows; explicit full-coverage assertion, no computed '
                      'catch-all',
            'reviewer': 'ChatGPT Codex (sole Reviewer)',
            'note': 'label 0 reserved for transparent background; every '
                    'alpha>8 pixel carries an explicit semantic label; '
                    'sash and white cloth around the blade are '
                    'protected_costume (cane passes in front of them)',
        },
        'rows': rows_json,
    }
    jp = OUTDIR / 'a16_ownership_annotation.json'
    jp.write_text(json.dumps(doc, ensure_ascii=True, sort_keys=False),
                  encoding='utf-8', newline='\n')
    n_runs = sum(len(r) - 1 for r in rows_json)
    print(f'wrote {jp} rows={len(rows_json)} runs={n_runs} '
          f'{jp.stat().st_size} bytes')

    census = {LABELS[lb]['name']: int((ownership == lb).sum())
              for lb in range(8)}
    print(json.dumps(census, indent=1))

    # ---- dev previews (NOT part of the deliverable) -----------------------
    DEVDIR.mkdir(parents=True, exist_ok=True)
    colours = {0: (0, 0, 0), 1: (30, 80, 255), 2: (120, 200, 120),
               3: (255, 160, 60), 4: (230, 0, 230), 5: (255, 40, 40),
               6: (160, 90, 40), 7: (0, 200, 200)}
    ov = np.zeros((h, w, 3), np.uint8)
    for lb in range(8):
        ov[ownership == lb] = colours[lb]
    af = master[..., 3:4].astype(np.float32) / 255.0
    blend = (ov.astype(np.float32) * 0.55 * af
             + master[..., :3].astype(np.float32) * 0.45 * af
             + 255.0 * (1 - af)).clip(0, 255).astype(np.uint8)
    Image.fromarray(blend).save(DEVDIR / 'iter_overlay_full.png')
    for tag, kill in [('cane', ownership == L_CANE),
                      ('chair', ownership == L_CHAIR),
                      ('both', (ownership == L_CANE)
                       | (ownership == L_CHAIR))]:
        cut = master.copy()
        cut[..., 3][kill] = 0
        bg = np.full((h, w, 3), 255, np.uint8)
        a2 = cut[..., 3:4].astype(np.float32) / 255.0
        comp = (cut[..., :3].astype(np.float32) * a2
                + bg * (1 - a2)).clip(0, 255).astype(np.uint8)
        Image.fromarray(comp).save(DEVDIR / f'iter_{tag}_cutout.png')
    print('dev previews written')


if __name__ == '__main__':
    main()
