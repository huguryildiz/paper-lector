"""Rank a PDF collection against frozen research-question slots and give a reading order with starting pages.

Method:
  1. Whole PDF through pdftotext; the bibliography is cut after a References heading or, with none, from the
     first numbered entry in the second half that more entries follow; appendices and supplementary material stay.
  2. 1,200-token windows with 200-token overlap (Voyage's tokenizer), each labelled with its PDF pages. Windows leave
     out the head of step 4 (the abstract, or the opening 1,000 tokens), which the reranker reads first anyway.
  3. Per paper and query, windows are ranked by Reciprocal Rank Fusion (k = 60) of voyage-4-large cosine
     and BM25 on the query's keyword string ("hybrid"), or by cosine alone ("dense"); the top 3 are kept.
  4. rerank-3 scores every paper once per query on its abstract (from --abstracts when the paper is in the search
     results, else read from the PDF, else its first 1,000 tokens) plus the 3 windows.
  5. fused_rank = RRF over the queries listed in "fuse" (default: main and subject). A reading order only.
  6. With --abstracts <search JSONL>, every paper is also ranked on its abstract alone (abs_fused_rank), including
     search results with no PDF (source abstract_only). Abstract-only scores run lower than full-text ones, so the two
     orders are kept apart: fused_rank covers full_text papers, abs_fused_rank all papers with an abstract.

  Provider "bm25" (literature.json "rank": {"provider": "bm25"}, or --provider bm25) needs no API key: windows are
  chosen by BM25 alone and each paper is scored by BM25 on the same abstract plus 3 windows. Output: <out>_<name>_rank-bm25.csv.

  Voyage embeddings are cached in ~/.cache/paper-lector/embeddings.sqlite (key: model, input type, text), so a
  rerun or a run resumed after a crash only pays for new text. Table src ties each vector to its PDF's SHA-256 and
  window number and pages (or to the queries hash and query id).

  rank.py --setup                         # once, online: checks pdftotext, downloads the tokenizer
  rank.py --dry                           # counts and token estimate, no API call
  rank.py                                 # writes runs/<date>_<time>_<name>_rank.csv and _rank_run.json, logs questions.jsonl
"""
import argparse, csv, datetime, hashlib, json, math, os, re, shutil, sqlite3, subprocess, sys, urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

EMBED, RERANK = 'voyage-4-large', 'rerank-3'
WIN, STEP, RRF_K, N_WIN, MAX_OVERLAP, HEAD = 1200, 1000, 60, 3, 0.2, 1000
EMBED_BATCH, RERANK_BATCH, MAX_ITEMS = 100_000, 500_000, 1000     # Voyage: at most 1,000 inputs or documents per call
RERANK_PAIR = 32_000                                                 # rerank-3 context: query + one document
PDFTOTEXT_SECONDS = 300
TOK_REV = 'bb931c2635a93efe400c24741363d8ff61d7bb32'
TOK_URL = f'https://huggingface.co/voyageai/voyage-4-large/resolve/{TOK_REV}/tokenizer.json'
TOK_SHA = 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539'
TOK_PATH = Path.home() / '.cache/paper-lector/voyage-4-large-tokenizer.json'
CACHE = Path.home() / '.cache/paper-lector/embeddings.sqlite'
STOP = set('a an the of for and or in on with to via under by at as is are be been was were this that these those it its '
           'from into over than then which when where while what who how does do can not no '
           've ile bir bu şu için da de olan olarak gibi daha en çok her ise veya ya ki ne'.split())
KEY = None


def call(ep, body):
    req = urllib.request.Request(f'https://api.voyageai.com/v1/{ep}', json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + KEY, 'content-type': 'application/json'})
    return common.open_json(req, timeout=600)


