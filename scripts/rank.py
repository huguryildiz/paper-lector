"""Rank a PDF collection against frozen research-question slots and give a reading order with starting pages.

Method:
  1. Whole PDF through pdftotext; every bibliography is cut, from a References heading or, with none, from a
     numbered list of dated, authored entries, up to where the entries stop; appendices and later chapters stay.
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

  Provider "local" (literature.json "rank": {"provider": "local"}, or --provider local) needs no API key: the
  model2vec model potion-science-32M (static token vectors, English, 130 MB, downloaded once; "rank": {"model":
  "retrieval"} or --local-model retrieval picks potion-retrieval-32M) replaces voyage-4-large in step 3, and in step 4
  each paper is scored by the cosine of the same model's vectors for the query and for its abstract plus 3 windows.
  Output: <out>_<name>_rank-local.csv.

  Voyage embeddings are cached in ~/.cache/paper-lector/embeddings.sqlite (key: model, input type, text), so a
  rerun or a run resumed after a crash does not pay for them again; reranking is paid in full on every run. Every
  request, retries included, counts against --budget. Outputs are written at the end, all or none. Table src ties each vector to its PDF's SHA-256 and
  window number and pages (or to the queries hash and query id).

  rank.py --setup                         # once, online: checks pdftotext, downloads the tokenizer
  rank.py --dry                           # counts and token estimate, no API call
  rank.py                                 # writes runs/<date>_<time>_<name>_rank.csv and _rank_run.json, logs questions.jsonl
"""
import argparse, csv, datetime, functools, hashlib, io, json, math, os, re, shutil, sqlite3, subprocess, sys, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

EMBED, RERANK = 'voyage-4-large', 'rerank-3'
WIN, STEP, RRF_K, N_WIN, MAX_OVERLAP, HEAD = 1200, 1000, 60, 3, 0.2, 1000
EMBED_BATCH, RERANK_BATCH, MAX_ITEMS = 100_000, 500_000, 1000     # Voyage: at most 1,000 inputs or documents per call
RERANK_PAIR, RERANK_QUERY = 32_000, 8_000                           # rerank-3: query + one document, query alone
# A rerank request costs query tokens x documents + document tokens, at most 600K for rerank-3; RERANK_BATCH stays below.
PDFTOTEXT_SECONDS = 300
TOK_REV = 'bb931c2635a93efe400c24741363d8ff61d7bb32'
TOK_URL = f'https://huggingface.co/voyageai/voyage-4-large/resolve/{TOK_REV}/tokenizer.json'
TOK_SHA = 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539'
TOK_PATH = Path.home() / f'.cache/paper-lector/voyage-4-large-tokenizer-{TOK_REV[:7]}.json'   # a new revision, a new file
LOCAL_MODELS = {   # model2vec models (static token vectors, English) at a pinned revision; keys are common.LOCAL_MODELS
    'science': ('minishlab/potion-science-32M', '7366079845507de14a4330007cdfa01bb92bca52', 130,
                {'model.safetensors': '5973432fc766d8f0fff07d4138bbb79d67854fe6af120aff2922f26b9b7e2055',
                 'tokenizer.json': 'fdf9372b4c0b0a5b4b841a9955be1834ffc5878734a207f80e349e2956c65e93'}),
    'retrieval': ('minishlab/potion-retrieval-32M', '6fc8051fab2a1e0ee76689cf08c853792ac285e7', 131,
                  {'model.safetensors': '07609e5bd33aad37900b3fd62f4ec96f6daec88ca4d46b9d8b928bfababf6ea0',
                   'tokenizer.json': '7d75cbc54318138807c401b0f0c9721117c628b39de8e8e0edb6cb17e0ee7d18'}),
}


def local_dir(model):
    repo, rev = LOCAL_MODELS[model][:2]
    return Path.home() / f'.cache/paper-lector/{repo.split("/")[1]}/{rev[:7]}'      # a new revision, a new folder
CACHE = Path.home() / '.cache/paper-lector/embeddings.sqlite'
STOP = set('a an the of for and or in on with to via under by at as is are be been was were this that these those it its '
           'from into over than then which when where while what who how does do can not no '
           've ile bir bu şu için da de olan olarak gibi daha en çok her ise veya ya ki ne'.split())
KEY = None
SENT, BUDGET = 0, math.inf                      # tokens sent to Voyage in this run, and --budget
LIGATURES = str.maketrans({'\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl', '\ufb03': 'ffi', '\ufb04': 'ffl',
                           '\ufb05': 'st', '\ufb06': 'st'})       # pdftotext keeps a font's ligature glyphs


def call(ep, body, n):
    """One Voyage request of n tokens (counted with Voyage's tokenizer, as in the estimate). Every attempt, retries
    included, counts n against --budget before it is sent, since a request lost on the way back may still be billed;
    an attempt that would pass the budget is not sent. Errors stop the run with a message."""
    global SENT
    req = common.authorized(urllib.request.Request(f'https://api.voyageai.com/v1/{ep}', json.dumps(body).encode(),
                                                   {'content-type': 'application/json'}), KEY)

    def once():
        global SENT
        if SENT + n > BUDGET:
            sys.exit(f'stopped: the next Voyage request ({n:,} tokens) would bring the tokens sent to {SENT + n:,}, '
                     f'above --budget {BUDGET:,} (retries count too). Nothing written; embeddings already received '
                     f'are cached, so a rerun does not pay for them again')
        SENT += n
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    try:
        return common.retry(once)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f'Voyage refused the key (HTTP {e.code}): VOYAGE_API_KEY is wrong or revoked. Nothing written. '
                     f'Fix the key (environment, project .env or ~/.config/paper-lector/.env), or use --provider local')
        if e.code == 429:
            sys.exit('Voyage kept answering HTTP 429 (rate limit) after the retries; nothing written, embeddings already '
                     'received are cached. Accounts with no payment method get very low limits, too low for a batch of '
                     'this size: add a payment method in the Voyage dashboard (the free tokens still apply), wait and '
                     'run again, or use --provider local')
        try:
            detail = json.load(e).get('detail') or ''
        except (ValueError, AttributeError, OSError):
            detail = ''
        sys.exit(f'Voyage answered HTTP {e.code} on {ep}' + (f': {common.redact(str(detail), KEY)[:300]}' if detail else '')
                 + '. Nothing written; embeddings already received are cached')
    except (common.TRANSIENT + (json.JSONDecodeError,)) as e:
        sys.exit(f'cannot get an answer from api.voyageai.com ({e}). Nothing written; embeddings already received are '
                 f'cached. Check the connection and run again')


def tokens_used(r):
    """total_tokens from a Voyage answer, 0 when it holds none."""
    u = r.get('usage') if isinstance(r, dict) else None
    t = u.get('total_tokens') if isinstance(u, dict) else None
    return t if isinstance(t, int) else 0


def rerank_scores(r, n):
    """index -> relevance score from a rerank response for n documents. A response that misses or repeats a document,
    or gives a score that is not a finite number, stops the run: a rank built on it would be wrong."""
    got, data = {}, r.get('data') if isinstance(r, dict) else None
    for x in data if isinstance(data, list) else []:
        if not isinstance(x, dict):
            got = None
            break
        i, v = x.get('index'), x.get('relevance_score')
        if not isinstance(i, int) or not 0 <= i < n or i in got or isinstance(v, bool) \
                or not isinstance(v, (int, float)) or not math.isfinite(v):
            got = None
            break
        got[i] = float(v)
    if got is None or len(got) != n:
        sys.exit(f'Voyage returned an incomplete or invalid rerank answer (not {n} results with one finite score each); '
                 f'nothing written. Run again')
    return got


