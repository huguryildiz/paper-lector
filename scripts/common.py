"""Shared helpers: project config (literature.json), API keys, sources table, queries file, HTTP retries."""
import csv, datetime, email.utils, hashlib, http.client, json, os, re, stat, sys, time, urllib.error, urllib.request
from pathlib import Path

try:
    import fcntl
except ImportError:                                   # not on Windows
    fcntl = None

VERSION = '0.1.0'
CONFIG_NAME = 'literature.json'
LABELS = ('main', 'subject', 'approach', 'outcome', 'context', 'comparison')
DEFAULT_FUSE_LABELS = ('main', 'subject')
PROVIDERS = ('voyage', 'local')


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
                     f'Create one, for example: {{"pdf_dirs": ["pdfs"], "download_dir": "pdfs", "queries": "queries/my-topic.json"}}')
        return None
    try:
        cfg = json.load(open(path, encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f'{path}: not valid JSON in UTF-8 ({e})')
    if not isinstance(cfg, dict):
        sys.exit(f'{path}: the config must be one JSON object, for example {{"pdf_dirs": ["pdfs"]}}')
    root = path.parent
    if not isinstance(cfg.get('pdf_dirs'), list) or not cfg['pdf_dirs'] or not all(isinstance(x, str) for x in cfg['pdf_dirs']):
        sys.exit(f'{path}: "pdf_dirs" must be a non-empty list of folder paths')
    for k in ('download_dir', 'sources', 'queries'):
        if k in cfg and not isinstance(cfg[k], str):
            sys.exit(f'{path}: "{k}" must be a path string')
    rank = cfg.get('rank', {})
    if isinstance(rank, dict) and rank.get('provider') == 'bm25':
        sys.exit(f'{path}: the bm25 provider was replaced by "local" (a model2vec model, no API key): set "rank": {{"provider": "local"}}')
    if not isinstance(rank, dict) or rank.get('provider', 'voyage') not in PROVIDERS:
        sys.exit(f'{path}: "rank" must look like {{"provider": "voyage"}}; provider is one of {", ".join(PROVIDERS)}')
    out = {'root': root, 'path': path, 'pdf_dirs': [(root / d).resolve() for d in cfg['pdf_dirs']]}
    out['download_dir'] = (root / cfg['download_dir']).resolve() if 'download_dir' in cfg else out['pdf_dirs'][0]
    out['sources'] = (root / cfg['sources']).resolve() if cfg.get('sources') else None
    out['queries'] = (root / cfg['queries']).resolve() if cfg.get('queries') else None
    out['provider'] = rank.get('provider', 'voyage')
    return out


def _read_env(path):
    vals = {}
    if path.is_file():
        for line in open(path, encoding='utf-8'):
            m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if m and not line.lstrip().startswith('#'):
                v = m.group(2)
                vals[m.group(1)] = v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in '\'"' else re.sub(r'\s+#.*$', '', v)
    return vals


def api_key(name, cfg=None, required=True):
    """Process environment first, then the project's .env, then ~/.config/paper-lector/.env. Missing: exit, or None
    when not required."""
    if os.environ.get(name):
        return os.environ[name]
    for p in ([cfg['root'] / '.env'] if cfg else []) + [Path.home() / '.config/paper-lector/.env']:
        v = _read_env(p).get(name)
        if v:
            if os.name == 'posix' and p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                print(f'note: {p} holds {name} and other users can read it; run "chmod 600 {p}"', file=sys.stderr)
            return v
    if not required:
        return None
    sys.exit(f'{name} is not set. Put it in the environment, in the project .env, or in ~/.config/paper-lector/.env')


TRANSIENT = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead, http.client.BadStatusLine)


def retry(fn, tries=4, wait=10):
    """Call fn(); retry on 429/5xx, timeouts, dropped connections and cut-off bodies, raise anything else."""
    for attempt in range(tries):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1 or (e.code == 429 and retry_after(e) > 120):
                raise
        except TRANSIENT:
            if attempt == tries - 1:
                raise
        time.sleep(wait * (attempt + 1))