def embed(items, input_type, usage, srcs):
    """Unit-norm embeddings for (text, tokens) items. Cached vectors are reused; new ones are stored after each
    API batch, so a crashed run resumes without paying again. Stored as float32 whether fresh or cached.
    srcs gives each item's origin, (ref, part, pages): a window is (PDF SHA-256, window number in that PDF, its pages),
    a query is (queries hash, query id, ''). They go to table src, cached items too, so a vector can be traced back to
    a paper; one text met in two PDFs has one vector and two src rows."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE)
    db.execute('create table if not exists emb (key text primary key, vec blob)')
    db.execute('create table if not exists src (key text, kind text, ref text, part text, pages text, tokens integer, '
               'first_seen text, primary key (key, ref, part))')
    keys = [hashlib.sha256(f'{EMBED}\0{input_type}\0{t}'.encode()).hexdigest() for t, _ in items]
    vec = {}
    for k in dict.fromkeys(keys):
        row = db.execute('select vec from emb where key = ?', (k,)).fetchone()
        if row:
            vec[k] = np.frombuffer(row[0], np.float32)
    cached = len(vec)
    todo = list({k: it for k, it in zip(keys, items) if k not in vec}.items())
    for part in batches(todo, lambda x: x[1][1], EMBED_BATCH, MAX_ITEMS):
        r = call('embeddings', {'input': [it[0] for _, it in part], 'model': EMBED, 'input_type': input_type, 'truncation': False})
        usage['embed'] += r['usage']['total_tokens']
        for (k, _), x in zip(part, r['data']):
            vec[k] = np.asarray(x['embedding'], np.float32)
        db.executemany('insert or replace into emb values (?, ?)', [(k, vec[k].tobytes()) for k, _ in part])
        db.commit()
    now = datetime.datetime.now().isoformat(timespec='seconds')      # after the vectors, so every src row has one
    db.executemany('insert or ignore into src values (?, ?, ?, ?, ?, ?, ?)',
                   [(k, input_type, ref, str(i), pages, n, now) for k, (_, n), (ref, i, pages) in zip(keys, items, srcs)])
    db.commit()
    db.close()
    usage['embed_cached'] += cached
    E = np.array([vec[k] for k in keys], float)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


def tokenizer():
    """Voyage's tokenizer at a pinned revision, downloaded once into the cache and checked against its SHA-256.
    A partial download never lands at TOK_PATH."""
    from tokenizers import Tokenizer
    if not TOK_PATH.exists():
        TOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        part = TOK_PATH.with_suffix('.part')
        try:
            urllib.request.urlretrieve(TOK_URL, part)
        except OSError as e:
            part.unlink(missing_ok=True)
            sys.exit(f'cannot download the tokenizer ({e}). rank.py needs it once, also with --dry and bm25: connect to the '
                     f'internet and run "rank.py --setup", or copy {TOK_URL} to {TOK_PATH}')
        if common.sha256_file(part) != TOK_SHA:
            part.unlink()
            sys.exit(f'the tokenizer downloaded from {TOK_URL} does not match its pinned SHA-256; not used')
        part.replace(TOK_PATH)
    if common.sha256_file(TOK_PATH) != TOK_SHA:
        sys.exit(f'{TOK_PATH} is not the pinned tokenizer (revision {TOK_REV[:7]}). Delete it and run "rank.py --setup"')
    return Tokenizer.from_file(str(TOK_PATH))


def need_pdftotext():
    if not shutil.which('pdftotext'):
        sys.exit('pdftotext not found. Install poppler: "brew install poppler" (macOS), '
                 '"sudo apt install poppler-utils" (Debian/Ubuntu), "conda install -c conda-forge poppler" (Windows)')


def digest(path):
    return common.sha256_file(path)


def find_pdfs(dirs, known, ids=None, allow_empty=False):
    """Paper id -> PDF. Papers in the sources table keep their key; every other PDF is named by its file stem.
    A byte-identical copy of a PDF already found is skipped with a note."""
    out = {k: v['pdf'] for k, v in known.items() if v['pdf'] and v['pdf'].is_file()}
    taken = {p.resolve() for p in out.values()}
    seen = {}
    for k, p in list(out.items()):
        d = digest(p)
        if d in seen:
            print(f'note: {p} is the same file as {out[seen[d]]}; skipped', file=sys.stderr); del out[k]
        else:
            seen[d] = k
    gone = [str(d) for d in dirs if not Path(d).is_dir()]
    if gone:
        sys.exit(f'PDF folder not found: {", ".join(gone)}. Check "pdf_dirs" in the config or --dirs')
    for d in dirs:
        for p in sorted(Path(d).rglob('*.pdf')):
            if p.resolve() in taken:
                continue
            d = digest(p)
            if d in seen:
                print(f'note: {p} is the same file as {out[seen[d]]}; skipped', file=sys.stderr); continue
            pid, n = p.stem, 2
            while pid in out:
                pid, n = f'{p.stem}-{n}', n + 1
            if pid != p.stem:
                print(f'note: {p} has the same name as {out[p.stem]}; ranked as {pid}', file=sys.stderr)
            out[pid] = p; taken.add(p.resolve()); seen[d] = pid
    if ids:
        # An id read back from our own CSV may carry the ' that cell() put in front of it.
        ids = [i[1:] if i not in out and i[:1] == "'" and cell(i[1:]) == i and i[1:] in out else i for i in ids]
        missing = [i for i in ids if i not in out]
        if missing:
            sys.exit(f'no PDF for {missing}')
        out = {i: out[i] for i in ids}
    if not out and not allow_empty:
        sys.exit(f'no PDFs in {", ".join(map(str, dirs))}. Add PDFs there, or search and fetch them first')
    return out


# Section headings by language: English, Turkish, German, French, Spanish, Italian, Portuguese, Russian.
# The ' ?' variants cover pdftotext splitting a spaced-out first letter ("R EFERENCES").
BIB = (r'r ?eferences|b ?ibliography|kaynaklar|kaynakça|literatur|literaturverzeichnis|quellenverzeichnis'
       r'|r[ée]f[ée]rences(?: bibliographiques)?|bibliographie|referencias(?: bibliogr[aá]ficas)?|bibliograf[ií]a'
       r'|riferimenti(?: bibliografici)?|refer[êe]ncias(?: bibliogr[aá]ficas)?|литература|список литературы'
       r'|библиография|список использованных источников')
APPENDIX = (r'a ?ppendix\b|a ?ppendices\b|s ?upplement(?:al|ary)\s+(?:materials?|information|notes?|methods)\b|ekler\b|ek\s*[A-Z0-9]?\s*$|anhang\b|annexes?\b'
            r'|ap[ée]ndices?\b|anexos?\b|appendice\b|ap[êe]ndices?\b|приложени[ея]\b')
ABSTRACT = r'abstract|özet|öz|zusammenfassung|kurzfassung|r[ée]sum[ée]|resumen|riassunto|resumo|аннотация|реферат'
INTRO = (r'i ?ntroduction|g[iİ]r[iİ][şŞ]|einleitung|einführung|introducci[oó]n|introduzione|introdu[çc][ãa]o'
         r'|введение')
CITES = [r'(?m)^\s*\[\d+\]', r'\(\d{4}\)|, \d{4}\.', r'(?m)^\s*\d{1,3}\.\s+\S.*\b(?:19|20)\d{2}\b']


def numbered_refs(tail):
    """True when tail opens a reference list with no heading: entries numbered 1, 2, 3, ... in order, as "[n]" or
    "n.", at least 3 of them, and nearly every entry holds a year. Numbered body paragraphs or lists have no years."""
    for pat in (r'(?m)^\s*\[(\d{1,3})\]\s', r'(?m)^\s*(\d{1,3})\.\s'):
        ms = list(re.finditer(pat, tail))
        n = 0
        while n < len(ms) and int(ms[n].group(1)) == n + 1:
            n += 1
        if n < 3:
            continue
        ends = [m.start() for m in ms[1:n]] + [ms[n].start() if n < len(ms) else len(tail)]
        dated = sum(bool(re.search(r'\b(?:1[89]|20)\d{2}\b', tail[m.start():e])) for m, e in zip(ms[:n], ends))
        if dated >= max(3, 0.8 * n):
            return True
    return False


def clean(text):
    """Cut the bibliography if a References heading (in any language in BIB) in the second half is followed by
    citation entries; with no such heading (APS and Nature styles print none), cut from the first entry "[1]" or
    "1. Author ... year" in the second half that is followed by more entries. Keep appendices."""
    heads = [m for m in re.finditer(rf'(?m)^\s*(?:[IVX]+\.\s*|\d+\.?\s*)?({BIB})\s*:?\s*$', text, re.I)
             if m.start() > len(text) * 0.5]
    cites = lambda at: any(len(re.findall(c, text[at:at + 5000])) >= 3 for c in CITES)
    start = heads[-1].start() if heads and cites(heads[-1].start()) else None
    if start is None:
        start = next((m.start() for m in re.finditer(r'(?m)^\s*(?:\[1\]|1\.)\s', text)
                      if m.start() > len(text) * 0.5 and numbered_refs(text[m.start():m.start() + 6000])), None)
    if start is None:
        return text, False, None
    app = re.search(rf'(?m)^\s*(?:[A-Z]\.?\s*)?({APPENDIX})', text[start:], re.I)
    if not app:
        return text[:start], True, None
    return text[:start] + text[start + app.start():], True, (start, app.start())


def abstract(text):
    """The abstract and its character span in text, or (None, None)."""
    m = re.search(rf'\b(?:{ABSTRACT})\b\W{{0,3}}(.{{300,3000}}?)(?=\b(?:I\.|1\.?)?\s*(?:{INTRO})\b)',
                  text[:15000], re.I | re.S)
    return (m.group(1).strip(), m.span(1)) if m else (None, None)


class ExtractError(Exception):
    pass


def pdf_pages(path):
    """Page texts from pdftotext. A failed or slow extraction raises ExtractError rather than ranking partial text."""
    try:
        r = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, errors='replace',
                           timeout=PDFTOTEXT_SECONDS)
    except subprocess.TimeoutExpired:
        raise ExtractError(f'pdftotext took more than {PDFTOTEXT_SECONDS} s')
    if r.returncode:
        raise ExtractError(f'pdftotext failed (exit {r.returncode}): {r.stderr.strip()[:200]}')
    pages = r.stdout.split('\f')
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()                      # pdftotext ends every page with a form feed, so the last piece is empty
    return pages


def windows(path, tok):
    pages = pdf_pages(path)
    starts, text = [], ''
    for p in pages:
        starts.append(len(text)); text += re.sub(r'[ \t]+', ' ', p) + '\n'
    body, cut, shift = clean(text)
    enc = tok.encode(body, add_special_tokens=False)
    orig = lambda c: c + shift[1] if shift and c >= shift[0] else c
    page_of = lambda c: sum(1 for s in starts if s <= orig(c))
    ab, ab_span = abstract(body)
    head = ab if ab else tok.decode(enc.ids[:HEAD])
    # The reranker reads the head before the windows, so a window leaves out the head's tokens [h0, h1) (the abstract,
    # or the opening HEAD tokens when none is found): its text, token spans and page label cover only the rest, and
    # 'full' keeps the whole window. A window that is all head stays whole.
    off = enc.offsets
    if ab_span:
        h0 = next((k for k, o in enumerate(off) if o[1] > ab_span[0]), len(off))
        h1 = next((k for k, o in enumerate(off) if o[0] >= ab_span[1]), len(off))
    else:
        h0, h1 = 0, min(HEAD, len(off))

    def piece(spans):
        a, b = off[spans[0][0]][0], off[spans[-1][1] - 1][1]
        p0, p1 = page_of(a), page_of(b - 1)
        return {'text': ' '.join(re.sub(r'\s+', ' ', body[off[x][0]:off[y - 1][1]]).strip() for x, y in spans),
                'spans': spans, 'pages': f'p. {p0}' if p0 == p1 else f'p. {p0}-{p1}'}
    wins = []
    for i in range(0, max(1, len(off) - WIN + STEP), STEP):
        e = min(i + WIN, len(off))
        if i >= e:
            break
        full = piece([(i, e)])
        rest = [(x, y) for x, y in ((i, min(e, h0)), (max(i, h1), e)) if x < y]
        wins.append(dict(piece(rest) if rest else full, full=full))
    return [w for w in wins if w['text']], head, cut, ab is not None, len(enc.ids)


def near_duplicates(P, threshold=0.8):
    """Pairs of papers whose abstracts (or opening text) share most of their words: often a preprint and its
    published version, or one paper saved under two names. Reported, never dropped."""
    words = [set(w for w in re.findall(r'[^\W\d_]{4,}', lower(p['head'])) if w not in STOP) for p in P]
    pairs = []
    for i in range(len(P)):
        for j in range(i + 1, len(P)):
            if words[i] and words[j] and len(words[i] & words[j]) / len(words[i] | words[j]) >= threshold:
                pairs.append([P[i]['id'], P[j]['id']])
    return pairs


def lower(s):
    """Lowercase that keeps Turkish dotted capital I as one letter (plain str.lower adds a combining dot)."""
    return s.replace('İ', 'i').lower()


def bm25_scores(docs, query, k1=1.2, b=0.75):
    terms = lambda s: [t for t in re.split(r'[\W_]+', lower(s)) if t and t not in STOP]
    toks = [Counter(terms(d)) for d in docs]
    lens = np.array([sum(t.values()) for t in toks], float); avg = lens.mean() or 1.0
    df = Counter(t for c in toks for t in c)
    out = np.zeros(len(docs))
    for t in dict.fromkeys(terms(query)):
        idf = math.log((len(docs) - df[t] + 0.5) / (df[t] + 0.5) + 1)
        tf = np.array([c[t] for c in toks], float)
        out += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lens / avg))
    return out


def min_ranks(x):
    """1 = best; ties share the best rank."""
    x = np.asarray(x)
    return np.array([1 + int((x > v).sum()) for v in x])


def pick(wins, score):
    """The N_WIN best windows, each sharing less than MAX_OVERLAP of the smaller one's tokens with any chosen one."""
    size = lambda x: sum(b - a for a, b in x)
    shared = lambda x, y: sum(max(0, min(b, d) - max(a, c)) for a, b in x for c, d in y)
    chosen = []
    for j in sorted(range(len(wins)), key=lambda j: -score[j]):
        s = wins[j]['spans']
        ok = all(shared(s, wins[c]['spans']) / min(size(s), size(wins[c]['spans'])) < MAX_OVERLAP for c in chosen)
        if ok:
            chosen.append(j)
        if len(chosen) == N_WIN:
            break
    return chosen


