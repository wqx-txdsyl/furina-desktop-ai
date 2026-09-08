"""NIGHT-03 Patch 2A R6A-R4 — reviewer-locked fail-closed ledger tests.

Reviewer task book (R6A-R3 verdict @ c38e746): the occlusion_resolution
ledger verifier must independently assert

    ledger_pixels == cane_primitive ∩ chair_primitive

and must fail closed on: a deleted ledger pixel, a duplicated ledger
pixel, a non-overlap pixel added to the ledger, and a tampered winner.
The positive case must pass on the committed delivery unchanged.

The validation function under test is
``validate_frozen_ownership`` in
``scripts/assets_v2/night03_patch2a_r6ar4_freeze_masks.py`` and the
committed delivery JSON is loaded from the R6A-R4 output directory.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[3]
           / 'scripts/assets_v2/night03_patch2a_r6ar4_freeze_masks.py')
_SOURCE = (Path(__file__).resolve().parents[3]
           / 'data/assets_v2/repair_candidates/night03_patch2a_r6ar4/'
           'a16_ownership_annotation.json')


def _load_module():
    spec = importlib.util.spec_from_file_location('r6ar4_freeze', _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_doc():
    return json.loads(_SOURCE.read_text(encoding='utf-8'))


def _validate(mod, doc, master_path):
    return mod.validate_frozen_ownership(doc, master_path,
                                         mod.ALPHA_THRESHOLD)


def test_positive_committed_delivery_passes(tmp_path):
    mod = _load_module()
    doc = _load_doc()
    validate = _validate(mod, doc, mod.MASTERS / mod.MASTER_FILE)
    assert validate['ledger_pixels'] == validate['primitive_overlap_px']
    assert validate['ledger_winners'] == [5, 6]
    assert validate['unclassified_visible_pixels'] == 0


def test_fail_closed_deleted_ledger_pixel(tmp_path):
    mod = _load_module()
    doc = _load_doc()
    entry = doc['occlusion_resolution'][0]
    assert entry['pixels'], 'entry has no pixels to delete'
    entry['pixels'].pop()
    entry['px'] -= 1
    with pytest.raises(AssertionError):
        _validate(mod, doc, mod.MASTERS / mod.MASTER_FILE)


def test_fail_closed_duplicated_ledger_pixel(tmp_path):
    mod = _load_module()
    doc = _load_doc()
    entry = doc['occlusion_resolution'][0]
    entry['pixels'].append(list(entry['pixels'][0]))
    entry['px'] += 1
    with pytest.raises(AssertionError):
        _validate(mod, doc, mod.MASTERS / mod.MASTER_FILE)


def test_fail_closed_non_overlap_pixel_added(tmp_path):
    mod = _load_module()
    doc = _load_doc()
    # a pixel far away from every primitive (plain background corner)
    entry = doc['occlusion_resolution'][0]
    entry['pixels'].append([5, 5])
    entry['px'] += 1
    with pytest.raises(AssertionError):
        _validate(mod, doc, mod.MASTERS / mod.MASTER_FILE)


def test_fail_closed_winner_tampered(tmp_path):
    mod = _load_module()
    doc = _load_doc()
    tampered = False
    for entry in doc['occlusion_resolution']:
        for pix in entry['pixels']:
            if entry['winner'] == 5:
                pix_y, pix_x = pix[1], pix[0]
                # flip this pixel's final ownership label to chair
                for row in doc['rows']:
                    if row[0] != pix_y:
                        continue
                    new_runs = []
                    for a, b, lb in row[1:]:
                        if a <= pix_x <= b:
                            if a <= pix_x - 1:
                                new_runs.append([a, pix_x - 1, lb])
                            new_runs.append([pix_x, pix_x, 6])
                            if pix_x + 1 <= b:
                                new_runs.append([pix_x + 1, b, lb])
                            tampered = True
                        else:
                            new_runs.append([a, b, lb])
                    row[1:] = new_runs
        if tampered:
            break
    assert tampered, 'could not place a tampered pixel'
    with pytest.raises(AssertionError):
        _validate(mod, doc, mod.MASTERS / mod.MASTER_FILE)
