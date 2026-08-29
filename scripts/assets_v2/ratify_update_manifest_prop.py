"""NIGHT-02: add prop_mode / cane_hand / prop_required to manifest entries (cane = optional prop)."""
import json, os

PATH = 'data/assets_v2/metadata/manifest_v2.json'
m = json.load(open(PATH, encoding='utf-8'))

PROP = {
    'a01': ('cane', 'image_left', False),
    'a02': ('cane', 'image_left', False),
    'a03': ('cane', 'image_left', False),
    'a04': ('cane', 'image_left', False),
    'a05': ('cane', 'image_right', False),
    'a06': ('cane', 'image_left', False),
    'a07': ('cane', 'image_left', False),
    'a08': ('cane', 'image_left', False),
    'a09': ('cane', 'image_left', False),
    'a10': ('cane', 'image_left', False),
    'a11': ('cane', 'image_left', False),
    'a12': ('cane', 'image_left', False),
    'a13': ('cane', 'image_right', False),
    'a14': ('cane', 'image_right', False),
    'a16': ('task_prop', 'image_right', False),
    'a17': ('cane', 'image_right', False),
    'a18': ('cane', 'image_left', False),
    'a19': ('task_prop', 'none', False),
    'a20': ('none', 'none', False),
}

changed = 0
for e in m['entries']:
    aid = e['alpha_id']
    if aid in PROP:
        pm, ch, pr = PROP[aid]
        e['prop_mode'] = pm
        e['cane_hand'] = ch
        e['prop_required'] = pr
        changed += 1
m['prop_policy'] = {
    'rule': 'cane is an OPTIONAL prop, not an identity invariant (see FURINA_IDENTITY_LOCK amendment 2026-08-28)',
    'prop_mode': 'none | cane | task_prop',
    'cane_hand': 'none | image_left | image_right',
    'prop_required': False,
    'note': 'cane_hand records the IMAGE side where the cane is drawn; only spatial continuity within one continuous animation is required',
}
with open(PATH, 'w', encoding='utf-8') as f:
    json.dump(m, f, indent=1, ensure_ascii=False)
print('entries updated:', changed)