def batches(items, cost, limit, max_items=MAX_ITEMS):
    cur, total = [], 0
    for it in items:
        if cur and (total + cost(it) > limit or len(cur) == max_items):
            yield cur; cur, total = [], 0
        cur.append(it); total += cost(it)
    if cur:
        yield cur


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def cell(s):
    """A paper id safe to open in a spreadsheet: a leading = + - @ (a formula there) gets a ' in front."""
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


def read_ids(path):
    """Paper ids (and SHA-256 when the CSV has that column) from a CSV with a "paper" column."""
    rows = list(csv.DictReader(open(path, encoding='utf-8-sig')))
    if not rows or 'paper' not in rows[0]:
        sys.exit(f'{path}: --ids needs a CSV with a "paper" column and at least one row')
    rows = [r for r in rows if r.get('source') != 'abstract_only']      # --ids freezes the PDF corpus only
    if not rows:
        sys.exit(f'{path}: --ids lists no paper with a PDF (only abstract_only rows); nothing to freeze')
    ids = [r['paper'] for r in rows]
    if not all(ids) or len(set(ids)) != len(ids):
        sys.exit(f'{path}: --ids has an empty or repeated paper id')
    return ids, {i: r['sha256'] for i, r in zip(ids, rows) if r.get('sha256')}