def embed(items, input_type, usage, srcs, dim=None):
    """Unit-norm embeddings for (text, tokens) items. Cached vectors are reused; new ones are stored after each
    API batch, so a crashed run resumes without paying again. Stored as float32 whether fresh or cached.
    srcs gives each item's origin, (ref, part, pages): a window is (PDF SHA-256, window number in that PDF, its pages),
    a query is (queries hash, query id, ''). They go to table src, cached items too, so a vector can be traced back to
    a paper; one text met in two PDFs has one vector and two src rows. dim is the size every vector must have (the
    windows' size, for the queries); a vector of another size, or a zero or non-finite one, is never cached."""
    try:
        return _embed(items, input_type, usage, srcs, dim)
    except sqlite3.Error as e:
        sys.exit(f'the embedding cache {CACHE} cannot be read or written ({e}); nothing written. A full disk is the usual '
                 f'cause: free some space and run again. If the file itself is damaged, move it away; it is rebuilt, '
                 f'and its vectors are paid for again')


def usable(v, dim=None):
    """True for an embedding worth keeping: one finite, non-zero vector of at least 2 numbers (of dim numbers when
    given)."""
    return v.ndim == 1 and v.size >= 2 and (dim is None or v.size == dim) and bool(np.isfinite(v).all()) \
        and bool(np.linalg.norm(v))


def _embed(items, input_type, usage, srcs, dim):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE)
    db.execute('create table if not exists emb (key text primary key, vec blob)')
    db.execute('create table if not exists src (key text, kind text, ref text, part text, pages text, tokens integer, '
               'first_seen text, primary key (key, ref, part))')
    keys = [hashlib.sha256(f'{EMBED}\0{input_type}\0{t}'.encode()).hexdigest() for t, _ in items]
    vec = {}
    for k in dict.fromkeys(keys):
        row = db.execute('select vec from emb where key = ?', (k,)).fetchone()
        if row and len(row[0]) % 4 == 0:
            vec[k] = np.frombuffer(row[0], np.float32)
    # Vectors of the run's one size only (the most common among cached ones); any other cached vector, or a zero or
    # non-finite one, is not used and is fetched again, replacing it in the cache.
    sizes = Counter(v.size for v in vec.values() if usable(v))
    dim = dim or (sizes.most_common(1)[0][0] if sizes else None)
    bad = [k for k, v in vec.items() if not usable(v, dim)]
    for k in bad:
        del vec[k]
    if bad:
        print(f'note: {len(bad)} cached embeddings were unusable (wrong size, zero or not finite); fetched again',
              file=sys.stderr)
    cached = len(vec)
    todo = list({k: it for k, it in zip(keys, items) if k not in vec}.items())
    for part in batches(todo, lambda x: x[1][1], EMBED_BATCH, MAX_ITEMS):
        r = call('embeddings', {'input': [it[0] for _, it in part], 'model': EMBED, 'input_type': input_type, 'truncation': False},
                 sum(it[1] for _, it in part))
        r = r if isinstance(r, dict) else {}
        usage['embed'] += tokens_used(r)
        try:
            data = r['data']
            got = {x.get('index', i): np.asarray(x['embedding'], np.float32) for i, x in enumerate(data)}
            if len(data) != len(got):
                got = {}                             # an index given twice: one vector would replace another
        except (KeyError, TypeError, ValueError, AttributeError):
            got = {}
        dim = dim or next((v.size for v in got.values() if usable(v)), None)
        if set(got) != set(range(len(part))) or not all(usable(v, dim) for v in got.values()):
            sys.exit('Voyage returned an incomplete or invalid embedding batch (a missing, zero, non-finite or '
                     'wrong-sized vector); nothing written and nothing of it cached. Run again')
        for i, (k, _) in enumerate(part):
            vec[k] = got[i]
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
    fetch(TOK_URL, TOK_PATH, TOK_SHA, 'the tokenizer', 'rank.py needs it once, also with --dry and local', 'rank.py --setup')
    if common.sha256_file(TOK_PATH) != TOK_SHA:
        sys.exit(f'{TOK_PATH} is not the pinned tokenizer (revision {TOK_REV[:7]}). Delete it and run "rank.py --setup"')
    return Tokenizer.from_file(str(TOK_PATH))


def fetch(url, path, want, what, why, setup):
    """Download url to path once; a partial download or one with the wrong SHA-256 never lands at path."""
    if path.exists():
        return
    part = path.with_suffix('.part')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(part, 'wb') as f:   # 120 s without data: give up
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        part.unlink(missing_ok=True)
        sys.exit(f'cannot download {what} ({e}). {why}: connect to the internet and run "{setup}", or copy {url} to {path}')
    if common.sha256_file(part) != want:
        part.unlink()
        sys.exit(f'{what} downloaded from {url} does not match its pinned SHA-256; not used')
    part.replace(path)


def local_model(model='science'):
    """A model of LOCAL_MODELS at its pinned revision, downloaded once (130 MB) and checked against its SHA-256 on every
    load. Returns texts -> unit-norm vectors: the mean of the texts' static token vectors, as model2vec computes them."""
    from tokenizers import Tokenizer
    repo, rev, mb, files = LOCAL_MODELS[model]
    d, setup = local_dir(model), 'rank.py --setup --provider local' + (f' --local-model {model}' if model != 'science' else '')
    for f, want in files.items():
        fetch(f'https://huggingface.co/{repo}/resolve/{rev}/{f}', d / f, want, f'the local model ({f})',
              f'The local provider needs it once ({mb} MB)', setup)
        if common.sha256_file(d / f) != want:
            sys.exit(f'{d / f} is not the pinned local model ({repo}, revision {rev[:7]}). Delete it and run "{setup}"')
    path = d / 'model.safetensors'
    with open(path, 'rb') as fh:
        n = int.from_bytes(fh.read(8), 'little')
        shape = json.loads(fh.read(n))['embeddings']['shape']
    emb = np.memmap(path, np.float32, 'r', offset=8 + n, shape=tuple(shape))
    tok = Tokenizer.from_file(str(d / 'tokenizer.json'))

    def vecs(texts):
        V = np.array([emb[e.ids].mean(0) if e.ids else np.zeros(shape[1]) for e in
                      tok.encode_batch(list(texts), add_special_tokens=False)], float).reshape(-1, shape[1])
        return V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-12)
    return vecs


def need_pdftotext():
    if not shutil.which('pdftotext'):
        sys.exit('pdftotext not found. Install poppler: "brew install poppler" (macOS), '
                 '"sudo apt install poppler-utils" (Debian/Ubuntu); on Windows use WSL')


def digest(path):
    return common.sha256_file(path)


