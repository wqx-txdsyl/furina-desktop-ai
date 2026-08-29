"""NIGHT-02: write ratification_v1.json + ART_ALPHA_INDEPENDENT_RATIFICATION.md (read-only review outputs)."""
import json, os

ROOT = 'data/assets_v2'

# ---- per-asset verdict records (independent NIGHT-02 review) ----
V = {
    'a01': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Showpiece tail on viewer-LEFT (BASE: viewer-RIGHT); thigh band drawn only on viewer-right thigh (BASE band crosses both, gem at viewer-right end); face/hat/ahoge/costume pass; cane present (image_left); contact 2-foot + cane tip on G.'),
    'a02': dict(verdict='ACCEPT', tail='BASE_CONSISTENT', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-RIGHT with curled tip (matches BASE); strap band both thighs + gem viewer-right (BASE-like); face/hat/ahoge pass; cane image_left; content_px +1px vs measured (threshold noise); slight-left yaw within limits.'),
    'a03': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT while pose is slight-right (inverted); face/hat/ahoge pass; cane image_left.'),
    'a04': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); face/hat/ahoge pass; content_px +1px (noise).'),
    'a05': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='HOLD', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); detached 410px tail wisp at (625,1284)-(662,1313) — matte artifact; cane held image_right as scepter (allowed, optional prop); right hand on hip per action block.'),
    'a06': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); cane held center both hands; content_px +1px (noise).'),
    'a07': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); 6px stray speck at (579,600) recorded (negligible); crossed-arms pose clean.'),
    'a08': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); face/hat/ahoge pass.'),
    'a09': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); curious-lean pose OK otherwise.'),
    'a10': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); sleepy pose OK otherwise.'),
    'a11': dict(verdict='ACCEPT', tail='BASE_CONSISTENT', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Sitting: showpiece tail curl on viewer-RIGHT (correct); seat contact at G; height frac 0.667 (spec 0.62-0.72); face/hat/ahoge pass; cane across lap (image_left).'),
    'a12': dict(verdict='ACCEPT', tail='VIEWPOINT_JUSTIFIED', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Walking key pose: right showpiece tail longer than left (order preserved); left tail inflated vs BASE short tail but motion-justified; monitor in later frames; right hand holds cane per action block; face pass.'),
    'a13': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='HOLD', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); two detached blue droplets (112px total) below tail at (325,1256); cane behind raised arm (image_right) — mark for later layering; face/hat/ahoge pass.'),
    'a14': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); cane in other hand per action block (image_right); face pass.'),
    'a16': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='HOLD', geometry='CHAIR_EXCEPTION', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); WOODEN CHAIR baked into master while action block says "unseen writing slope" (environment art, STYLE_LOCK §11.10); cane drawn in hand while action block says "leaning beside her" — removal/layering needed; 3 stray specks near hip (20-54px); height frac 0.75 with chair.'),
    'a17': dict(verdict='ACCEPT', tail='BASE_CONSISTENT', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Speaking/presenting: right showpiece tail dominant (left tail inflated vs BASE but order preserved — note); cane held like orator (image_right); face/hat/ahoge pass; mouth open speaking.'),
    'a18': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); quiet reflective face pass; hands clasped on cane (image_left); narrowest ground contact 8px (cane tip); feet within tolerance.'),
    'a19': dict(verdict='HOLD', tail='MIRRORED_ERROR', alpha='HOLD', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Tail on viewer-LEFT (mirrored); BAKED decorative FX: detached crescent moon 200px at (304,1062), 4-point sparkle 191px at (778,1199), plus 3 small dots (STYLE_LOCK §11.9); cane absent per action block (task_prop: cake); sitting height 0.667.'),
    'a20': dict(verdict='ACCEPT', tail='BASE_CONSISTENT', alpha='CLEAN', geometry='OK', provenance='COMPLETE',
                identity='OK', notes='Playing twirl: huge showpiece tail swirl on viewer-RIGHT (correct); 23k enclosed hole = legit gap inside tail swirl loop; cane absent per action block (prop_mode none); single-foot contact plausible for twirl; face/hat/ahoge pass.'),
}

TOTALS = {
    'REVIEWED_COUNT': 19,
    'ACCEPT': [k for k, v in V.items() if v['verdict'] == 'ACCEPT'],
    'HOLD': [k for k, v in V.items() if v['verdict'] == 'HOLD'],
    'REJECT': [],
    'TAIL_BASE_CONSISTENT': [k for k, v in V.items() if v['tail'] == 'BASE_CONSISTENT'],
    'TAIL_VIEWPOINT_JUSTIFIED': [k for k, v in V.items() if v['tail'] == 'VIEWPOINT_JUSTIFIED'],
    'TAIL_MIRRORED_ERROR': [k for k, v in V.items() if v['tail'] == 'MIRRORED_ERROR'],
    'ALPHA_CLEAN': [k for k, v in V.items() if v['alpha'] == 'CLEAN'],
    'ALPHA_HOLD': [k for k, v in V.items() if v['alpha'] == 'HOLD'],
    'PROVENANCE_COMPLETE': [k for k, v in V.items() if v['provenance'] == 'COMPLETE'],
}