def rid(x):
    """A normalised (kind, value) id, or None for an empty or unreadable one."""
    try:
        return common.norm_id(str(x)) if x else None
    except Exception:
        return None


def words(s):
    return ' '.join(re.findall(r'\w+', (s or '').lower()))


TITLE_STOP = {'a', 'an', 'the', 'of', 'for', 'and', 'or', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at', 'from',
              'over', 'into', 'as', 'its', 'is', 'are', 'using', 'based', 'toward', 'towards'}


def same_title(a, b):
    """Two versions of one paper: normalised titles at least 95% alike letter by letter ("Fidelity-Guarantee" and
    "Fidelity-Guaranteed"); different papers with near titles stay apart (about 87% for those seen so far)."""
    import difflib
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.95


def title_cover(title, lead):
    """Share of the title's content words found, in order, at the start of the PDF (lead: its first 40 words)."""
    t = [w for w in title.split() if w not in TITLE_STOP]
    if not t:
        return 0.0
    import difflib
    m = difflib.SequenceMatcher(None, t, [w for w in lead if w not in TITLE_STOP], autojunk=False)
    return sum(b.size for b in m.get_matching_blocks()) / len(t)


def link(r, doi=None):
    """A clickable link: the DOI, else the arXiv page, else the OpenAlex page."""
    doi = (r or {}).get('doi') or doi
    if doi:
        return 'https://doi.org/' + doi
    if (r or {}).get('arxiv'):
        return 'https://arxiv.org/abs/' + r['arxiv']
    return 'https://openalex.org/' + r['openalex'] if (r or {}).get('openalex') else ''


def citation(r):
    """Authors (year). Title. Venue, volume(issue), pages. Only what the search record holds."""
    if not r:
        return ''
    names = r.get('authors') or ([r['first_author']] if r.get('first_author') else [])
    who = ', '.join(names[:3]) + (' et al.' if len(names) > 3 else '')
    b = r.get('biblio') or {}
    where = '' if not r.get('venue') else r['venue'] + (f", {b['volume']}" if b.get('volume') else '') + (f"({b['issue']})" if b.get('issue') else '') \
        + (f", {b['first_page']}" if b.get('first_page') else '') \
        + (f"\u2013{b['last_page']}" if b.get('last_page') and b.get('last_page') != b.get('first_page') else '')
    return ' '.join(x for x in (f'{who} ({r.get("year") or "n.d."}).' if who else f'({r.get("year") or "n.d."}).',
                                (r.get('title') or '').rstrip('.') + '.' if r.get('title') else '', where.strip(', ') + '.' if where.strip(', ') else '') if x)