def find_pdfs(dirs, known, ids=None, allow_empty=False):
    """Paper id -> PDF. Papers in the sources table keep their key; every other PDF is named by its file stem.
    A byte-identical copy of a PDF already found is skipped with a note."""
    out = {k: v['pdf'] for k, v in known.items() if v['pdf'] and v['pdf'].is_file()}
    for k, v in known.items():
        if v['pdf'] and k not in out and (not ids or k in ids):
            print(f'note: sources key {k}: {v["pdf"]} not found; a copy in the PDF folders is ranked under its file '
                  f'name, without the sources DOI', file=sys.stderr)
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
        for p in sorted(Path(d).rglob('*.pdf', case_sensitive=False)):
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
        # An id read back from our own CSV carries the ' that cell() put in front of it: decoded first, since cell()
        # is one to one ("''p" is the id "'p"); an id written by hand without it is taken as it is.
        ids = [i[1:] if i[:1] == "'" and cell(i[1:]) == i and i[1:] in out else i for i in ids]
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
ABSTRACT = r'a ?bstract|özet|öz|zusammenfassung|kurzfassung|r[ée]sum[ée]|resumen|riassunto|resumo|аннотация|реферат'
INTRO = (r'i ?ntroduction|g[iİ]r[iİ][şŞ]|einleitung|einführung|introducci[oó]n|introduzione|introdu[çc][ãa]o'
         r'|введение')
KEYWORDS = r'index terms|key ?words|ccs concepts|anahtar kelimeler|schlüsselwörter|mots[- ]cl[ée]s|palabras clave'
CITES = [r'(?m)^\s*\[\d+\]', r'\(\d{4}\)|, \d{4}\.', r'(?m)^\s*\d{1,3}\.\s+\S.*\b(?:19|20)\d{2}\b',
         r'(?m)(?:^|\.\s)(?:19|20)\d{2}[a-z]?\.(?:\s|$)',     # ACL style, "and C. Manning. 2015. Title"
         r'(?m)^\s*\[[A-Za-z+@][\w+@]*\d{2}[a-z]?\]']           # biblatex alphabetic keys, "[Aco+24]"


Y = r'(?:19\d{2}|20[0-3]\d)'                                  # a publication year; table values like 2048 are not
YEAR = re.compile(rf'\b{Y}\b')
AUTHOR = re.compile(rf'(?<!\w)[A-ZА-ЯÀ-Ý]\.|\b[A-Z][\w\'-]+ [A-Z]{{1,3}}(?:,| \()|\({Y}[a-z]?\)'
                    r'|(?i:\bet al\b|\bdoi\b|arxiv|\bvol\.|\bpp\.|\bproc\.)')   # "A. Author", "Author AB,", "(2019)"
IN_TEXT = re.compile(rf'\([^()\n]{{0,80}}?(?:et al\.?|&|\band\b|,)[^()\n]{{0,80}}?\b{Y}[a-z]?[^()\n]{{0,40}}\)'
                     rf'|\b[A-Z][\w-]+(?: et al\.?)?\s+\({Y}[a-z]?\)(?!\.)')   # "(Liu et al., 2020a)", "Galley et al. (2018)"
FIRST_ENTRY = re.compile(r'(?m)^[ \t]*(?:\[1\]|1\.|1(?=[ \t]+[A-Z]\.))\s')
LETTERED = re.compile(r'(?m)^[ \t]*[A-H]\.?[ \t]*\n(?:[ \t]*\n)*[ \t]*[A-Z][\w-]*(?:[ \t]+[\w-]+){0,7}[ \t]*$'
                      r'|^[ \t]*[A-H](?:\.[ \t]*|[ \t]+)[A-Z][\w-]*(?:[ \t]+[\w-]+){0,7}[ \t]*$')   # "A\n\nProof of Theorem 1"
BIB_BLOCK, BIB_YEARS = 1500, 3        # a bibliography holds a year every few lines; body text, a proof or a table rarely


def numbered_refs(tail):
    """True when tail opens a reference list with no heading: entries numbered 1, 2, 3, ... in order, as "[n]", "n."
    or "n A." (pdftotext dropped the bracket), at least 3 of them, nearly every entry holds a year and most name an
    author (an initial, "et al.") or a venue. Numbered body paragraphs or lists, dated ones too, have no such entries."""
    for pat in (r'(?m)^\s*\[(\d{1,3})\]\s', r'(?m)^\s*(\d{1,3})\.\s', r'(?m)^\s*(\d{1,3})\s+(?=[A-Z]\.)'):
        ms = list(re.finditer(pat, tail))
        n = 0
        while n < len(ms) and int(ms[n].group(1)) == n + 1:
            n += 1
        if n < 3:
            continue
        ends = [m.start() for m in ms[1:n]] + [ms[n].start() if n < len(ms) else len(tail)]
        entries = [tail[m.end():e] for m, e in zip(ms[:n], ends)]
        dated = sum(bool(YEAR.search(x)) for x in entries)
        named = sum(bool(AUTHOR.search(x)) for x in entries)
        if dated >= max(3, 0.8 * n) and named >= 0.6 * n:
            return True
    return False


def masked(text, a, b):
    """text[a:b] with in-text citations blanked out, positions kept."""
    return IN_TEXT.sub(lambda m: ' ' * len(m.group()), text[a:b])


def dense(text, a, stop):
    """True when text[a:a + BIB_BLOCK] (cut at stop) holds a year every BIB_BLOCK / BIB_YEARS characters or more,
    leaving out the years of in-text citations (an appendix of an author-year paper cites as densely as a list)."""
    n = min(BIB_BLOCK, stop - a)
    return n > 0 and len(YEAR.findall(masked(text, a, a + n))) >= BIB_YEARS * n / BIB_BLOCK


def first_entries(text, a, b):
    """Starts of the entries "[1]", "1." or "1 A." between a and b that read like a reference (an author or venue in
    the next 200 characters), not line 1 of an algorithm or a numbered step."""
    return [m.start() for m in FIRST_ENTRY.finditer(text, a, b) if AUTHOR.search(text, m.end(), m.end() + 200)]


def bib_start(text, head):
    """Where the entries under a References heading begin: at its entry "[1]" when one follows more than 300 and
    less than BIB_BLOCK characters on (pdftotext left a column of body text between them), else right at the heading; or, when
    pdftotext put the heading away from the list (two-column pages), where the first dense stretch within 4,500
    characters starts: at its entry "[1]" if one comes before it, else at the first of the dated lines that lead into
    it. None if no such stretch."""
    for a in range(head, min(head + 3 * BIB_BLOCK + 1, len(text)), BIB_BLOCK):
        if dense(text, a, len(text)):
            if a == head:
                first = first_entries(text, head, head + BIB_BLOCK)
                return first[0] if first and first[0] - head > 300 else head
            first = first_entries(text, head, a)
            if first:
                return first[-1]
            s = YEAR.search(text, a).start()
            while s - 400 > head and YEAR.search(text, s - 400, s):
                s -= 400
            return text.rfind('\n', 0, s) + 1
    return None


def walk_back(text, s, floor):
    """Entries pdftotext printed before the list's start (a column that comes out above its References heading): s
    moves back over 600-character stretches that each hold 2 or more years (in-text citations aside), at most 6,000
    characters and never before floor."""
    lim = max(floor, s - 6000)
    while s - 600 >= lim:
        ys = [m.start() for m in YEAR.finditer(masked(text, s - 600, s))]
        if len(ys) < 2:
            break
        s = text.rfind('\n', 0, s - 600 + ys[0]) + 1
    return s


