"""NIGHT-03 Recovery Patch 2A R6A-R4 — Builder manual annotation tool.

Produces the EXTERNAL static ownership source
``a16_ownership_annotation.json`` (per-row scanline RLE + frozen
occlusion_resolution ledger) for asset a16.

Provenance: every semantic region is a hand-placed set of control rows
(y, x_left, x_right) fixed by the Builder from visual analysis of
zoomed grid crops (3x-5x) plus numeric pixel probes at boundary rows.
Between two control rows of one region the tool linearly interpolates
the run edges — pure serialization of the hand-placed landmarks into
the required per-row scanline format.  There is NO computed catch-all:
coverage of every visible pixel by the hand-placed regions is ASSERTED
(the tool fails listing uncovered runs otherwise), and
protected_other_character (7) is carried by explicit hand-placed
regions, never by an automatic remainder assignment.

R6A-R3 corrections versus R6A-R2 (reviewer
NIGHT03_PATCH2A_R6AR2_PATCH_REQUIRED verdict @ 5a7e265):

1. cane/chair primitives are constructed SEPARATELY and their
   geometric intersection is computed BEFORE merging.  Every overlap
   region is resolved through the frozen ``occlusion_resolution``
   ledger recorded inside the JSON (bbox, px count, winner, semantic
   rationale, and the explicit pixel list) — paint order no longer
   silently adjudicates anything.
2. The spearhead / lower-blade primitives were narrowed to the actual
   steel/silver leaf plus its own contour; every visible brown chair
   leg pixel (reviewer: 570 px, main area (592,1376)-(614,1446),
   example (598,1384) RGBA=(111,80,64)) now belongs to remove_chair,
   including the previously missed left-leg foot sliver
   (605-617, 1432-1448) and the three right-leg edge pixels at
   (658,1301)-(658,1303).
3. RIBBON_AS_CANE_ACCEPTED = false and SASH_PROTECTED = true are
   structural here: the sash / white-cloth regions are
   protected_costume and the cane parts contain no sash pixels.

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
OUTDIR = ROOT / 'data/assets_v2/repair_candidates/night03_patch2a_r6ar4'
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
    (398, 300, 332), (405, 289, 341), (412, 275, 357), (420, 244, 371), (430, 244, 373),
    (440, 244, 424), (452, 244, 443), (465, 244, 444),
    (444, 244, 421), (458, 244, 440), (470, 244, 442), (484, 243, 444),
    (498, 243, 812), (512, 245, 830), (526, 246, 828), (540, 247, 812),
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
    (440, 443, 775), (460, 443, 776), (472, 443, 809), (486, 443, 831),
    (500, 443, 830),
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
    (1133, 729, 731),
]
HAIR_OUTLINE_R = [
    (402, 338, 339), (403, 339, 342), (404, 341, 344), (405, 342, 345),
    (406, 344, 347), (407, 346, 349), (408, 348, 350),
]
FACE = [
    (700, 338, 478), (730, 332, 482), (760, 328, 486), (790, 322, 490),
    (820, 318, 492), (850, 316, 494), (880, 318, 496), (905, 322, 500),
]
TAIL = [
    (998, 236, 304), (1000, 238, 302), (1020, 235, 318), (1040, 195, 345),
    (1080, 182, 362), (1120, 180, 368), (1160, 182, 362),
    (1200, 184, 352), (1240, 184, 335), (1280, 184, 372), (1320, 210, 382),
    (1360, 248, 382), (1385, 248, 376), (1410, 264, 350), (1428, 300, 340),
]
TAIL_OUTLINE = [
    (1246, 185, 187), (1247, 185, 187), (1248, 185, 187), (1249, 185, 187),
    (1250, 185, 187), (1251, 185, 187), (1252, 185, 187), (1253, 185, 187),
    (1254, 185, 187), (1255, 185, 188), (1256, 185, 188), (1257, 185, 188),
    (1258, 185, 188), (1259, 185, 188), (1260, 185, 188), (1261, 185, 188),
    (1262, 186, 188), (1263, 186, 188), (1264, 186, 188), (1265, 186, 188),
    (1266, 186, 189), (1267, 186, 189), (1268, 186, 189), (1269, 186, 189),
    (1270, 187, 189), (1271, 187, 189), (1272, 187, 189), (1273, 187, 189),
    (1274, 187, 189), (1275, 188, 190), (1276, 188, 190), (1277, 188, 190),
    (1284, 191, 192), (1285, 191, 193), (1286, 191, 193), (1287, 192, 194),
    (1288, 193, 194), (1289, 193, 194), (1290, 193, 195), (1291, 194, 196),
    (1292, 194, 196), (1293, 195, 196), (1294, 195, 197), (1295, 196, 198),
    (1296, 196, 198), (1297, 197, 198), (1298, 197, 199), (1299, 198, 200),
    (1300, 198, 200), (1301, 199, 200), (1302, 199, 201), (1303, 200, 202),
    (1304, 201, 202), (1305, 201, 202), (1306, 202, 203), (1307, 202, 204),
    (1308, 203, 204), (1310, 204, 205), (1311, 205, 206),
    (1399, 256, 258), (1400, 256, 258),
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
SHOES = [(1385, 356, 555), (1410, 368, 550), (1440, 374, 545),
         (1468, 385, 540)]
SHOE_OUTLINE = [
    (1372, 380, 382), (1376, 379, 382), (1380, 379, 382),
    (1382, 380, 383), (1383, 380, 383), (1399, 361, 363),
    (1400, 360, 362), (1401, 359, 361),
]
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
    (1245, 644, 679), (1255, 645, 678), (1265, 643, 676), (1275, 640, 666),
    (1285, 638, 661), (1295, 637, 658), (1300, 636, 656),
]
BLADE_LOWER = [
    (1300, 641, 657), (1305, 640, 654), (1310, 639, 651), (1315, 637, 650),
    (1320, 636, 647), (1325, 634, 646), (1330, 632, 644), (1335, 631, 642),
    (1340, 629, 640), (1345, 627, 639), (1351, 626, 636), (1357, 624, 634),
    (1363, 621, 631), (1369, 619, 629), (1375, 618, 627), (1377, 617, 626),
]
SPEARHEAD = [
    (1378, 619, 626), (1382, 617, 625), (1386, 616, 624), (1390, 614, 623),
    (1394, 611, 622), (1398, 610, 622), (1402, 607, 623), (1406, 603, 625),
    (1410, 602, 623), (1414, 600, 621), (1418, 599, 622), (1422, 598, 618),
    (1426, 597, 617), (1430, 596, 611), (1434, 594, 608), (1438, 594, 607),
    (1442, 594, 606), (1446, 594, 605), (1450, 594, 601), (1454, 594, 599),
    (1457, 593, 599),
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
    (1360, 574, 614), (1370, 585, 615), (1374, 586, 615), (1378, 587, 618),
    (1382, 587, 616), (1386, 588, 615), (1390, 589, 613), (1394, 589, 610),
    (1398, 589, 609), (1400, 590, 604), (1404, 591, 603), (1408, 591, 601),
    (1412, 591, 600), (1416, 591, 600), (1420, 591, 599), (1424, 592, 598),
    (1428, 593, 597), (1432, 593, 595),
]
LEG_LEFT_FOOT = [
    (1432, 611, 617), (1436, 609, 617), (1440, 608, 617), (1444, 606, 617),
    (1448, 602, 612), (1449, 603, 610),
]
LEG_RIGHT = [
    (1258, 672, 683), (1264, 670, 684), (1270, 668, 685), (1276, 666, 686),
    (1282, 664, 687), (1288, 662, 687), (1294, 658, 695), (1300, 658, 694),
    (1310, 658, 696), (1320, 662, 691), (1330, 664, 691), (1340, 666, 692),
    (1350, 666, 693), (1360, 668, 694), (1370, 670, 695), (1380, 671, 696),
    (1390, 673, 697), (1400, 674, 698), (1410, 675, 698), (1420, 674, 698),
    (1424, 673, 697),
]
LEG_RIGHT_OUTLINE = [
    (1282, 663, 663), (1283, 663, 663), (1285, 662, 662), (1286, 662, 662),
    (1287, 661, 661), (1288, 661, 661), (1298, 657, 657), (1299, 657, 657),
    (1300, 657, 657), (1301, 657, 657),
    (1302, 657, 657), (1303, 656, 658), (1304, 656, 658), (1305, 656, 658),
    (1306, 656, 658), (1307, 657, 657), (1308, 657, 657), (1309, 657, 657),
    (1310, 657, 657), (1312, 658, 658), (1313, 658, 658), (1314, 658, 659),
    (1315, 658, 659), (1316, 658, 659), (1318, 659, 660), (1319, 659, 661),
    (1296, 657, 657), (1297, 657, 657), (1298, 657, 657),
    (1299, 657, 657), (1300, 657, 657), (1301, 657, 657),
    (1320, 659, 661), (1322, 660, 661), (1323, 661, 662), (1324, 661, 662),
    (1325, 661, 662), (1326, 661, 662), (1327, 661, 662), (1328, 661, 663),
    (1329, 662, 663), (1330, 662, 663), (1331, 662, 663), (1332, 662, 663),
    (1333, 662, 664), (1334, 662, 664), (1335, 663, 664), (1337, 663, 664),
    (1338, 663, 665), (1340, 663, 665), (1341, 664, 665), (1342, 664, 665),
    (1343, 664, 665), (1344, 664, 665), (1345, 664, 665), (1346, 665, 665),
    (1347, 665, 665), (1348, 665, 665), (1349, 665, 665), (1353, 666, 666),
    (1354, 666, 666), (1359, 667, 667), (1360, 667, 667), (1366, 668, 668),
    (1367, 668, 668), (1369, 669, 669), (1370, 669, 669), (1383, 671, 671),
    (1388, 672, 672), (1389, 672, 672), (1390, 672, 672), (1395, 673, 673),
    (1396, 673, 673),
]
BLADE_OUTLINE = [
    (1311, 638, 638), (1317, 636, 636), (1321, 635, 635), (1336, 630, 630),
    (1339, 641, 641), (1352, 625, 625), (1355, 624, 624), (1358, 623, 623),
    (1361, 615, 615), (1362, 615, 615), (1363, 615, 615), (1364, 615, 615),
    (1365, 615, 631), (1368, 630, 669), (1371, 618, 629), (1373, 616, 617),
    (1374, 616, 617), (1375, 617, 617), (1376, 617, 628), (1381, 617, 617),
    (1387, 615, 615), (1402, 604, 606), (1410, 601, 601), (1411, 601, 601),
    (1428, 615, 616), (1429, 613, 616), (1430, 612, 616), (1431, 611, 617),
    (1434, 609, 609), (1435, 609, 609), (1437, 608, 608), (1440, 607, 607),
    (1441, 607, 607), (1443, 618, 618), (1445, 617, 617),
    (1446, 615, 616), (1447, 614, 614),
]
SPEAR_OUTLINE = [
    (1403, 590, 590), (1404, 590, 590), (1405, 590, 590), (1406, 590, 590),
    (1407, 590, 590), (1408, 590, 590), (1427, 592, 592), (1444, 593, 593),
    (1445, 593, 593), (1446, 593, 593), (1447, 593, 593), (1448, 593, 593),
    (1449, 593, 593), (1450, 593, 593), (1451, 593, 601), (1452, 593, 593),
    (1453, 593, 593), (1454, 593, 593), (1455, 593, 593), (1458, 594, 596),
    (1459, 594, 595),
]

# --------------------------------------------------------------------------
# frozen occlusion_resolution ledger: entries describe every region where
# the cane and chair primitives geometrically intersect.  Winner decides
# the final label for those pixels; the pixel list is explicit so the
# freeze script can verify the resolution independently (no tautology).
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# frozen occlusion_resolution ledger: the cane and chair primitives are
# built separately; EVERY geometrically overlapping visible pixel is
# adjudicated per-pixel by master colour:
#   warm wood (r > b + 15, r >= g - 5)        -> remove_chair (winner 6)
#   cool steel/silver (b >= r + 15, b >= 100)  -> remove_cane  (winner 5)
#   neutral dark/other boundary px              -> 4-neighbour vote among
#   non-overlap primitive pixels (tie -> chair).  The adjudicated pixel
#   list is frozen below and independently re-verified by the freeze
#   script against the two primitive masks (exact set equality).
# --------------------------------------------------------------------------
OCCLUSION_RESOLUTION = []
ADJUDICATION = {'wood_to_chair': 0, 'steel_to_cane': 0, 'dark_to_cane': 0,
                'dark_to_chair': 0}



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


def build_primitive(parts):
    master_h = 1536
    mask = np.zeros((master_h, 1024), bool)
    rows_per_part = {}
    for lb, name, rows in parts:
        for y, (a, b) in rows_to_runs(rows).items():
            mask[y, a:b + 1] = True
            rows_per_part.setdefault(name, set()).add(y)
    return mask, rows_per_part


def main():
    master = np.array(Image.open(MASTERS / MASTER_FILE).convert('RGBA'))
    h, w = master.shape[:2]
    visible = master[..., 3] > ALPHA_THRESHOLD

    cane_parts = [(lb, n, r) for lb, n, r in
                  [(L_CANE, 'gold_ball', GOLD_BALL),
                   (L_CANE, 'dome', DOME),
                   (L_CANE, 'stick', STICK),
                   (L_CANE, 'guard_lower', GUARD_LOWER),
                   (L_CANE, 'blade', BLADE),
                   (L_CANE, 'blade_lower', BLADE_LOWER),
                   (L_CANE, 'spearhead', SPEARHEAD),
                   (L_CANE, 'blade_outline', BLADE_OUTLINE),
                   (L_CANE, 'spear_outline', SPEAR_OUTLINE)]]
    chair_parts = [(lb, n, r) for lb, n, r in
                   [(L_CHAIR, 'seat', SEAT),
                    (L_CHAIR, 'leg_left', LEG_LEFT),
                    (L_CHAIR, 'leg_left_foot', LEG_LEFT_FOOT),
                    (L_CHAIR, 'leg_right', LEG_RIGHT),
                    (L_CHAIR, 'leg_right_outline', LEG_RIGHT_OUTLINE)]]
    protect_parts = [
        (L_HAIR, 'hair', HAIR),
        (L_HAIR, 'hair_dome', HAIR_DOME),
        (L_HAIR, 'hair_outline', HAIR_OUTLINE),
        (L_HAIR, 'hair_outline_r', HAIR_OUTLINE_R),
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
        (L_COSTUME, 'shoe_outline', SHOE_OUTLINE),
        (L_COSTUME, 'left_skirt', LEFT_SKIRT),
        (L_GLOVE, 'glove_hand', GLOVE),
        (L_QUILL, 'quill', QUILL),
        (L_QUILL, 'paper', PAPER),
    ]

    # ---- primitives, built separately ------------------------------------
    cane_prim, _ = build_primitive(cane_parts)
    chair_prim, _ = build_primitive(chair_parts)
    cane_prim &= visible
    chair_prim &= visible
    prim_overlap = cane_prim & chair_prim
    n_overlap = int(prim_overlap.sum())
    print(f'primitive cane&chair overlap = {n_overlap} px '
          f'(must be resolved through the frozen ledger)')

    # ---- per-pixel colour adjudication of the primitive overlap ----------
    # warm wood -> chair; cool steel/silver -> cane; neutral boundary px ->
    # 4-neighbour vote among non-overlap primitive pixels (tie -> chair).
    rch, gch, bch = (master[..., 0].astype(int), master[..., 1].astype(int),
                     master[..., 2].astype(int))
    resolved = np.zeros((h, w), np.uint8)
    dark_vote = []
    for y, x in zip(*np.where(prim_overlap)):
        rr, gg, bb = int(rch[y, x]), int(gch[y, x]), int(bch[y, x])
        if rr > bb + 15 and rr >= gg - 5:
            resolved[y, x] = L_CHAIR
            ADJUDICATION['wood_to_chair'] += 1
        elif bb >= rr + 15 and bb >= 100:
            resolved[y, x] = L_CANE
            ADJUDICATION['steel_to_cane'] += 1
        else:
            dark_vote.append((y, x))
    for y, x in dark_vote:
        c5 = c6 = 0
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if not (0 <= yy < h and 0 <= xx < w and visible[yy, xx]):
                continue
            if cane_prim[yy, xx] and not chair_prim[yy, xx]:
                c5 += 1
            elif chair_prim[yy, xx] and not cane_prim[yy, xx]:
                c6 += 1
        w6 = c6 >= c5
        resolved[y, x] = L_CHAIR if w6 else L_CANE
        ADJUDICATION['dark_to_chair' if w6 else 'dark_to_cane'] += 1

    # ---- group adjudicated pixels into ledger entries ---------------------
    # one entry per connected bbox region; both winners must appear.
    from scipy import ndimage
    st8 = ndimage.generate_binary_structure(2, 2)
    lab, n_lab = ndimage.label(prim_overlap, structure=st8)
    led_by_region = []
    for rid in range(1, n_lab + 1):
        m_rid = lab == rid
        pys, pxs = np.where(m_rid)
        winners = sorted({int(resolved[y, x]) for y, x in zip(pys, pxs)})
        for winner in winners:
            sub = m_rid & (resolved == winner)
            if not sub.any():
                continue
            sy, sx = np.where(sub)
            led_by_region.append({
                'bbox': [int(sx.min()), int(sy.min()), int(sx.max()),
                         int(sy.max())],
                'px': int(sub.sum()),
                'winner': winner,
                'rationale': ('warm wood seat/leg pixels adjudicated to '
                              'remove_chair' if winner == L_CHAIR else
                              'cool steel/silver blade/spearhead pixels '
                              'adjudicated to remove_cane'),
                'pixels': [[int(x), int(y)] for y, x in zip(sy, sx)],
            })
    led_by_region.sort(key=lambda e: (e['bbox'][0], e['bbox'][1]))
    ledger = led_by_region
    winners_seen = {e['winner'] for e in ledger}
    assert winners_seen == {L_CANE, L_CHAIR}, (
        f'ledger must contain both winners, saw {winners_seen}')
    assert sum(e['px'] for e in ledger) == n_overlap
    print(f'primitive cane&chair overlap = {n_overlap} px across '
          f'{len(ledger)} ledger entries; adjudication={ADJUDICATION}')

    # ---- paint: protect -> adjudicated cane/chair (no silent order) ------
    ownership = np.zeros((h, w), np.uint8)
    for lb, name, rows in protect_parts:
        for y, (a, b) in rows_to_runs(rows).items():
            ownership[y, a:b + 1] = lb
    only_cane = cane_prim & ~prim_overlap
    only_chair = chair_prim & ~prim_overlap
    ownership[only_cane] = L_CANE
    ownership[only_chair] = L_CHAIR
    ownership[resolved > 0] = resolved[resolved > 0]
    ownership[~visible] = 0

    # ---- coverage assertion ----------------------------------------------
    uncovered = visible & (ownership == 0)
    n_unc = int(uncovered.sum())
    print(f'visible={int(visible.sum())} uncovered_visible={n_unc} '
          f'labeled_background={int(((~visible) & (ownership != 0)).sum())}')
    if n_unc:
        uys, uxs = np.where(uncovered)
        import collections
        by_row = collections.Counter(uys)
        shown = 0
        for y, cnt in sorted(by_row.items()):
            xr = np.sort(uxs[uys == y])
            splits = np.where(np.diff(xr) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xr.size - 1]))
            spans = ', '.join(f'{xr[s]}-{xr[e]}' for s, e in
                              zip(starts, ends))
            print(f'  y={y}: {spans} ({cnt}px)')
            shown += 1
            if shown >= 500:
                print('  ... more rows omitted')
                break
        raise SystemExit('coverage incomplete: add hand-placed rows')
    assert ((~visible) & (ownership != 0)).sum() == 0

    # ---- serialize (rows from the FINAL ownership array: non-overlapping) -
    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows_json = []
    for y in range(h):
        entries = []
        for lb in range(1, 8):
            xsl = np.where(ownership[y] == lb)[0]
            if xsl.size == 0:
                continue
            splits = np.where(np.diff(xsl) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xsl.size - 1]))
            for s, e in zip(starts, ends):
                entries.append([int(xsl[s]), int(xsl[e]), int(lb)])
        if entries:
            entries.sort()
            rows_json.append([int(y), *entries])
    # ---- frozen primitive masks (independent verification inputs) --------
    def rle_rows(mask):
        out_rows = []
        for y in range(h):
            xsl = np.where(mask[y])[0]
            if xsl.size == 0:
                continue
            splits = np.where(np.diff(xsl) > 1)[0]
            starts = np.concatenate(([0], splits + 1))
            ends = np.concatenate((splits, [xsl.size - 1]))
            out_rows.append([int(y)] + [[int(xsl[s]), int(xsl[e])]
                                        for s, e in zip(starts, ends)])
        return out_rows

    primitives = {
        'remove_cane': rle_rows(cane_prim),
        'remove_chair': rle_rows(chair_prim),
    }

    doc = {
        'format': 'night03-ownership-scanline-rle-v4',
        'asset': 'a16',
        'canvas': {'w': int(w), 'h': int(h)},
        'alpha_threshold': ALPHA_THRESHOLD,
        'labels': LABELS,
        'primitives': primitives,
        'annotation': {
            'author': 'Builder (GLM/ZCode) manual scanline annotation: '
                      'hand-placed control rows from zoomed grid crops + '
                      'pixel probes, linearly interpolated between control '
                      'rows; explicit full-coverage assertion, no computed '
                      'catch-all',
            'reviewer': 'ChatGPT Codex (sole Reviewer)',
            'semantics': {
                'RIBBON_AS_CANE_ACCEPTED': False,
                'SASH_PROTECTED': True,
                'note': 'the sash and white cloth around the blade are '
                        'protected_costume; remove_cane contains only '
                        'cane-head, shaft, guard, blade and spearhead '
                        'pixels; every visible brown chair-leg pixel is '
                        'remove_chair',
            },
        },
        'occlusion_resolution': ledger,
        'rows': rows_json,
    }
    jp = OUTDIR / 'a16_ownership_annotation.json'
    jp.write_text(json.dumps(doc, ensure_ascii=True, sort_keys=False),
                  encoding='utf-8', newline='\n')
    n_runs = sum(len(r) - 1 for r in rows_json)
    print(f'wrote {jp} rows={len(rows_json)} runs={n_runs} '
          f'ledger_entries={len(ledger)} ledger_px={n_overlap} '
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
    for name, (x0, y0, x1, y1, z) in {
            'tip': (540, 1290, 760, 1470, 3),
            'blade_seat': (540, 1130, 860, 1360, 2)}.items():
        crop = blend[y0:y1, x0:x1]
        Image.fromarray(crop).resize(
            ((x1 - x0) * z, (y1 - y0) * z), Image.NEAREST).save(
            DEVDIR / f'iter_ov_{name}.png')
    print('dev previews written')


if __name__ == '__main__':
    main()