def short_id(r, taken):
    """Surname, year and five title words, like the PDF names fetch_pdf.py writes (without the hash)."""
    surname = re.sub(r'\W', '', (r.get('first_author') or (r.get('authors') or ['Anon'])[0] or 'Anon').split()[-1])
    stop = {'a', 'an', 'the', 'of', 'for', 'and', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at'}
    w = [x for x in re.findall(r'[A-Za-z0-9]+', r.get('title') or '') if x.lower() not in stop][:5]
    base = f"{surname}{r.get('year') or ''}_{''.join(x[:1].upper() + x[1:] for x in w)}"
    pid, n = base, 2
    while pid in taken:
        pid, n = f'{base}-{n}', n + 1
    return pid


def abstract_corpus(paths, P, W, cfg, dirs):
    """Papers for the abstract order: every PDF paper (its search record's abstract, else the abstract read from the
    PDF) and every search record with no PDF (abstract_only). A record belongs to a PDF through the sources table's
    DOI, an OK line in fetch_log.jsonl, or its title on the PDF's first page."""
    recs, seen = [], set()
    for path in paths:
        for n, line in enumerate(open(path, encoding='utf-8'), 1):
            if not line.strip():
                continue
            r = json.loads(line)
            ids = {i for i in (rid(r.get('doi')), rid(r.get('openalex')), rid(r.get('arxiv'))) if i}
            if not ids:
                print(f'note: {path} line {n}: no doi, arxiv or openalex id ({r.get("title")}); left out', file=sys.stderr)
                continue
            if not ids & seen:
                recs.append((r, ids))
            seen |= ids
    sel = {p['id'] for p in P}
    owner = {}                                            # normalised id -> PDF paper id (only papers in this run)
    for key, v in common.sources(cfg).items():
        if key in sel and v['doi'] and rid(v['doi']):
            owner[rid(v['doi'])] = key
    by_path = {Path(p['path']).resolve(): p for p in P}
    logs = {f for d in list(dirs) + ([cfg['download_dir']] if cfg else []) if Path(d).is_dir()
            for f in Path(d).rglob('fetch_log.jsonl')}
    for f in sorted(logs):
        for line in open(f, encoding='utf-8'):
            e = json.loads(line)
            p = by_path.get((f.parent / e['file']).resolve()) if e.get('file') else None
            if e.get('status', 'OK') == 'OK' and p and rid(e.get('id')) and e.get('sha256', p['sha256']) == p['sha256']:
                owner[rid(e['id'])] = p['id']             # the logged file, in the log's own folder, unchanged
    first = {p['id']: words(W[p['wins'][0]]['full']['text']).split()[:40] for p in P}    # title and authors

    def by_title(t):
        """The one PDF whose opening holds, in order, at least 80% of the title's content words (titles change a
        little between preprint and print). Short titles, ties and near ties match nothing."""
        if len([w for w in t.split() if w not in TITLE_STOP]) < 4:
            return None
        cover = sorted(((title_cover(t, v), k) for k, v in first.items()), reverse=True)
        if not cover or cover[0][0] < 0.8 or (len(cover) > 1 and cover[1][0] >= cover[0][0] - 0.1):
            return None
        return cover[0][1]
    A = {p['id']: {'id': p['id'], 'source': 'full_text', 'title': '', 'text': p['head'] if p['abstract_found'] else '',
                   'from': 'pdf' if p['abstract_found'] else '', 'rec': None} for p in P}
    taken, left = set(), []
    for r, ids in recs:                                   # ids first, so a title never takes a paper a DOI owns
        pid = next((owner[i] for i in ids if i in owner), None)
        if pid is None:
            left.append(r); continue
        if pid not in taken:
            taken.add(pid)
            A[pid].update(title=r.get('title') or '', rec=r)
            if r.get('abstract'):
                A[pid].update(text=r['abstract'], **{'from': 'search'})
        # else: a second record with the same id as a paper already matched
    same = {words(A[k]['title']): k for k in taken if A[k]['title']}   # titles already held, word for word
    for r in left:
        t = words(r.get('title'))
        twin = next((k for k in same if len(t.split()) >= 4 and same_title(t, k)), None)
        if twin is not None:
            print(f'note: {r.get("doi") or r.get("openalex")} has the title of {same[twin]} (another version); '
                  f'counted once', file=sys.stderr)
            held = A[same[twin]]
            if (r.get('cited_by') or 0) > ((held['rec'] or {}).get('cited_by') or 0):   # citations of the most cited version
                held['rec'] = dict(held['rec'] or {}, **{k: r.get(k) for k in ('cited_by', 'cited_pct', 'cited_at')})
            continue
        pid = by_title(t)
        if pid is not None and pid not in taken:
            taken.add(pid)
            A[pid].update(title=r.get('title') or '', rec=r)
            if r.get('abstract'):
                A[pid].update(text=r['abstract'], **{'from': 'search'})
            same[t] = pid
            continue
        aid = short_id(r, A)
        if len(t.split()) >= 4:
            same[t] = aid
        A[aid] = {'id': aid, 'source': 'abstract_only', 'title': r.get('title') or '', 'text': r.get('abstract') or '',
                  'from': 'search' if r.get('abstract') else '', 'rec': r}
    return list(A.values())


def rel(path, cfg):
    """A path relative to the project root when it lies inside it, so the log stays valid if the project moves."""
    root = (cfg['root'] if cfg else Path.cwd()).resolve()
    path = Path(path).resolve()
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def questions_log(cfg, qfile):
    """One questions.jsonl per project, so the freeze and name checks see every queries file: beside the config's
    queries file, else in <project>/queries/; with no config, beside the queries file given."""
    if cfg:
        return (cfg['queries'].parent if cfg['queries'] else cfg['root'] / 'queries') / 'questions.jsonl'
    return qfile.parent / 'questions.jsonl'


def csv_name(out, name, variant):
    """<out>_<name>_rank.csv for the default hybrid run (name from the queries file, else paper-lector); dense and
    bm25 runs keep their variant in the file name."""
    return f'{out}_{name}_rank.csv' if variant == 'hybrid' else f'{out}_{name}_rank-{variant}.csv'


def run_name(out, name, ext='json'):
    """<out>_<name>_rank_run.json, the run record (and with ext='lock' the lock beside it)."""
    return f'{out}_{name}_rank_run.{ext}'


def stamp():
    return datetime.datetime.now().strftime('%Y-%m-%d_%H%M')


def versions():
    """Versions that change windows or scores, for the run record."""
    import platform, tokenizers
    try:
        pt = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True).stderr.split('\n')[0]
    except OSError:
        pt = ''
    return {'python': platform.python_version(), 'numpy': np.__version__, 'tokenizers': tokenizers.__version__,
            'pdftotext': pt, 'tokenizer_revision': TOK_REV}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', help=f'path to {common.CONFIG_NAME} (default: searched upward from the current folder)')
    ap.add_argument('--queries', help='queries file (default: "queries" in the config)')
    ap.add_argument('--dirs', help='comma-separated PDF folders (default: "pdf_dirs" in the config)')
    ap.add_argument('--ids', help='CSV with a "paper" column (and optionally "sha256"): rank exactly these papers (frozen corpus)')
    ap.add_argument('--provider', choices=common.PROVIDERS, help='voyage or bm25 (no API key); default: "rank" in the config, else voyage')
    ap.add_argument('--variants', default='hybrid', help='hybrid, dense or hybrid,dense (dense is an ablation); voyage only')
    ap.add_argument('--abstracts', help='comma-separated search JSONL files: also rank every paper on its abstract, '
                    'including results with no PDF (abs_fused_rank, source abstract_only)')
    ap.add_argument('--expect', default='', help='paper ids expected in the first query\'s top 10, fixed before the run')
    ap.add_argument('--budget', type=int, default=15_000_000, help='stop before any API call if the token estimate is higher')
    ap.add_argument('--dry', action='store_true', help='build windows, print counts and the token estimate; no API call')
    ap.add_argument('--out', help='output path prefix (default: runs/<date>_<time> next to the config, for example '
                    'runs/2026-10-17_2315)')
    ap.add_argument('--setup', action='store_true', help='check pdftotext and download the tokenizer once, then exit')
    a = ap.parse_args(argv)
    need_pdftotext()
    if a.setup:
        tokenizer()
        print(f'ready: pdftotext {shutil.which("pdftotext")}, tokenizer {TOK_PATH}')
        return
    cfg = common.load_config(a.config, required=not (a.dirs and a.queries))
    qpath = a.queries or (cfg and cfg['queries'])
    if not qpath:
        sys.exit('no queries file: pass --queries or set "queries" in the config')
    question, Q, fuse = common.load_queries(qpath)
    name = json.load(open(qpath, encoding='utf-8')).get('name')
    frozen = {'question': question, 'queries': Q, 'fuse': fuse}
    qsha = sha(json.dumps(dict(frozen, name=name) if name else frozen, sort_keys=True))   # older files: same hash as before
    qfile = Path(qpath).resolve()
    log = questions_log(cfg, qfile)
    seen = []
    for f in dict.fromkeys([log, qfile.parent / 'questions.jsonl']):      # and an older log beside the queries file
        for l in (open(f, encoding='utf-8') if f.is_file() else []):
            if l.strip():
                e = json.loads(l)
                e['file'] = (f.parent / e.get('queries', '')).resolve()    # "queries" is relative to its log's folder
                seen.append(e)
    if any(e['file'] == qfile and e.get('queries_sha') != qsha for e in seen):
        sys.exit(f'{qpath} was ranked before with a different question, queries or fuse list ({log}). A frozen queries '
                 f'file is not edited: write the new queries into a new file and rank that')
    same = {e.get('name') or 'paper-lector' for e in seen if e.get('question') == question}
    if same and (name or 'paper-lector') not in same:
        sys.exit(f'this question was ranked before as "{sorted(same)[0]}" ({log}); give the queries file that "name" '
                 f'so its runs keep one name')
    a.name = name or 'paper-lector'
    if not a.out:
        base = (cfg['root'] if cfg else Path.cwd()) / 'runs' / stamp()
        a.out, n = str(base), 2
        while any(Path(a.out).parent.glob(Path(a.out).name + '_*')):
            a.out, n = f'{base}-{n}', n + 1
    stem, parent = Path(a.out).name, Path(a.out).parent      # one --out holds the runs of one queries name only
    names = {f.name[len(stem) + 1:].rsplit('_rank_run.', 1)[0] for f in (parent.iterdir() if parent.is_dir() else [])
             if f.name.startswith(stem + '_') and f.name.endswith(('_rank_run.json', '_rank_run.lock'))}
    other = sorted(n for n in names - {a.name} if common.valid_name(n))
    if other or Path(f'{a.out}_run.json').exists():
        sys.exit(f'--out {a.out} already holds ' + (f'a run of "{other[0]}"' if other else 'a run of an older paper-lector')
                 + '; rank into a new --out')
    prev = Path(run_name(a.out, a.name))
    if prev.is_file() and json.loads(prev.read_text()).get('queries_sha') != qsha:
        sys.exit(f'{prev} was made with a different question, queries or fuse list. A frozen queries file is not edited: '
                 f'write a new queries file and rank it with a new --out')
    provider = a.provider or (cfg and cfg['provider']) or 'voyage'
    variants = a.variants.split(',')
    if any(v not in ('hybrid', 'dense') for v in variants):
        sys.exit('--variants takes hybrid and/or dense')
    if provider == 'bm25':
        if variants != ['hybrid']:
            sys.exit('--variants applies to the voyage provider only')
        variants = ['bm25']
    dirs = [Path(d) for d in a.dirs.split(',')] if a.dirs else cfg['pdf_dirs']
    ids, want_sha = read_ids(a.ids) if a.ids else (None, {})
    outs = [Path(run_name(a.out, a.name))] + [Path(csv_name(a.out, a.name, v)) for v in variants]
    lock = Path(run_name(a.out, a.name, 'lock'))
    if not a.dry:
        if any(p.exists() for p in outs):
            sys.exit(f'{", ".join(str(p) for p in outs if p.exists())} already exists. Rank into a new --out '
                     f'(for example with today\'s date) and compare the two runs')
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            open(lock, 'x').close()
        except FileExistsError:
            sys.exit(f'{lock} exists: another run into this --out is going on, or one stopped half-way. '
                     f'Use a new --out, or delete the lock and the partial outputs if no run is going on')
    try:
        rank(a, cfg, question, Q, fuse, qsha, provider, variants, dirs, ids, want_sha)
        if not a.dry:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'created': datetime.datetime.now().isoformat(timespec='seconds'), 'question': question,
                                    'name': a.name, 'queries': os.path.relpath(qfile, log.parent), 'queries_sha': qsha, 'fuse': fuse, 'provider': provider,
                                    'out': rel(a.out, cfg), 'abstracts': a.abstracts or ''}, ensure_ascii=False) + '\n')
    finally:
        if not a.dry:
            lock.unlink(missing_ok=True)