def bib_end(text, start):
    """Where the reference list that starts at start ends: at an appendix heading (the word, or a letter and a short
    title, "A\\n\\nProof of Theorem 1", that thin text follows), or where the entries stop, that is the first stretch
    of BIB_BLOCK characters with fewer than BIB_YEARS years (one such stretch between two dense ones is a gap inside the
    list). The end falls just after that stretch's last dated line (in-text citations aside)."""
    app = re.search(rf'(?m)^\s*(?:[A-Z]\.?\s*)?({APPENDIX})', text[start:], re.I)
    stop = start + app.start() if app else len(text)
    let = next((m.start() for m in LETTERED.finditer(text, start, stop) if not dense(text, m.start(), len(text))), None)
    stop = let if let is not None else stop
    a = start
    while a < stop and (dense(text, a, stop) or (a + BIB_BLOCK < stop and dense(text, a + BIB_BLOCK, stop))):
        a += BIB_BLOCK
    if a >= stop:
        return stop
    b = max(start, a - BIB_BLOCK)                         # the last dense stretch and the first thin one
    last = [b + m.end() for m in YEAR.finditer(masked(text, b, min(a + BIB_BLOCK, stop)))]
    if not last:
        return a
    nl = text.find('\n', last[-1])
    return min(stop, nl + 1 if nl >= 0 else stop)


def clean(text):
    """Cut every bibliography: from a References heading (in any language in BIB) followed by citation entries, or,
    with no heading (APS and Nature styles print none), from an entry "[1]", "1." or "1 A." past the first fifth that
    more dated, authored entries follow. A cut also takes the entries pdftotext printed just above its heading
    (walk_back), ends where the entries stop (bib_end), and a list numbered on after an appendix page ("[56]" after
    "[55]") is cut again; appendices, lettered ones too, and the chapters after a chapter's own bibliography stay.
    Returns (text, cut, shifts): shifts lists (position in the returned text, characters removed there) for mapping
    positions back to the original."""
    cites = lambda at: any(len(re.findall(c, text[at:at + 5000])) >= 3 for c in CITES)
    heads = [bib_start(text, m.start()) for m in
             re.finditer(rf'(?m)^\s*(?:[IVX]+\.\s*|\d+\.?\s*)?({BIB})\s*:?\s*$', text, re.I) if cites(m.start())]
    starts = sorted((s, True) for s in heads if s is not None)         # (start, may take entries printed above it)
    if not starts:
        starts = [(m, False) for m in first_entries(text, int(len(text) * 0.2), len(text))
                  if numbered_refs(text[m:m + 6000])][:1]
    spans = []
    while starts:
        s, headed = starts.pop(0)
        if spans and s < spans[-1][1]:
            continue                                  # a running "Bibliography" header inside a list already cut
        if headed:
            s = walk_back(text, s, spans[-1][1] if spans else 0)
        e = bib_end(text, s)
        if e <= s:
            continue
        spans.append((s, e))
        nums = [int(x) for x in re.findall(r'(?m)^\s*\[(\d{1,3})\]', text[s:e])]
        more = re.compile(rf'(?m)^\s*\[{max(nums) + 1}\]\s').search(text, e) if nums else None
        if more and dense(text, more.start(), len(text)):
            starts = sorted(starts + [(more.start(), False)])
    if not spans:
        return text, False, []
    out, shifts, prev, removed = [], [], 0, 0
    for s, e in spans:
        out.append(text[prev:s])
        removed += e - s
        shifts.append((s - (removed - (e - s)), e - s))
        prev = e
    out.append(text[prev:])
    return ''.join(out), True, shifts


def abstract(text):
    """The abstract and its character span in text, or (None, None): the text after an Abstract heading at the start
    of a line, up to an Introduction heading or an Index Terms / Keywords / CCS Concepts line, 100 to 4,000
    characters."""
    m = re.search(rf'(?m:^)[ \t]*(?:{ABSTRACT})\b\W{{0,3}}(.{{100,4000}}?)'
                  rf'(?=(?m:^)[ \t]*(?:(?:I\.|1\.?)?\s*(?:{INTRO})\b|(?:{KEYWORDS})\b))', text[:15000], re.I | re.S)
    return (m.group(1).strip(), m.span(1)) if m else (None, None)


class ExtractError(Exception):
    pass