def retry_after(e):
    """Seconds an HTTP error's Retry-After header asks to wait (0 if none); hours means a spent daily budget."""
    v = ((e.headers or {}).get('Retry-After') or '').strip()
    if v.isdigit():
        return int(v)
    try:                                          # or an HTTP date
        return max(0, int((email.utils.parsedate_to_datetime(v) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def openalex_json(url, key, timeout):
    """GET an OpenAlex URL, keyless when key is None. A 429 with a Retry-After of hours (a spent daily budget) is
    raised at once, not retried."""
    return open_json(authorized(urllib.request.Request(url), key), timeout)


def openalex_error(e, key):
    """A message for an OpenAlex HTTPError worth stopping a search on (spent budget, refused query), else None."""
    if e.code == 429 and retry_after(e) > 120:
        return (f'OpenAlex daily budget is used up; it resets in about {retry_after(e) // 3600 + 1} h.'
                + ('' if key else ' Without a key the budget is about 100 searches a day, shared by everyone on'
                   ' this IP address; a free OPENALEX_API_KEY gives ten times that.'))
    if e.code == 400:
        try:
            msg = json.load(e).get('message')
        except (ValueError, AttributeError):
            return None
        return 'OpenAlex refused the request' + (': ' + redact(msg, key) if isinstance(msg, str) and msg else '')
    return None


def open_json(req, timeout, tries=4):
    """urlopen and parse JSON, with retry()."""
    def once():
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    return retry(once, tries)


def write_new(path, data):
    """Write bytes to path, which must not exist yet, so that a crash or a full disk never leaves a partial file
    under that name: written whole to a .part file, then hard-linked into place, which fails if path exists. Where
    hard links are not supported (FAT and exFAT drives, some network or synced folders) the .part file is renamed into
    place after a check that path is still free; only a second process writing the same name at that moment could
    then be replaced. False if path already exists; any other OSError (a full disk) is raised with nothing left."""
    path = Path(path)
    part = path.with_name(f'.{path.name}.{os.getpid()}.part')
    try:
        part.write_bytes(data)
        try:
            os.link(part, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass                                      # no hard links here
        if path.exists():
            return False
        os.rename(part, path)
        return True
    finally:
        part.unlink(missing_ok=True)


def append_line(path, line):
    """Append one line to a log file, or nothing: written unbuffered, and on a failure (a full disk, a size limit)
    the file is cut back to its old length, so the log never ends in a broken line."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX)            # another run appending meanwhile would be cut back with us
        size = os.fstat(fd).st_size
        data = (line.rstrip('\n') + '\n').encode('utf-8')
        try:
            while data:
                data = data[os.write(fd, data):]
        except OSError:
            os.ftruncate(fd, size)
            raise
    finally:
        os.close(fd)


def redact(text, *secrets):
    """text with every given secret (an API key) replaced by ***, for messages that quote a server's answer."""
    for k in secrets:
        if k and len(k) >= 8:                         # a real key; a short test value would blank ordinary words
            text = text.replace(k, '***')
    return text


def authorized(req, key):
    """Add the key as a Bearer header that urllib does not copy onto a redirected request, so a redirect to another
    host never carries it."""
    if key:
        req.add_unredirected_header('Authorization', 'Bearer ' + key)
    return req


def norm_id(x):
    """('doi', '10.x/y') or ('arxiv', '2205.06300') or ('openalex', 'W123'). DOIs are lowercased; an arXiv DOI
    (10.48550/arXiv.N) becomes its arXiv id, without a version (v2); doi.org, arxiv.org and openalex.org URLs (and a
    DOI URL's ?query or #fragment) and doi:/arXiv: prefixes go."""
    kind, v = _norm_id(x)
    return (kind, re.sub(r'v\d+$', '', v)) if kind == 'arxiv' else (kind, v)


def _norm_id(x):
    x = x.strip()
    if re.match(r'(?i)^(?:https?://)?(?:www\.|dx\.)?doi\.org/', x):
        x = re.split(r'[?#]', re.sub(r'(?i)^(?:https?://)?(?:www\.|dx\.)?doi\.org/', '', x))[0]
    x = re.sub(r'(?i)^doi:', '', x)
    m = re.match(r'(?i)^(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/(.+?)(?:\.pdf)?$', x)
    if m:
        return 'arxiv', m.group(1)
    m = re.match(r'(?i)^(?:https?://)?(?:api\.)?openalex\.org/(?:works/)?(W\d+)$|^(W\d+)$', x)
    if m:
        return 'openalex', m.group(1) or m.group(2)
    if x.startswith('10.'):
        m = re.match(r'(?i)^10\.48550/arxiv\.(.+)$', x)
        return ('arxiv', m.group(1)) if m else ('doi', x.lower())
    return 'arxiv', re.sub(r'(?i)^arxiv:', '', x)


def doi_of(x):
    """The DOI OpenAlex files a DOI or arXiv id under (lowercase), or None for an OpenAlex id."""
    kind, v = norm_id(x)
    return v if kind == 'doi' else ('10.48550/arxiv.' + v.lower()) if kind == 'arxiv' else None


def sha256_file(path):
    """SHA-256 of a file, read in 1 MB chunks."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sources(cfg):
    """Optional table of known papers: key -> {'pdf': Path or None, 'doi': str}."""
    if not cfg or not cfg['sources']:
        return {}
    if not cfg['sources'].is_file():
        print(f'note: sources table {cfg["sources"]} not found; continuing without it', file=sys.stderr)
        return {}
    with open(cfg['sources'], encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if rows and 'key' not in rows[0]:
        sys.exit(f'{cfg["sources"]}: needs a "key" column')
    out = {}
    for n, r in enumerate(rows, 2):
        if not (r['key'] or '').strip():
            sys.exit(f'{cfg["sources"]} line {n}: empty "key"; every row needs one (it names the paper in the results)')
        if r['key'] in out:
            sys.exit(f'{cfg["sources"]}: key "{r["key"]}" appears twice; keys must be unique')
        pdf = (r.get('pdf_path') or '').split(';')[0].strip()
        doi = (r.get('doi') or '').strip()
        out[r['key']] = {'pdf': (cfg['root'] / pdf).resolve() if pdf else None, 'doi': doi_of(doi) if doi else ''}
    return out


NAME_MAX = 25


def valid_name(name):
    """A short output name: lowercase letters, digits and single hyphens, at most NAME_MAX characters."""
    return isinstance(name, str) and len(name) <= NAME_MAX and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name))


def load_queries(path):
    """Validate the queries file. Returns (question, queries in id order with empty slots removed, fuse ids)."""
    try:
        data = json.load(open(path, encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f'{path}: cannot read queries ({e})')
    if not isinstance(data, dict):
        sys.exit(f'{path}: the file must hold one JSON object with "question", "queries" and "fuse"')
    Q = data.get('queries')
    name = data.get('name')
    if name is not None and not valid_name(name):
        sys.exit(f'{path}: "name" must be lowercase letters, digits and single hyphens, at most {NAME_MAX} characters '
                 f'(for example "entanglement-scheduling"); it names the output files')
    if not isinstance(Q, dict) or not Q:
        sys.exit(f'{path}: needs a "queries" object, e.g. {{"Q0": {{"label": "main", "text": "...", "keywords": "..."}}}}')
    out = {}
    for qid, q in Q.items():
        if not re.fullmatch(r'Q\d+', qid):
            sys.exit(f'{path}: query id "{qid}" must look like Q0, Q1, ...')
        if not isinstance(q, dict):
            sys.exit(f'{path}: {qid} must be an object with "label", "text" and "keywords"')
        if q.get('label') not in LABELS:
            sys.exit(f'{path}: {qid} label "{q.get("label")}" must be one of {", ".join(LABELS)}')
        for k in ('text', 'keywords', 'description'):
            if q.get(k) is not None and not isinstance(q[k], str):
                sys.exit(f'{path}: {qid} "{k}" must be a string')
        if (q.get('text') or '').strip():
            out[qid] = {'label': q['label'], 'description': q.get('description', ''), 'text': q['text'].strip(),
                        'keywords': (q.get('keywords') or '').strip()}
    if not any(q['label'] == 'main' for q in out.values()):
        sys.exit(f'{path}: a non-empty query with label "main" is required')
    out = dict(sorted(out.items(), key=lambda kv: int(kv[0][1:])))
    fuse = data['fuse'] if 'fuse' in data else [i for i, q in out.items() if q['label'] in DEFAULT_FUSE_LABELS]
    if not isinstance(fuse, list) or not fuse or not all(isinstance(i, str) for i in fuse):
        sys.exit(f'{path}: "fuse" must be a non-empty list of query ids, e.g. ["Q0", "Q1"]')
    if len(set(fuse)) != len(fuse):
        sys.exit(f'{path}: "fuse" names a query twice: {fuse}')
    bad = [i for i in fuse if i not in out]
    if bad:
        sys.exit(f'{path}: "fuse" names missing or empty queries: {bad}')
    return data.get('question', ''), out, fuse