report = {
    'ratification': 'ART_ALPHA_INDEPENDENT_RATIFICATION_V1',
    'date': '2026-08-28',
    'reviewer_model': 'GLM-5.3-Flash (visual review, fresh session)',
    'independent_of': 'NIGHT-01 (no NIGHT-01 verdicts trusted; all 19 re-reviewed from BASE)',
    'base_sha256': '2f8e10bb17cdc325cf29954bd960e55c90208e84835dddf5b62001a5b922682a',
    'base_file': 'data/assets_v2/_base/furina-base.png',
    'generation_calls': 0,
    'production_files_changed': 0,
    'masters_modified': 0,
    'totals': {k: (len(v) if isinstance(v, list) else v) for k, v in TOTALS.items()},
    'verdicts': V,
    'a15': {
        'status': 'REJECT (unchanged)',
        'recommendation': 'REGEN_CANDIDATE',
        'rationale': 'Identity itself passed; lift/dangle semantics not realized in 3 attempts (character remains standing on ground). A standing sprite cannot procedurally produce a believable mid-air dangle (RUNTIME_PROCEDURAL would only give ground-drag translation); needs keyframe/video tooling per NIGHT-01 note (SPECIAL_ONLY class). Ground-drag response can be served procedurally from any standing master. No regeneration performed tonight.',
    },
    'alpha_diagnostics': {
        'method': '4-background composites (white/black/gray50/checkerboard) + magenta-fringe count + enclosed-hole labelling + detached-island connected components',
        'magenta_like_px': 0,
        'corner_residue': 'none (all 24px corners transparent for all 19)',
        'enclosed_holes': 'all labeled; all are legitimate pose gaps (arm/body, tail/leg, tail-swirl loop, chair-leg gaps) — no matting loss through hair/hat/clothing',
        'edge_alpha': 'soft AA edges typical of hair/outline; no hard fringing bands',
        'detached_islands': 'a05 410px tail wisp; a07 6px speck; a13 112px droplets; a16 3 specks 20-54px; a19 crescent 200px + sparkle 191px + 3 dots',
    },
    'geometry_diagnostics': {
        'canvas': 'RGBA 1024x1536 for all 19',
        'baseline': 'lowest opaque row y=1467 for all (G=1468; within 1px)',
        'standing_height_frac': '0.9167 (spec 0.88-0.94)',
        'sit_height_frac': 'a11/a19 0.6667 (spec 0.62-0.72); a16 0.75 (chair exception)',
        'com_x_frac': '0.49-0.518 for all (spec 0.50 +/-0.03)',
        'contact': 'a01 two-foot+cane-tip; a02..a20 single or dual segments on G; a18 narrowest (8px cane-tip, feet within tolerance); a20 single-foot twirl contact',
        'content_px': 'matches measured [x,y,w,h] for 15/19; a02/a04/a06/a16 differ by 1px (alpha-threshold noise)',
    },
    'runtime_scale': {
        'previews': '512/256/128 px generated read-only under review/runtime_previews/',
        'pet_size_128px': 'face, hat, ahoge, hands, shoes and silhouette readable for all 19; no silhouette collapse',
        'overview': 'review/runtime_scale_overview.png (all 19 + BASE at true 128px pet size)',
    },
    'tail_review': {
        'method': 'full-res + lower-body crop sheets vs BASE (4x inspection)',
        'ground_truth': 'BASE: long showpiece tail on her LEFT side = viewer-RIGHT, curled tip at knee level; short tail behind arm/cane on viewer-LEFT',
        'mirrored_assets': TOTALS['TAIL_MIRRORED_ERROR'],
        'note': 'MIRRORED_ERROR assets are HOLD — no automatic horizontal flip of any master; repair is targeted regeneration with anti-mirror lock wording',
    },
    'prop_review': {
        'policy': 'cane = optional prop (NIGHT-02 correction). prop_mode/cane_hand/prop_required added to manifest_v2.json entries; spec docs amended (FURINA_IDENTITY_LOCK §6/§10.7, ASSET_GEOMETRY_AND_ANCHOR_SPEC §4/§6).',
        'layering_candidates': ['a13 (cane behind raised petting arm)', 'a16 (cane should lean beside her, not be held; chair removal)'],
        'no_regen_for_cane': True,
    },
    'final_state': 'NOT_READY_FOR_HUMAN_ALPHA_RATIFICATION: 14/19 masters carry MIRRORED_ERROR showpiece tail (viewer-LEFT instead of BASE viewer-RIGHT); 4 masters carry detached-island/FX alpha defects (a05, a13, a16, a19); a16 additionally bakes a chair and a held cane contradicting its action block. 5 masters (a02, a11, a12, a17, a20) pass all gates and are ready for human alpha review.',
}