def pdf_pages(path):
    """Page texts from pdftotext. A failed or slow extraction raises ExtractError rather than ranking partial text."""
    try:
        r = subprocess.run(['pdftotext', '-enc', 'UTF-8', str(path), '-'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=PDFTOTEXT_SECONDS)
    except subprocess.TimeoutExpired:
        raise ExtractError(f'pdftotext took more than {PDFTOTEXT_SECONDS} s')
    if r.returncode:
        raise ExtractError(f'pdftotext failed (exit {r.returncode}): {r.stderr.strip()[:200]}')
    pages = r.stdout.translate(LIGATURES).split('\f')
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()                      # pdftotext ends every page with a form feed, so the last piece is empty
    return pages


def text_layer_only_repeats(pages):
    """True for a PDF of three or more pages whose text, past the lines every page repeats (a publisher's watermark
    or running header), holds fewer than 3 distinct words (page numbers not counted): a scan with no real text layer."""
    lines = [{l.strip() for l in p.splitlines() if l.strip()} for p in pages]
    if len(lines) < 3:
        return False
    same = set.intersection(*lines)
    rest = {w for ls in lines for l in ls - same for w in re.findall(r'[^\W\d_]\w*', lower(l))}
    return len(rest) < 3


def windows(path, tok):
    pages = pdf_pages(path)
    if text_layer_only_repeats(pages):
        return [], '', False, False, 0
    starts, text = [], ''
    for p in pages:
        starts.append(len(text)); text += re.sub(r'[ \t]+', ' ', p) + '\n'
    body, cut, shifts = clean(text)
    enc = tok.encode(body, add_special_tokens=False)
    orig = lambda c: c + sum(n for at, n in shifts if c >= at)
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
    return s.replace('İ', 'i').translate(LIGATURES).lower()


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
    """A text cell safe to open in a spreadsheet: a leading = + - @, tab, CR or LF (a formula there) gets a ' in front, and so does a
    leading ' (which a spreadsheet hides), so two different texts never give the same cell."""
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r', '\n', "'") else s


def unique_pages(s):
    """A _pages cell without repeated labels (two windows can share a label), first occurrence kept."""
    return '; '.join(dict.fromkeys(s.split('; '))) if s else s


def start_pages(cells, k=3):
    """Up to k page labels to start reading at: labels counted once per query cell, most counted first (then by
    page), a label overlapping one already picked skipped, never widened."""
    def span(p):
        a, _, b = p[3:].partition('-')
        return int(a), int(b or a)
    count = Counter(p for c in cells if c for p in set(c.split('; ')))
    picked = []
    for p in sorted(count, key=lambda p: (-count[p], *span(p))):
        a, b = span(p)
        if not any(a <= y and b >= x for x, y in map(span, picked)):
            picked.append(p)
        if len(picked) == k:
            break
    return '; '.join(picked)


def read_ids(path):
    """Paper ids (and SHA-256 when the CSV has that column) from a CSV with a "paper" column."""
    if not Path(path).is_file():
        sys.exit(f'--ids {path}: file not found')
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


@functools.lru_cache(maxsize=None)
def words(s):
    return ' '.join(re.findall(r'\w+', (s or '').translate(LIGATURES).lower()))


@functools.lru_cache(maxsize=None)
def content_words(s):
    """The words of 4 or more letters in s, stop words left out (for comparing abstracts)."""
    return frozenset(w for w in re.findall(r'[^\W\d_]{4,}', lower(s or '')) if w not in STOP)


@functools.lru_cache(maxsize=None)
def numbers(s):
    """Numbers and roman numerals among the words of s ("Part II", "5G")."""
    return frozenset(w for w in s.split() if re.fullmatch(r'\d+|x{0,3}(?:ix|iv|v?i{0,3})', w))


def alike(a, b, least):
    """True when strings a and b are at least `least` alike letter by letter (difflib ratio). The cheap upper bounds
    go first, so most pairs never reach the full comparison."""
    import difflib
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= least and m.quick_ratio() >= least and m.ratio() >= least


TITLE_STOP = {'a', 'an', 'the', 'of', 'for', 'and', 'or', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at', 'from',
              'over', 'into', 'as', 'its', 'is', 'are', 'using', 'based', 'toward', 'towards'}


def same_title(a, b):
    """Two versions of one paper: normalised titles at least 95% alike letter by letter ("Fidelity-Guarantee" and
    "Fidelity-Guaranteed"); different papers with near titles stay apart (about 87% for those seen so far)."""
    if numbers(a) != numbers(b):
        return False                                      # "Part I" and "Part II": different papers
    return alike(a, b, 0.95)


def versions_of(r, h):
    """Records r and h can be two versions of one paper: the same first author's surname and years at most two apart,
    where both records give them. Two papers that only share a title stay apart."""
    if not r or not h:
        return True                                   # a PDF matched by its title alone: nothing to compare
    # The first author's name words: "Angela Sara Cacciapuoti" and "CACCIAPUOTI, Angela Sara" share them, so the
    # name order a repository uses does not matter; two people share none (initials aside).
    name = lambda x: {w for w in words(x.get('first_author') or (x.get('authors') or [''])[0]).split() if len(w) > 1}
    if name(r) and name(h) and not name(r) & name(h):
        return False
    return not (r.get('year') and h.get('year') and abs(r['year'] - h['year']) > 2)


def retitled(r, h):
    """Records r and h are one paper retitled between preprint and print: the same first author (full name), years
    at most one apart, titles at least 85% alike with the same numbers, and abstracts sharing 80% of their words."""
    if not r or not h:
        return False
    sur = lambda x: words(x.get('first_author') or (x.get('authors') or [''])[0])
    if not sur(r) or sur(r) != sur(h) or not r.get('year') or not h.get('year') or abs(r['year'] - h['year']) > 1:
        return False
    ta, tb = words(r.get('title')), words(h.get('title'))
    aa, bb = content_words(r.get('abstract')), content_words(h.get('abstract'))
    return numbers(ta) == numbers(tb) and bool(aa) and bool(bb) and len(aa & bb) / len(aa | bb) >= 0.8 \
        and alike(ta, tb, 0.85)


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
    """Authors (year). Title. Venue, volume(issue), pages. Only what the record holds; up to six authors, then et al."""
    if not r:
        return ''
    names = r.get('authors') or ([r['first_author']] if r.get('first_author') else [])
    who = ', '.join(names[:6]) + (' et al.' if len(names) > 6 else '')
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


def logged(P, cfg, dirs):
    """(paper id, line) for each OK or HAVE line in a fetch_log.jsonl that names a ranked PDF: the logged file in the
    log's own folder, or a byte-identical copy ranked in its place, with the SHA-256 unchanged. One PDF can have several
    lines (a preprint and its published DOI). A line holds the id and, from newer fetches, the citation fields."""
    by_path = {Path(p['path']).resolve(): p for p in P}
    by_sha = {p['sha256']: p for p in P}
    logs = {f for d in list(dirs) + ([cfg['download_dir']] if cfg else []) if Path(d).is_dir()
            for f in Path(d).rglob('fetch_log.jsonl')}
    out = []
    for f in sorted(logs):
        for n, line in enumerate(open(f, encoding='utf-8'), 1):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                if not isinstance(e, dict):
                    raise ValueError('not an object')
            except ValueError as x:
                sys.exit(f'{f} line {n}: not a JSON record ({x}); repair or delete that line, then run again')
            p = by_path.get((f.parent / e['file']).resolve()) if e.get('file') else None
            p = p or by_sha.get(e.get('sha256'))
            if e.get('status', 'OK') in ('OK', 'HAVE') and p and rid(e.get('id')) and e.get('sha256', p['sha256']) == p['sha256']:
                out.append((p['id'], e))
    return out


def logged_rec(e):
    """A fetch_log line as a search-like record, for link() and citation()."""
    kind, v = rid(e['id'])
    return {k: e[k] for k in ('doi', 'title', 'year', 'venue', 'authors', 'first_author', 'biblio') if e.get(k)} | {kind: v}


def abstract_corpus(paths, P, W, cfg, dirs):
    """Papers for the abstract order: every PDF paper (its search record's abstract, else the abstract read from the
    PDF) and every search record with no PDF (abstract_only). A record belongs to a PDF through the sources table's
    DOI, an OK line in fetch_log.jsonl, or its title on the PDF's first page."""
    recs, seen = [], {}                                  # seen: normalised id -> index in recs
    for path in paths:
        for n, line in enumerate(open(path, encoding='utf-8'), 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                sys.exit(f'{path} line {n}: not a JSON record ({e}); nothing ranked')
            if not isinstance(r, dict):
                sys.exit(f'{path} line {n}: not a JSON record (an object with a doi, arxiv or openalex id); nothing ranked')
            ids = list(dict.fromkeys(i for i in (rid(r.get('doi')), rid(r.get('arxiv')), rid(r.get('openalex'))) if i))
            if not ids:
                print(f'note: {path} line {n}: no doi, arxiv or openalex id ({r.get("title")}); left out', file=sys.stderr)
                continue
            k = next((seen[i] for i in ids if i in seen), None)
            if k is None:
                k = len(recs); recs.append((dict(r), ids))
            else:                                         # the same paper again: the first record's fields win, the
                held, held_ids = recs[k]                  # later one fills the empty ones (an abstract, a DOI)
                held.update({f: v for f, v in r.items() if v not in (None, '', []) and held.get(f) in (None, '', [])})
                held_ids[:] = list(dict.fromkeys([i for i in (rid(held.get('doi')), rid(held.get('arxiv')),
                                                              rid(held.get('openalex'))) if i] + held_ids + ids))
            for i in ids:
                seen.setdefault(i, k)
    sel = {p['id'] for p in P}
    owner = {}                                            # normalised id -> PDF paper id (only papers in this run)
    for key, v in common.sources(cfg).items():
        if key in sel and v['doi'] and rid(v['doi']):
            owner[rid(v['doi'])] = key
    for pid, e in logged(P, cfg, dirs):
        owner[rid(e['id'])] = pid                         # the logged file, in the log's own folder, unchanged
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
        pids = list(dict.fromkeys(owner[i] for i in ids if i in owner))   # by the record's DOI, then arXiv, then OpenAlex
        if len(pids) > 1:
            print(f'note: {r.get("doi") or r.get("openalex")} names {" and ".join(pids)} (two versions); its abstract '
                  f'goes to {pids[0]}, the one its {"DOI" if rid(r.get("doi")) in owner else "first id"} names', file=sys.stderr)
        pid = pids[0] if pids else None
        if pid is None:
            left.append(r); continue
        if pid not in taken:
            taken.add(pid)
            A[pid].update(title=r.get('title') or '', rec=r)
            if r.get('abstract'):
                A[pid].update(text=r['abstract'], **{'from': 'search'})
        # else: a second record with the same id as a paper already matched
    same = [(words(A[k]['title']), k) for k in sorted(taken) if A[k]['title']]   # (title word for word, paper) held
    for r in left:
        t = words(r.get('title'))
        twin = next((k for tt, k in same if len(t.split()) >= 4 and ((same_title(t, tt) and versions_of(r, A[k]['rec']))
                                                                     or retitled(r, A[k]['rec']))), None)
        if twin is not None:
            print(f'note: {r.get("doi") or r.get("openalex")} has the title of {twin} (another version); '
                  f'counted once', file=sys.stderr)
            held = A[twin]
            if (r.get('cited_by') or 0) > ((held['rec'] or {}).get('cited_by') or 0):   # citations of the most cited version
                held['rec'] = dict(held['rec'] or {}, **{k: r.get(k) for k in ('cited_by', 'cited_pct', 'cited_at')})
            continue
        pid = by_title(t)
        if pid is not None and pid not in taken:
            taken.add(pid)
            A[pid].update(title=r.get('title') or '', rec=r)
            if r.get('abstract'):
                A[pid].update(text=r['abstract'], **{'from': 'search'})
            same.append((t, pid))
            continue
        aid = short_id(r, A)
        if len(t.split()) >= 4:
            same.append((t, aid))
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
    local runs keep their variant in the file name."""
    return f'{out}_{name}_rank.csv' if variant == 'hybrid' else f'{out}_{name}_rank-{variant}.csv'


def run_name(out, name, ext='json'):
    """<out>_<name>_rank_run.json, the run record (and with ext='lock' the lock beside it)."""
    return f'{out}_{name}_rank_run.{ext}'


def inputs(a, cfg, dirs):
    """SHA-256 of every input file besides the PDFs that can change the CSV: the queries file, the config, the sources
    table and each fetch_log.jsonl (they tie search records to PDFs and give the links)."""
    f = lambda p: {'path': rel(p, cfg), 'sha256': common.sha256_file(p)} if p and Path(p).is_file() else None
    logs = sorted({x for d in list(dirs) + ([cfg['download_dir']] if cfg else []) if Path(d).is_dir()
                   for x in Path(d).rglob('fetch_log.jsonl')})
    return {'queries_file': f(a.queries or (cfg and cfg['queries'])), 'config': f(cfg and cfg['path']),
            'sources': f(cfg and cfg['sources']), 'fetch_logs': [f(x) for x in logs]}


def publish(files):
    """Write the run's files under their final names, all or none: each goes through common.write_new (no partial
    file under its name), and a failure removes the ones this run already wrote, so a full disk leaves no CSV
    without its run record."""
    done = []
    try:
        for path, data in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not common.write_new(path, data):
                raise FileExistsError(f'{path} appeared during the run')
            done.append(path)
    except BaseException as e:                       # a full disk, or Ctrl-C half-way: keep none
        for path in done:
            path.unlink(missing_ok=True)
        if not isinstance(e, OSError):
            raise
        sys.exit(f'cannot write the outputs ({e}); nothing of this run was kept. Free some space and run again'
                 + ('; embeddings already received are cached' if BUDGET != math.inf else ''))
    return done


def stamp():
    return datetime.datetime.now().strftime('%Y-%m-%d_%H%M')


def versions():
    """Versions that change windows or scores, for the run record."""
    import platform, tokenizers
    try:
        pt = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True).stderr.split('\n')[0]
    except OSError:
        pt = ''
    return {'os': platform.platform(), 'python': platform.python_version(), 'numpy': np.__version__, 'tokenizers': tokenizers.__version__,
            'pdftotext': pt, 'tokenizer_revision': TOK_REV}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', help=f'path to {common.CONFIG_NAME} (default: searched upward from the current folder)')
    ap.add_argument('--queries', help='queries file (default: "queries" in the config)')
    ap.add_argument('--dirs', help='comma-separated PDF folders (default: "pdf_dirs" in the config)')
    ap.add_argument('--ids', help='CSV with a "paper" column (and optionally "sha256"): rank exactly these papers (frozen corpus)')
    ap.add_argument('--provider', choices=common.PROVIDERS, help='voyage or local (no API key); default: "rank" in the config, else voyage')
    ap.add_argument('--local-model', choices=common.LOCAL_MODELS, help='science or retrieval; default: "model" in the '
                    'config\'s "rank", else science')
    ap.add_argument('--variants', default='hybrid', help='hybrid, dense or hybrid,dense (dense is an ablation); voyage only')
    ap.add_argument('--abstracts', help='comma-separated search JSONL files: also rank every paper on its abstract, '
                    'including results with no PDF (abs_fused_rank, source abstract_only)')
    ap.add_argument('--expect', default='', help='paper ids expected in the first query\'s top 10, fixed before the run')
    ap.add_argument('--budget', type=int, default=15_000_000, help='stop before any API call if the token estimate is higher')
    ap.add_argument('--dry', action='store_true', help='build windows, print counts and the token estimate; no API call')
    ap.add_argument('--out', help='output path prefix (default: runs/<date>_<time> next to the config, for example '
                    'runs/2026-10-17_2315)')
    ap.add_argument('--setup', action='store_true', help='check pdftotext and download the tokenizer once (with --provider local also the local model), then exit')
    a = ap.parse_args(argv)
    a.argv = argv
    need_pdftotext()
    if a.setup:
        tokenizer()
        if a.provider == 'local':
            local_model(a.local_model or 'science')
        print(f'ready: pdftotext {shutil.which("pdftotext")}, tokenizer {TOK_PATH}'
              + (f', local model {local_dir(a.local_model or "science")}' if a.provider == 'local' else ''))
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
        for n, l in enumerate(open(f, encoding='utf-8') if f.is_file() else [], 1):
            if l.strip():
                try:
                    e = json.loads(l)
                    if not isinstance(e, dict):
                        raise ValueError('not an object')
                except ValueError:
                    sys.exit(f'{f} line {n} is not a JSON record (cut off by a crash?). Repair or delete that line, '
                             f'then run again')
                if not isinstance(e.get('queries', ''), str):
                    sys.exit(f'{f} line {n}: "queries" is not a file path; repair or delete that line, then run again')
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
    try:
        prev_sha = json.loads(prev.read_text(encoding='utf-8')).get('queries_sha') if prev.is_file() else qsha
    except (ValueError, AttributeError):
        sys.exit(f'{prev} is not a complete run record (an older paper-lector cut off by a crash?); rank into a new --out')
    if prev_sha != qsha:
        sys.exit(f'{prev} was made with a different question, queries or fuse list. A frozen queries file is not edited: '
                 f'write a new queries file and rank it with a new --out')
    provider = a.provider or (cfg and cfg['provider']) or 'voyage'
    variants = a.variants.split(',')
    if any(v not in ('hybrid', 'dense') for v in variants):
        sys.exit('--variants takes hybrid and/or dense')
    if a.local_model and provider != 'local':
        sys.exit('--local-model applies to the local provider only')
    a.local_model = a.local_model or (cfg and cfg['local_model']) or 'science'
    if provider == 'local':
        if variants != ['hybrid']:
            sys.exit('--variants applies to the voyage provider only')
        variants = ['local']
    dirs = [Path(d) for d in a.dirs.split(',')] if a.dirs else list(cfg['pdf_dirs'])
    if not a.dirs and cfg['download_dir'].is_dir() and not any(cfg['download_dir'].resolve().is_relative_to(Path(d).resolve()) for d in dirs):
        dirs.append(cfg['download_dir'])         # fetch_pdf.py saves there; not ranking it would drop papers unseen
        print(f'note: download_dir {cfg["download_dir"]} is outside pdf_dirs; ranked too', file=sys.stderr)
    ids, want_sha = read_ids(a.ids) if a.ids else (None, {})
    gone = [f for f in (a.abstracts.split(',') if a.abstracts else []) if not Path(f).is_file()]
    if gone:
        sys.exit(f'--abstracts: file not found: {", ".join(gone)}')
    outs = [Path(run_name(a.out, a.name))] + [Path(csv_name(a.out, a.name, v)) for v in variants]
    lock = Path(run_name(a.out, a.name, 'lock'))
    if not a.dry:
        if any(p.exists() for p in outs):
            sys.exit(f'{", ".join(str(p) for p in outs if p.exists())} already exists. Rank into a new --out '
                     f'(for example with today\'s date) and compare the two runs')
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            open(lock, 'x').close()
        except FileExistsError:
            sys.exit(f'{lock} exists: another run into this --out is going on, or one stopped half-way. '
                     f'Use a new --out, or delete the lock and the partial outputs if no run is going on')
        except OSError as e:
            sys.exit(f'cannot create {lock} ({e}); nothing ranked. Check that the folder can be written and has space')
    try:
        done = rank(a, cfg, question, Q, fuse, qsha, provider, variants, dirs, ids, want_sha)
        if not a.dry:
            line = json.dumps({'created': datetime.datetime.now().isoformat(timespec='seconds'), 'question': question,
                               'name': a.name, 'queries': os.path.relpath(qfile, log.parent), 'queries_sha': qsha, 'fuse': fuse,
                               'provider': provider, 'out': rel(a.out, cfg), 'abstracts': a.abstracts or ''}, ensure_ascii=False)
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                common.append_line(log, line)         # all of the line or none of it
            except OSError as e:
                for path in done:
                    path.unlink(missing_ok=True)
                sys.exit(f'cannot add the run to {log} ({e}); its outputs were removed again, so no run stands '
                         f'unlogged. Free some space and run again (embeddings already received are cached)')
    finally:
        if not a.dry:
            lock.unlink(missing_ok=True)


def rank(a, cfg, question, Q, fuse, qsha, provider, variants, dirs, ids, want_sha):
    global KEY, SENT, BUDGET

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
        x['doc'] = 'Abstract: ' + x['text']           # no title: a PDF-only paper has none to add
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
          + (f'estimated {estimate:,} tokens' if provider == 'voyage' else 'provider local, no API call'), file=sys.stderr)
    if provider == 'voyage':                 # stop before any paid call rather than on the API's refusal half-way
        qmax = max((ntok(q['text']) for q in Q.values()), default=0)
        if qmax > RERANK_QUERY:
            sys.exit(f'no API call made: rerank-3 takes a query of at most {RERANK_QUERY:,} tokens; the longest query '
                     f'has {qmax:,}. Shorten its "text" in a new queries file')
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
            print(x['id'], 'skipped: ' + ' '.join(x['reason'].split()), sep='\t')
        for x, y in dupes:
            print(x, f'possible duplicate of {y}', sep='\t')
        return
    usage = Counter()
    if provider == 'voyage':
        if estimate > a.budget:
            sys.exit(f'estimate {estimate:,} tokens is above --budget {a.budget:,}; raise --budget to run')
        SENT, BUDGET = 0, a.budget
        KEY = common.api_key('VOYAGE_API_KEY', cfg)
        if W:
            E = embed([(w['text'], w['n']) for w in W], 'document', usage,
                      [(P[w['paper']]['sha256'], j - P[w['paper']]['wins'][0], w['pages']) for j, w in enumerate(W)])
            QE = embed([(q['text'], ntok(q['text'])) for q in Q.values()], 'query', usage, [(qsha, i, '') for i in Q],
                       E.shape[1])                   # the queries' vectors must have the windows' size
    else:
        vecs = local_model(a.local_model)
        E, QE = vecs(w['text'] for w in W), vecs(q['text'] for q in Q.values())

    abs_rows = {}
    if AR:
        for qid, q in Q.items():
            col = f'{qid}_{q["label"]}'
            if provider == 'local':
                sc = dict(enumerate(map(float, vecs(x['doc'] for x in AR) @ vecs([q['text']])[0])))
            else:
                sc, qn = {}, ntok(q['text'])
                items = [{'i': i, 'n': ntok(x['doc']) + qn} for i, x in enumerate(AR)]
                for part in batches(items, lambda k: k['n'], RERANK_BATCH, MAX_ITEMS):
                    r = call('rerank', {'query': q['text'], 'documents': [AR[k['i']]['doc'] for k in part],
                                        'model': RERANK, 'truncation': False}, sum(k['n'] for k in part))
                    usage['rerank'] += tokens_used(r)
                    for i, v in rerank_scores(r, len(part)).items():
                        sc[part[i]['i']] = v
            for i, x in enumerate(AR):
                row = abs_rows.setdefault(x['id'], {})
                row[f'{col}_abs_rank'] = 1 + sum(1 for v in sc.values() if v > sc[i])
                row[f'{col}_abs_score'] = round(sc[i], 4)
        for row in abs_rows.values():
            row['_afs'] = sum(1 / (RRF_K + row[f'{qid}_{Q[qid]["label"]}_abs_rank']) for qid in fuse)
        for row in abs_rows.values():
            row['abs_fused_rank'] = 1 + sum(1 for o in abs_rows.values() if o['_afs'] > row['_afs'])
            row['abs_fused_score'] = round(row['_afs'], 6)

    outputs, files = {}, []                          # files: (path, bytes), published together at the end
    for variant in variants:
        rows = {p['id']: {'paper': p['id']} for p in P}
        sanity = None
        for qi, (qid, q) in enumerate(Q.items() if P else []):      # no PDFs: abstract order only
            col = f'{qid}_{q["label"]}'
            cos = E @ QE[qi]
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
            if variant == 'local':
                score = {k['pi']: float(v) for k, v in zip(pkgs, vecs(k['text'] for k in pkgs) @ QE[qi])}
            for part in (batches(pkgs, lambda k: k['n'] + qn, RERANK_BATCH, MAX_ITEMS) if variant != 'local' else []):
                r = call('rerank', {'query': q['text'], 'documents': [k['text'] for k in part], 'model': RERANK, 'truncation': False},
                         sum(k['n'] + qn for k in part))
                usage['rerank'] += tokens_used(r)
                for i, v in rerank_scores(r, len(part)).items():
                    score[part[i]['pi']] = v
            for k in pkgs:
                row = rows[P[k['pi']]['id']]
                row[f'{col}_rank'] = 1 + sum(1 for v in score.values() if v > score[k['pi']])
                row[f'{col}_score'] = round(score[k['pi']], 4)
                row[f'{col}_pages'] = unique_pages(k['pages'])
            if sanity is None:
                sanity = [P[i]['id'] for i in sorted(score, key=lambda i: (-score[i], P[i]['id']))[:10]]
        cols = {qid: f'{qid}_{q["label"]}' for qid, q in Q.items()}
        for r in rows.values():
            r['_fs'] = sum(1 / (RRF_K + r[f'{cols[q]}_rank']) for q in fuse)
        for r in rows.values():
            r['fused_rank'] = 1 + sum(1 for o in rows.values() if o['_fs'] > r['_fs'])
            r['fused_score'] = round(r['_fs'], 6)
            r['start_pages'] = start_pages(r[f'{cols[q]}_pages'] for q in fuse)
        first = cols[next(iter(Q))]
        order = sorted(rows.values(), key=lambda r: (-r['_fs'], r[f'{first}_rank'], r['paper']))
        meta = {p['id']: p for p in P}
        head = ['paper', 'link', 'citation', 'fused_rank', 'fused_score', 'cited_by', 'cited_pct', 'cited_at'] + [f'{c}_{s}' for c in cols.values() for s in ('rank', 'score')] \
            + [f'{c}_pages' for c in cols.values()] + ['tokens', 'bib_cut', 'abstract_found', 'source']
        if a.abstracts:
            head += ['abs_fused_rank', 'abs_fused_score'] + [f'{c}_abs_{s}' for c in cols.values() for s in ('rank', 'score')] \
                + ['abstract_from']
        lead = ['fused_rank'] + ['abs_fused_rank'] * bool(a.abstracts) + ['citation', 'link', 'cited_by', 'cited_pct', 'start_pages']
        head = lead + [h for h in head if h not in lead]          # reading columns first, the rest in their old order
        val = lambda h, v: cell(v) if isinstance(v, str) else v
        known = common.sources(cfg)
        info = {x['id']: dict(abs_rows.get(x['id'], {}), abstract_from=x['from'], source=x['source'],
                              link=link(x['rec'], (known.get(x['id']) or {}).get('doi')), citation=citation(x['rec']),
                              **{k: (x['rec'] or {}).get(k) for k in ('cited_by', 'cited_pct', 'cited_at')}) for x in A}
        fetched = {}                                       # a PDF's fetch_log line, the one with citation fields first
        for pid, e in logged(P, cfg, dirs):
            if pid not in fetched or (e.get('title') and not fetched[pid].get('title')):
                fetched[pid] = logged_rec(e)
        for pid in meta:
            info.setdefault(pid, {'link': link(None, (known.get(pid) or {}).get('doi'))})
            if pid in fetched:                             # no search record or sources DOI: the fetch log's
                info[pid]['link'] = info[pid].get('link') or link(fetched[pid])
                info[pid]['citation'] = info[pid].get('citation') or citation(fetched[pid])
        extra = sorted((x for x in A if x['source'] == 'abstract_only'),
                       key=lambda x: (info[x['id']].get('abs_fused_rank', math.inf), x['id']))
        path = Path(csv_name(a.out, a.name, variant))
        f = io.StringIO(newline='')
        w = csv.writer(f); w.writerow(head)
        for r in order:
            m = dict(meta[r['paper']], source='full_text', **{k: v for k, v in info.get(r['paper'], {}).items() if k != 'source'})
            w.writerow([val(h, r.get(h, m.get(h))) for h in head])
        for x in extra:
            w.writerow([val(h, dict(info[x['id']], paper=x['id']).get(h)) for h in head])
        files.append((path, f.getvalue().encode('utf-8')))
        outputs[variant] = {'csv': str(path), 'fused_top10': [r['paper'] for r in order[:10]], 'first_query_top10': sanity}

    try:     # "-dirty" when the scripts were changed after that commit, so a record never names code it did not run
        commit = subprocess.run(['git', '-C', str(Path(__file__).resolve().parent), 'describe', '--always', '--dirty',
                                 '--abbrev=7'], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ''
    run = {'created': datetime.datetime.now().isoformat(timespec='seconds'), 'paper_lector_version': common.VERSION,
           'paper_lector_commit': commit, 'argv': sys.argv[1:] if a.argv is None else a.argv, 'cwd': rel(Path.cwd(), cfg),
           'inputs': inputs(a, cfg, dirs),
           'question': question, 'queries': Q, 'queries_sha': qsha, 'fuse': fuse,
           'models': {'provider': provider, 'embed': EMBED if provider == 'voyage' else '{}@{}'.format(*LOCAL_MODELS[a.local_model][:2]),
                      'rerank': RERANK if provider == 'voyage' else None, 'tokenizer': TOK_URL},
           'versions': versions(),
           'params': {'window': WIN, 'step': STEP, 'rrf_k': RRF_K, 'windows_per_paper': N_WIN, 'max_overlap': MAX_OVERLAP},
           'corpus': {'papers': len(P), 'windows': len(W), 'ids': [p['id'] for p in P],
                      'files': [{'id': p['id'], 'path': rel(p['path'], cfg), 'sha256': p['sha256']} for p in P],
                      'skipped': [dict(x, path=rel(x['path'], cfg)) for x in skipped],
                      'possible_duplicates': dupes},
           'expect': a.expect, 'usage': dict(usage), 'estimate': estimate, 'outputs': outputs}
    if a.abstracts:
        run['abstracts'] = {'files': [{'path': rel(f, cfg), 'sha256': common.sha256_file(f)} for f in a.abstracts.split(',')],
                            'papers': len(A), 'ranked': len(AR),
                            'abstract_only': [x['id'] for x in A if x['source'] == 'abstract_only'],
                            'no_abstract': [x['id'] for x in A if not x['text']],
                            'top10': [k for k, _ in sorted(abs_rows.items(), key=lambda kv: kv[1]['abs_fused_rank'])[:10]]}
    files.append((Path(run_name(a.out, a.name)), json.dumps(run, indent=1, ensure_ascii=False).encode('utf-8')))
    done = publish(files)
    for v in variants:                               # only once the files are there, so no order is reported unwritten
        print(f'[{v}] fused top 10: ' + ', '.join(outputs[v]['fused_top10']))
        sanity = outputs[v]['first_query_top10']
        if a.expect and sanity is None:
            print(f'[{v}] sanity check skipped: no paper ranked on full text')
        elif a.expect:
            exp = [k for k in a.expect.split(',') if k]
            print(f'[{v}] sanity check: {sum(k in sanity for k in exp)} of {len(exp)} expected papers in '
                  f'{next(iter(Q))} top 10; missing: {[k for k in exp if k not in sanity]}')
        print(f'[{v}] -> {outputs[v]["csv"]}', file=sys.stderr)
    print(f'tokens: embed {usage["embed"]:,} ({usage["embed_cached"]:,} texts from cache), rerank {usage["rerank"]:,} '
          f'-> {run_name(a.out, a.name)}', file=sys.stderr)
    return done


if __name__ == '__main__':
    main()
