"""Shared helpers: project config (literature.json), API keys, sources table, queries file."""
import csv, json, os, re, sys
from pathlib import Path

CONFIG_NAME = 'literature.json'
LABELS = ('main', 'subject', 'approach', 'outcome', 'context', 'comparison')
DEFAULT_FUSE_LABELS = ('main', 'subject')


def find_config(explicit=None, start=None):
    """Explicit path wins; otherwise walk up from start (cwd) to the project root (first dir with .git)."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            sys.exit(f'config not found: {p}')
        return p
    d = Path(start or os.getcwd()).resolve()
    while True:
        if (d / CONFIG_NAME).is_file():
            return d / CONFIG_NAME
        if (d / '.git').exists() or d.parent == d:
            return None
        d = d.parent


def load_config(explicit=None, required=True, start=None):
    """Return the config with every path made absolute relative to the config file's folder."""
    path = find_config(explicit, start)
    if path is None:
        if required:
            sys.exit(f'No {CONFIG_NAME} found from {Path(start or os.getcwd()).resolve()} up to the project root.\n'
                     f'Create one, for example: {{"pdf_dirs": ["pdfs"], "download_dir": "pdfs", "queries": "queries.json"}}')
        return None
    try:
        cfg = json.load(open(path, encoding='utf-8'))
    except json.JSONDecodeError as e:
        sys.exit(f'{path}: not valid JSON ({e})')
    root = path.parent
    if not isinstance(cfg.get('pdf_dirs'), list) or not cfg['pdf_dirs'] or not all(isinstance(x, str) for x in cfg['pdf_dirs']):
        sys.exit(f'{path}: "pdf_dirs" must be a non-empty list of folder paths')
    for k in ('download_dir', 'sources', 'queries'):
        if k in cfg and not isinstance(cfg[k], str):
            sys.exit(f'{path}: "{k}" must be a path string')
    out = {'root': root, 'path': path, 'pdf_dirs': [(root / d).resolve() for d in cfg['pdf_dirs']]}
    out['download_dir'] = (root / cfg['download_dir']).resolve() if 'download_dir' in cfg else out['pdf_dirs'][0]
    out['sources'] = (root / cfg['sources']).resolve() if cfg.get('sources') else None
    out['queries'] = (root / cfg['queries']).resolve() if cfg.get('queries') else None
    return out


def _read_env(path):
    vals = {}
    if path.is_file():
        for line in open(path, encoding='utf-8'):
            m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if m and not line.lstrip().startswith('#'):
                vals[m.group(1)] = m.group(2).strip('\'"')
    return vals


def api_key(name, cfg=None):
    """Process environment first, then the project's .env, then ~/.config/paper-lector/.env."""
    if os.environ.get(name):
        return os.environ[name]
    for p in ([cfg['root'] / '.env'] if cfg else []) + [Path.home() / '.config/paper-lector/.env']:
        v = _read_env(p).get(name)
        if v:
            return v
    sys.exit(f'{name} is not set. Put it in the environment, in the project .env, or in ~/.config/paper-lector/.env')


def sources(cfg):
    """Optional table of known papers: key -> {'pdf': Path or None, 'doi': str}."""
    if not cfg or not cfg['sources']:
        return {}
    with open(cfg['sources'], encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if rows and 'key' not in rows[0]:
        sys.exit(f'{cfg["sources"]}: needs a "key" column')
    out = {}
    for r in rows:
        pdf = (r.get('pdf_path') or '').split(';')[0].strip()
        out[r['key']] = {'pdf': (cfg['root'] / pdf).resolve() if pdf else None, 'doi': (r.get('doi') or '').strip().lower()}
    return out


def load_queries(path):
    """Validate the queries file. Returns (question, queries in id order with empty slots removed, fuse ids)."""
    try:
        data = json.load(open(path, encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f'{path}: cannot read queries ({e})')
    Q = data.get('queries')
    if not isinstance(Q, dict) or not Q:
        sys.exit(f'{path}: needs a "queries" object, e.g. {{"Q0": {{"label": "main", "text": "...", "keywords": "..."}}}}')
    out = {}
    for qid, q in Q.items():
        if not re.fullmatch(r'Q\d+', qid):
            sys.exit(f'{path}: query id "{qid}" must look like Q0, Q1, ...')
        if q.get('label') not in LABELS:
            sys.exit(f'{path}: {qid} label "{q.get("label")}" must be one of {", ".join(LABELS)}')
        if (q.get('text') or '').strip():
            out[qid] = {'label': q['label'], 'description': q.get('description', ''), 'text': q['text'].strip(),
                        'keywords': (q.get('keywords') or '').strip()}
    if not any(q['label'] == 'main' for q in out.values()):
        sys.exit(f'{path}: a non-empty query with label "main" is required')
    out = dict(sorted(out.items(), key=lambda kv: int(kv[0][1:])))
    fuse = data.get('fuse') or [i for i, q in out.items() if q['label'] in DEFAULT_FUSE_LABELS]
    bad = [i for i in fuse if i not in out]
    if bad:
        sys.exit(f'{path}: "fuse" names missing or empty queries: {bad}')
    return data.get('question', ''), out, fuse