os.makedirs(os.path.join(ROOT, 'metadata'), exist_ok=True)
with open(os.path.join(ROOT, 'metadata', 'ratification_v1.json'), 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=1, ensure_ascii=False)
print('wrote ratification_v1.json')

# ---- markdown report ----
def ids(a):
    return ', '.join(a)

SEM = {e['alpha_id']: e['semantic_state'] for e in json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))['entries']}
verdict_rows = [f'| {k} | {SEM.get(k, "")} | {v["verdict"]} | {v["tail"]} | {v["alpha"]} | {v["geometry"]} | {v["notes"]} |' for k, v in V.items()]

md = f"""# ART_ALPHA_INDEPENDENT_RATIFICATION — NIGHT-02

- date: 2026-08-28
- reviewer: GLM-5.3-Flash (visual review, fresh session — NIGHT-01 verdicts NOT trusted, all 19 re-reviewed from BASE)
- base_sha256: `{report['base_sha256']}`
- generation_calls: **0** (no image-generation model invoked this session)
- production_files_changed: **0** — masters/, raw/, rejected/, _base/ images untouched
- masters_modified: **0**

## 1. Scope & method

Reviewed every master against the retained BASE (`data/assets_v2/_base/furina-base.png`, 224x320,
opaque bbox (15,7)-(216,317)) and the frozen specs (IDENTITY_LOCK V2, STYLE_LOCK V2,
GEOMETRY_AND_ANCHOR V2, TAXONOMY, TOPOLOGY). Gates per asset:

1. provenance (hashes, raw source, prompt/init md5, seeds, manifest consistency)
2. identity (face, eyes, bangs, hat, ahoge, costume, hair silhouette, proportions, camera, palette, age)
3. long-tail side (BASE_CONSISTENT / VIEWPOINT_JUSTIFIED / MIRRORED_ERROR)
4. alpha (white/black/gray50/checkerboard composites, magenta fringe, holes, detached islands, corners, edge stats)
5. geometry & contact (baseline G=1468, height fraction, center-x, feet/cane contact, anchor deltas vs A01)
6. runtime scale (512/256/128 read-only previews; pet-size readability at 128px)

## 2. Verdicts (19 reviewed)

| id | semantic | verdict | tail | alpha | geometry | notes |
|---|---|---|---|---|---|---|
{chr(10).join(verdict_rows)}

## 3. Counts

| metric | count | assets |
|---|---|---|
| REVIEWED | 19 | — |
| ACCEPT | {len(TOTALS['ACCEPT'])} | {ids(TOTALS['ACCEPT'])} |
| HOLD | {len(TOTALS['HOLD'])} | {ids(TOTALS['HOLD'])} |
| REJECT (within 19) | 0 | — |
| TAIL_BASE_CONSISTENT | {len(TOTALS['TAIL_BASE_CONSISTENT'])} | {ids(TOTALS['TAIL_BASE_CONSISTENT'])} |
| TAIL_VIEWPOINT_JUSTIFIED | {len(TOTALS['TAIL_VIEWPOINT_JUSTIFIED'])} | {ids(TOTALS['TAIL_VIEWPOINT_JUSTIFIED'])} |
| TAIL_MIRRORED_ERROR | {len(TOTALS['TAIL_MIRRORED_ERROR'])} | {ids(TOTALS['TAIL_MIRRORED_ERROR'])} |
| ALPHA_CLEAN | {len(TOTALS['ALPHA_CLEAN'])} | {ids(TOTALS['ALPHA_CLEAN'])} |
| ALPHA_HOLD | {len(TOTALS['ALPHA_HOLD'])} | {ids(TOTALS['ALPHA_HOLD'])} |
| PROVENANCE_COMPLETE | {len(TOTALS['PROVENANCE_COMPLETE'])} | all 19 |

## 4. Tail review (decisive finding)

BASE ground truth (verified from BASE and the 4x inspection): the long showpiece tail is on her
**left** side = **viewer-RIGHT**, flowing past the hip to knee level with a curling tip; a short tail
sits behind the arm/cane on viewer-LEFT; the ahoge hooks viewer-LEFT and the hat tilts viewer-RIGHT.

**14 of 19 masters place the long showpiece tail on viewer-LEFT** (a01, a03-a10, a13, a14, a16,
a18, a19) — a partial mirror (ahoge/hat are NOT mirrored). Per the NIGHT-02 rule, MIRRORED_ERROR
=> HOLD; **no automatic horizontal flip was applied to any master**. The 4 BASE_CONSISTENT assets
(a02, a11, a17, a20) plus the walking-pose VIEWPOINT_JUSTIFIED asset (a12) are ACCEPT candidates.

## 5. Alpha review

- Zero magenta-like pixels in all 19; all four 24px corners fully transparent; edges show normal
  hair/outline AA, no fringing bands.
- All enclosed holes were labelled: every one is a legitimate pose gap (arm/body, tail/leg,
  tail-swirl loop, chair-leg gaps) — no hair/hat/clothing matting loss.
- ALPHA_HOLD (4): **a05** detached 410px tail wisp (625,1284)-(662,1313); **a13** two detached blue
  droplets (112px) below the tail; **a16** three stray specks near the hip/chair (20-54px); **a19**
  baked decorative FX — detached crescent moon (200px) + 4-point sparkle (191px) + three dots,
  violating STYLE_LOCK §11.9 (no particle FX in identity masters). a07 has a negligible 6px speck.

## 6. Geometry & contact

- All 19: RGBA 1024x1536; lowest opaque row y=1467 (baseline G=1468, within 1px); center-of-mass
  x within 0.49-0.518 (spec 0.50 ±0.03); standing height fraction 0.9167 (spec 0.88-0.94);
  sitting a11/a19 0.6667 (spec 0.62-0.72).
- a16 height fraction 0.75 with a **baked chair** (action block says "unseen writing slope") —
  geometry exception + environment-art violation; the chair is not part of the runtime desktop-pet
  contract and must be removed/layered.
- content_px matches measured [x,y,w,h] for 15/19; a02/a04/a06/a16 differ by 1px (threshold noise).

## 7. Runtime scale

Read-only previews at 512/256/128px written under `review/runtime_previews/` (never overwrite
masters). At true pet size (128px) every master keeps a readable face, hat, ahoge, hands, shoes and
silhouette — no collapse. See `review/runtime_scale_overview.png`.

## 8. A15 (REJECTED, unchanged) — recommendation only

**REGEN_CANDIDATE.** Identity passed in all 3 attempts; the mid-air lift/dangle semantics never
materialized (character stands on the ground). A standing sprite cannot be made to look lifted by
runtime procedure (a ground-drag translation is possible from any standing master, but not a
believable dangle); production belongs to SPECIAL_ONLY keyframe/video tooling as NIGHT-01 noted.
No regeneration was performed this session.

## 9. Prop policy (NIGHT-02 correction applied)

Cane is an OPTIONAL prop, not an identity invariant. `prop_mode`/`cane_hand`/`prop_required`
added to all 19 manifest entries and to the spec schema; FURINA_IDENTITY_LOCK §6 and §10.7 amended.
No asset was rejected or held for cane presence/handedness. Layering candidates flagged:
a13 (cane behind the raised petting arm), a16 (cane should lean beside her, not be held; chair removal).

## 10. Final state

**NOT_READY_FOR_HUMAN_ALPHA_RATIFICATION** — 14/19 masters carry the MIRRORED_ERROR showpiece tail
(viewer-LEFT instead of BASE viewer-RIGHT); 4 masters carry detached-island/FX alpha defects
(a05, a13, a16, a19); a16 additionally bakes a chair and a held cane contradicting its action block.
The 5 clean masters (a02, a11, a12, a17, a20) are ready for human alpha review.

## 11. Next repair queue

1. P1 — tail-side regeneration for the 14 MIRRORED_ERROR assets with anti-mirror lock wording
   ("long showpiece hair tail on her left side / viewer right"); NO horizontal flip of any master.
2. P1 — a16: remove chair ("unseen writing slope"), move cane to "leaning beside her", clear specks.
3. P2 — a19: remove baked crescent/sparkle/dots; a13: remove droplets + layer cane; a05: repair
   detached tail wisp.
4. P3 — a07 6px speck; a02/a04/a06/a16 ±1px metadata refresh.
5. A15 — REGEN_CANDIDATE under SPECIAL_ONLY keyframe tooling (out of tonight's scope).
"""
with open(os.path.join(ROOT, 'ART_ALPHA_INDEPENDENT_RATIFICATION.md'), 'w', encoding='utf-8') as f:
    f.write(md)
print('wrote ART_ALPHA_INDEPENDENT_RATIFICATION.md')
