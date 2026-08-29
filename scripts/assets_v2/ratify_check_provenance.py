"""NIGHT-02 independent ratification — provenance & file integrity checks (read-only)."""
import hashlib, json, os, sys

ROOT = 'data/assets_v2'

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

base = os.path.join(ROOT, '_base', 'furina-base.png')
print('BASE_SHA256:', sha256(base))
print('BASE_MD5:', md5(base))

m = json.load(open(os.path.join(ROOT, 'metadata', 'manifest_v2.json'), encoding='utf-8'))
problems = []
rows = []
for e in m['entries']:
    aid = e['alpha_id']
    mf = e['master_file'].replace('\\', '/')
    src = e['source_generation']
    raw = os.path.join(ROOT, 'raw', src['raw_file'])
    row = {'alpha_id': aid, 'seed': src.get('seed'), 'model': src.get('model'),
           'mode': src.get('mode'), 'raw_file': src['raw_file']}
    if not os.path.exists(mf):
        problems.append((aid, 'missing master', mf))
    if not os.path.exists(raw):
        problems.append((aid, 'missing raw', raw))
    else:
        row['raw_md5'] = md5(raw)
        pf = raw.replace('.png', '.prov.json')
        if not os.path.exists(pf):
            problems.append((aid, 'missing prov', pf))
        else:
            prov = json.load(open(pf, encoding='utf-8'))
            row['prov_keys'] = sorted(prov.keys())
            row['prov'] = prov
            # cross-check raw md5 recorded anywhere in prov
            raw_md5_in_prov = prov.get('raw_md5') or prov.get('raw_file_md5') or prov.get('output_md5')
            if raw_md5_in_prov and raw_md5_in_prov != row['raw_md5']:
                problems.append((aid, 'raw md5 mismatch prov', raw_md5_in_prov))
            # prompt hash cross-check: recompute md5 of prompt text in prov if present
            pm = src.get('prompt_md5')
            row['prompt_md5_manifest'] = pm
            row['prompt_md5_prov'] = prov.get('prompt_md5')
            if pm and prov.get('prompt_md5') and pm != prov['prompt_md5']:
                problems.append((aid, 'prompt_md5 manifest != prov', pm, prov['prompt_md5']))
            if src.get('seed') != prov.get('seed'):
                problems.append((aid, 'seed mismatch', src.get('seed'), prov.get('seed')))
            if src.get('model') and prov.get('model') and src['model'] != prov['model']:
                problems.append((aid, 'model mismatch', src['model'], prov['model']))
    if src.get('init_image_md5') != md5(base):
        problems.append((aid, 'init_image_md5 mismatch BASE', src.get('init_image_md5')))
    cand = e.get('candidate_file', '').replace('\\', '/')
    if cand and not os.path.exists(cand):
        problems.append((aid, 'missing candidate', cand))
    mf_meta = mf.replace('.png', '.meta.json')
    if not os.path.exists(mf_meta):
        problems.append((aid, 'missing meta', mf_meta))
    else:
        meta = json.load(open(mf_meta, encoding='utf-8'))
        for k in ('asset_id', 'alpha_id', 'canvas_width', 'canvas_height'):
            if k in e and meta.get(k) != e[k]:
                problems.append((aid, f'meta/manifest {k} mismatch', meta.get(k), e[k]))
        if meta.get('source_generation', {}).get('raw_file') != src['raw_file']:
            problems.append((aid, 'meta raw_file mismatch'))
    rows.append(row)

print('PROBLEMS:', len(problems))
for p in problems:
    print('  !', p)
print()
for r in rows:
    print(r['alpha_id'], r['seed'], r['mode'], '| raw_md5:', (r.get('raw_md5') or 'n/a')[:8],
          '| prompt match:', r.get('prompt_md5_manifest') == r.get('prompt_md5_prov'))
    print('   prov keys:', r.get('prov_keys'))