def rank(a, cfg, question, Q, fuse, qsha, provider, variants, dirs, ids, want_sha):
    global KEY

    tok = tokenizer()
    ntok = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
    P, W, skipped = [], [], []
    for pid, path in find_pdfs(dirs, common.sources(cfg), ids, allow_empty=bool(a.abstracts)).items():
        d = digest(path)
        want = want_sha.get(pid, want_sha.get(cell(pid)))
        if want and want != d:
            sys.exit(f'--ids: {pid} is now {path}, which is not the file of the frozen run (SHA-256 differs)')
        try:
            wins, head, cut, has_ab, n = windows(path, tok)
        except ExtractError as e:
            print(f'note: {path}: {e}; skipped', file=sys.stderr)
            skipped.append({'id': pid, 'path': str(path), 'reason': str(e)}); continue
        if not wins:
            print(f'note: no text extracted from {path} (scanned or protected?); skipped', file=sys.stderr)
            skipped.append({'id': pid, 'path': str(path), 'reason': 'no text'}); continue
        P.append({'id': pid, 'path': str(path), 'sha256': d, 'head': head, 'bib_cut': cut, 'abstract_found': has_ab, 'tokens': n,
                  'wins': list(range(len(W), len(W) + len(wins)))})
        W += [dict(w, paper=len(P) - 1) for w in wins]
    if not P and not a.abstracts:
        sys.exit('no PDFs with extractable text')
    if not P:
        print('note: no PDFs to rank on full text; the run gives the abstract order only', file=sys.stderr)
    if ids and skipped:
        sys.exit(f'--ids lists papers whose text could not be extracted: {[x["id"] for x in skipped]}; the frozen corpus is incomplete')
    dupes = near_duplicates(P)
    for x, y in dupes:
        print(f'note: {x} and {y} look like the same paper (preprint and published, or two names); both ranked', file=sys.stderr)
    A = abstract_corpus(a.abstracts.split(','), P, W, cfg, dirs) if a.abstracts else []
    AR = [x for x in A if x['text']]
    byid = {p['id']: p for p in P}
    for x in A:
        x['doc'] = 'Abstract: ' + (x['title'] + '. ' if x['from'] == 'search' and x['title'] else '') + x['text']
        if x['source'] == 'full_text' and x['from'] == 'search':
            p = byid[x['id']]
            # The text the windows left out is no longer the head: the PDF's opening, or a PDF abstract that the
            # search abstract does not cover (a different version, or a cut abstract). Then the windows get it back.
            left_out = set(words(p['head']).split()) if p['abstract_found'] else {''}
            if len(left_out - set(words(x['text']).split())) > 0.1 * len(left_out):
                for j in p['wins']:
                    W[j].update(W[j]['full'])
            p['head'] = x['text']                    # the search record's abstract beats one guessed from the PDF
    for w in W:
        w['n'] = ntok(w['text'])
        w['label_n'] = ntok(f"\n\n[{w['pages']}] ")
    # Upper bound per rerank package: "Abstract: " + head + the N_WIN largest windows with their page labels.
    head_n = [ntok('Abstract: ' + p['head']) for p in P]
    pkg_n = [h + sum(sorted((W[j]['n'] + W[j]['label_n'] for j in p['wins']), reverse=True)[:N_WIN]) for h, p in zip(head_n, P)]
    pkg = sum(pkg_n)
    estimate = sum(w['n'] for w in W) + sum(ntok(q['text']) for q in Q.values()) \
        + len(variants) * sum(pkg + ntok(q['text']) * len(P) for q in Q.values()) \
        + sum(sum(ntok(x['doc']) for x in AR) + ntok(q['text']) * len(AR) for q in Q.values())
    print(f'{len(P)} papers, {len(W)} windows, bibliography cut in {sum(p["bib_cut"] for p in P)}, '
          f'abstract found in {sum(p["abstract_found"] for p in P)}; {len(Q)} queries, fuse {fuse}; '
          + (f'estimated {estimate:,} tokens' if provider == 'voyage' else 'provider bm25, no API call'), file=sys.stderr)
    if provider == 'voyage':                 # stop before any paid call rather than on the API's refusal half-way
        qmax = max((ntok(q['text']) for q in Q.values()), default=0)
        long = [(p['id'], n) for p, n in zip(P, pkg_n) if n + qmax > RERANK_PAIR] \
            + [(x['id'], ntok(x['doc'])) for x in AR if ntok(x['doc']) + qmax > RERANK_PAIR]
        if long:
            sys.exit('no API call made: rerank-3 takes at most {:,} tokens per query and document; too long with the '
                     'longest query: {}. A search record\'s abstract is usually the cause: shorten or drop it in the '
                     'search file'.format(RERANK_PAIR, ', '.join(f'{i} ({n + qmax:,})' for i, n in long)))
    if a.abstracts:
        print(f'abstracts: {len(A)} papers, {sum(x["source"] == "abstract_only" for x in A)} without a PDF, '
              f'{sum(bool(x["title"]) for x in A if x["source"] == "full_text")} of {len(P)} PDFs matched to a search record, '
              f'{len(A) - len(AR)} with no abstract (left unranked)', file=sys.stderr)
    if a.dry:
        for p in P:
            print(p['id'], p['tokens'], len(p['wins']), 'bib' if p['bib_cut'] else '-', 'abs' if p['abstract_found'] else '-', sep='\t')
        for x in skipped:
            print(x['id'], f"skipped: {x['reason']}", sep='\t')
        for x, y in dupes:
            print(x, f'possible duplicate of {y}', sep='\t')
        return
    usage = Counter()
    if provider == 'voyage':
        if estimate > a.budget:
            sys.exit(f'estimate {estimate:,} tokens is above --budget {a.budget:,}; raise --budget to run')
        KEY = common.api_key('VOYAGE_API_KEY', cfg)
        if W:
            E = embed([(w['text'], w['n']) for w in W], 'document', usage,
                      [(P[w['paper']]['sha256'], j - P[w['paper']]['wins'][0], w['pages']) for j, w in enumerate(W)])
            QE = embed([(q['text'], ntok(q['text'])) for q in Q.values()], 'query', usage, [(qsha, i, '') for i in Q])

    abs_rows = {}
    if AR:
        for qid, q in Q.items():
            col = f'{qid}_{q["label"]}'
            if provider == 'bm25':
                sc = dict(enumerate(map(float, bm25_scores([x['doc'] for x in AR], q['keywords'] or q['text']))))
            else:
                sc, qn = {}, ntok(q['text'])
                items = [{'i': i, 'n': ntok(x['doc']) + qn} for i, x in enumerate(AR)]
                for part in batches(items, lambda k: k['n'], RERANK_BATCH, MAX_ITEMS):
                    r = call('rerank', {'query': q['text'], 'documents': [AR[k['i']]['doc'] for k in part],
                                        'model': RERANK, 'truncation': False})
                    usage['rerank'] += r['usage']['total_tokens']
                    for x in r['data']:
                        sc[part[x['index']]['i']] = x['relevance_score']
            for i, x in enumerate(AR):
                row = abs_rows.setdefault(x['id'], {})
                row[f'{col}_abs_rank'] = 1 + sum(1 for v in sc.values() if v > sc[i])
                row[f'{col}_abs_score'] = round(sc[i], 4)
        for row in abs_rows.values():
            row['_afs'] = sum(1 / (RRF_K + row[f'{qid}_{Q[qid]["label"]}_abs_rank']) for qid in fuse)
        for row in abs_rows.values():
            row['abs_fused_rank'] = 1 + sum(1 for o in abs_rows.values() if o['_afs'] > row['_afs'])
            row['abs_fused_score'] = round(row['_afs'], 6)

    outputs = {}
    for variant in variants:
        rows = {p['id']: {'paper': p['id']} for p in P}
        sanity = None
        for qi, (qid, q) in enumerate(Q.items() if P else []):      # no PDFs: abstract order only
            col = f'{qid}_{q["label"]}'
            cos = E @ QE[qi] if variant != 'bm25' else None
            lex = bm25_scores([w['text'] for w in W], q['keywords'] or q['text']) if variant != 'dense' else None
            pkgs = []
            for pi, p in enumerate(P):
                idx = p['wins']
                score = 1 / (RRF_K + min_ranks(cos[idx])) if cos is not None else np.zeros(len(idx))
                if lex is not None:
                    l = lex[idx]
                    score = score + np.where(l > 0, 1 / (RRF_K + min_ranks(l)), 0)
                chosen = [idx[k] for k in pick([W[j] for j in idx], score)]
                text = 'Abstract: ' + p['head'] + ''.join(f"\n\n[{W[j]['pages']}] {W[j]['text']}" for j in chosen)
                pkgs.append({'pi': pi, 'text': text, 'n': ntok(text), 'pages': '; '.join(W[j]['pages'] for j in chosen)})
            qn, score = ntok(q['text']), {}
            if variant == 'bm25':
                score = {k['pi']: float(v) for k, v in zip(pkgs, bm25_scores([k['text'] for k in pkgs], q['keywords'] or q['text']))}
            for part in (batches(pkgs, lambda k: k['n'] + qn, RERANK_BATCH, MAX_ITEMS) if variant != 'bm25' else []):
                r = call('rerank', {'query': q['text'], 'documents': [k['text'] for k in part], 'model': RERANK, 'truncation': False})
                usage['rerank'] += r['usage']['total_tokens']
                for x in r['data']:
                    score[part[x['index']]['pi']] = x['relevance_score']
            for k in pkgs:
                row = rows[P[k['pi']]['id']]
                row[f'{col}_rank'] = 1 + sum(1 for v in score.values() if v > score[k['pi']])
                row[f'{col}_score'] = round(score[k['pi']], 4)
                row[f'{col}_pages'] = k['pages']
            if sanity is None:
                sanity = [P[i]['id'] for i in sorted(score, key=lambda i: (-score[i], P[i]['id']))[:10]]
        cols = {qid: f'{qid}_{q["label"]}' for qid, q in Q.items()}
        for r in rows.values():
            r['_fs'] = sum(1 / (RRF_K + r[f'{cols[q]}_rank']) for q in fuse)
        for r in rows.values():
            r['fused_rank'] = 1 + sum(1 for o in rows.values() if o['_fs'] > r['_fs'])
            r['fused_score'] = round(r['_fs'], 6)
        first = cols[next(iter(Q))]
        order = sorted(rows.values(), key=lambda r: (-r['_fs'], r[f'{first}_rank'], r['paper']))
        meta = {p['id']: p for p in P}
        head = ['paper', 'link', 'citation', 'fused_rank', 'fused_score', 'cited_by', 'cited_pct', 'cited_at'] + [f'{c}_{s}' for c in cols.values() for s in ('rank', 'score')] \
            + [f'{c}_pages' for c in cols.values()] + ['tokens', 'bib_cut', 'abstract_found', 'source']
        if a.abstracts:
            head += ['abs_fused_rank', 'abs_fused_score'] + [f'{c}_abs_{s}' for c in cols.values() for s in ('rank', 'score')] \
                + ['abstract_from']
        known = common.sources(cfg)
        info = {x['id']: dict(abs_rows.get(x['id'], {}), abstract_from=x['from'], source=x['source'],
                              link=link(x['rec'], (known.get(x['id']) or {}).get('doi')), citation=citation(x['rec']),
                              **{k: (x['rec'] or {}).get(k) for k in ('cited_by', 'cited_pct', 'cited_at')}) for x in A}
        for pid in meta:
            info.setdefault(pid, {'link': link(None, (known.get(pid) or {}).get('doi'))})
        extra = sorted((x for x in A if x['source'] == 'abstract_only'),
                       key=lambda x: (info[x['id']].get('abs_fused_rank', math.inf), x['id']))
        path = Path(csv_name(a.out, a.name, variant)); path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(head)
            for r in order:
                m = dict(meta[r['paper']], source='full_text', **{k: v for k, v in info.get(r['paper'], {}).items() if k != 'source'})
                w.writerow([cell(r['paper'])] + [r.get(h, m.get(h)) for h in head[1:]])
            for x in extra:
                w.writerow([cell(x['id'])] + [info[x['id']].get(h) for h in head[1:]])
        outputs[variant] = {'csv': str(path), 'fused_top10': [r['paper'] for r in order[:10]], 'first_query_top10': sanity}
        print(f'[{variant}] fused top 10: ' + ', '.join(r['paper'] for r in order[:10]))
        if a.expect:
            exp = [k for k in a.expect.split(',') if k]
            print(f'[{variant}] sanity check: {sum(k in sanity for k in exp)} of {len(exp)} expected papers in '
                  f'{next(iter(Q))} top 10; missing: {[k for k in exp if k not in sanity]}')
        print(f'[{variant}] -> {path}', file=sys.stderr)

    try:
        commit = subprocess.run(['git', '-C', str(Path(__file__).resolve().parent), 'rev-parse', '--short', 'HEAD'],
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ''
    run = {'created': datetime.datetime.now().isoformat(timespec='seconds'), 'paper_lector_commit': commit,
           'question': question, 'queries': Q, 'queries_sha': qsha, 'fuse': fuse,
           'models': {'provider': provider, 'embed': EMBED if provider == 'voyage' else None,
                      'rerank': RERANK if provider == 'voyage' else None, 'tokenizer': TOK_URL},
           'versions': versions(),
           'params': {'window': WIN, 'step': STEP, 'rrf_k': RRF_K, 'windows_per_paper': N_WIN, 'max_overlap': MAX_OVERLAP},
           'corpus': {'papers': len(P), 'windows': len(W), 'ids': [p['id'] for p in P],
                      'files': [{'id': p['id'], 'path': p['path'], 'sha256': p['sha256']} for p in P], 'skipped': skipped,
                      'possible_duplicates': dupes},
           'expect': a.expect, 'usage': dict(usage), 'estimate': estimate, 'outputs': outputs}
    if a.abstracts:
        run['abstracts'] = {'files': [{'path': f, 'sha256': common.sha256_file(f)} for f in a.abstracts.split(',')],
                            'papers': len(A), 'ranked': len(AR),
                            'abstract_only': [x['id'] for x in A if x['source'] == 'abstract_only'],
                            'no_abstract': [x['id'] for x in A if not x['text']],
                            'top10': [k for k, _ in sorted(abs_rows.items(), key=lambda kv: kv[1]['abs_fused_rank'])[:10]]}
    with open(run_name(a.out, a.name), 'x', encoding='utf-8') as f:
        f.write(json.dumps(run, indent=1, ensure_ascii=False))
    print(f'tokens: embed {usage["embed"]:,} ({usage["embed_cached"]:,} texts from cache), rerank {usage["rerank"]:,} '
          f'-> {run_name(a.out, a.name)}', file=sys.stderr)


if __name__ == '__main__':
    main()
