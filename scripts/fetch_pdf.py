"""Download open-access PDFs for DOIs or arXiv ids into the project's download_dir (literature.json).

Order tried: arXiv, then every OpenAlex location that lists a pdf_url.
A file is kept only if it starts with %PDF. Publisher pages that answer 403
are reported as MANUAL with their landing URL: ask a person to download them.
When no URL could be reached at all (network down, DNS, timeouts), the paper is an ERROR to retry, not MANUAL.
Existing files are never overwritten. A DOI already in the sources table counts as held when its PDF is there, and a
download that is byte-identical to a PDF already in the folders is not saved (fetch_log.jsonl gets a HAVE line tying
the id to that PDF). Only http(s) URLs on public addresses are fetched (every
redirect is checked too), at most 100 MB and 5 minutes per file. Each saved PDF gets a line in fetch_log.jsonl in the
download folder (status OK: id, URL, file, SHA-256 and, from OpenAlex, title, authors, year, venue and volume/pages
for the citation), and so does each MANUAL paper (id, title, landing URL).
Exit status 1 if any paper was not obtained or skipped.
File names include publication metadata, an observed arXiv revision or unknown marker, and identifier/content hashes.
Publication metadata and PDF version observations are recorded separately; neither a DOI nor a URL verifies an edition.

  python fetch_pdf.py 10.1109/JSAC.2024.1234567 2601.11698
  python fetch_pdf.py --from $SP/x17.jsonl
"""
import argparse, datetime, hashlib, http.client, ipaddress, json, os, re, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

KEY = None

UA = {'User-Agent': 'Mozilla/5.0 (research; literature fetch)'}
MAX_BYTES, MAX_SECONDS = 100 * 2**20, 300
OFFLINE_STOP = 3                                 # papers in a row with no server reached: stop, the network is down


def openalex(ident):
    """The OpenAlex work for a DOI, arXiv id or OpenAlex id; None if OpenAlex does not have it."""
    kind, v = common.norm_id(ident)
    path = 'works/' + (v if kind == 'openalex' else 'doi:' + urllib.parse.quote(common.doi_of(ident)))
    try:
        return common.openalex_json(f'https://api.openalex.org/{path}', KEY, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def name_for(w, ident, provenance=None):
    surname = re.sub(r'\W', '', ((w.get('authorships') or [{}])[0].get('author', {}).get('display_name') or 'Anon').split()[-1])
    stop = {'a', 'an', 'the', 'of', 'for', 'and', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at'}
    words = [x for x in re.findall(r'[A-Za-z0-9]+', w.get('display_name') or '') if x.lower() not in stop][:5]
    tag = hashlib.sha1(((w.get('doi') or '').removeprefix('https://doi.org/') or common.doi_of(ident) or ident).lower()
                       .encode()).hexdigest()[:6]
    version = ''
    if provenance is not None:
        version = ('arxiv-' + provenance['pdf_arxiv_id'] if provenance['pdf_version'].startswith('arxiv_v')
                   else 'version-unknown')
        version = '_' + re.sub(r'[^A-Za-z0-9.-]', '-', version)
    return f"{surname}{w.get('publication_year') or ''}_{''.join(x[:1].upper() + x[1:] for x in words)}{version}_{tag}.pdf"


# arXiv landing pages: arxiv.org and export.arxiv.org (abs or pdf), arxiv-vanity.com/papers
ARXIV_LANDING = re.compile(r'(?i)^https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/([^?#]+?)(?:\.pdf)?/?(?:[?#].*)?$'
                           r'|^https?://(?:www\.)?arxiv-vanity\.com/papers/([^/?#]+)/?(?:[?#].*)?$')


def candidates(ident, w):
    urls = []
    kind, v = common._norm_id(ident)  # preserve explicitly requested arXiv revisions for the download
    arx = v if kind == 'arxiv' else None
    for l in (w or {}).get('locations') or []:
        m = ARXIV_LANDING.match(l.get('landing_page_url') or '')
        if m:
            arx = arx or m.group(1) or m.group(2)
    if arx:
        urls.append(f'https://arxiv.org/pdf/{arx}')
    for l in [(w or {}).get('best_oa_location') or {}] + ((w or {}).get('locations') or []):
        if l.get('pdf_url') and l['pdf_url'] not in urls:
            urls.append(l['pdf_url'])
    return urls


ARXIV_ID = r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})'
ARXIV_STAMP = re.compile(r'^\s*arXiv:(' + ARXIV_ID + r'v\d+)\s+\[[^\]\n]+\]\s*'
                         r'(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s*$', re.MULTILINE)


def pdf_provenance(data, ident, w=None, url=None):
    """Describe the downloaded bytes separately from OpenAlex's publication record.

    A first-page arXiv stamp is limited identity evidence. URL/metadata alone never
    establishes a PDF revision or the version of record. Extraction failure is unknown.
    """
    final_url = getattr(data, 'final_url', url)
    rec = {'requested_id': ident, 'publication': common.bib(w) if w else {},
           'source_url': url, 'resolved_url': final_url, 'pdf_version': 'unknown',
           'identity_status': 'unknown', 'version_basis': 'no_recognized_first_page_stamp'}
    locations = [(w or {}).get('best_oa_location') or {}] + ((w or {}).get('locations') or [])
    for loc in locations:
        m = ARXIV_LANDING.match(loc.get('landing_page_url') or '')
        arx_url = f'https://arxiv.org/pdf/{m.group(1) or m.group(2)}' if m else None
        if url and url in (loc.get('pdf_url'), arx_url):
            rec['location_version'] = loc.get('version') or 'unknown'
            rec['publication_relation'] = 'openalex_location_link; not independently verified'
            break
    try:
        result = subprocess.run(['pdftotext', '-f', '1', '-l', '1', '-layout', '-', '-'],
                                input=data, capture_output=True, timeout=15)
        if result.returncode:
            rec['version_basis'] = 'text_extraction_failed'
            return rec
        stamps = set(ARXIV_STAMP.findall(result.stdout.decode('utf-8', errors='replace')))
    except (OSError, subprocess.TimeoutExpired):
        rec['version_basis'] = 'text_extraction_unavailable'
        return rec
    if len(stamps) != 1:
        return rec
    arxiv, date = next(iter(stamps))
    rec.update(pdf_arxiv_id=arxiv, pdf_date=date, version_basis='pdf_first_page_arxiv_stamp')
    # A redirect, requested revision or source URL naming another revision/id is a conflict.
    expected = []
    for address in (url, final_url):
        m = ARXIV_LANDING.match(address or '')
        if m:
            expected.append(m.group(1) or m.group(2))
    kind, value = common._norm_id(ident)
    if kind == 'arxiv':
        expected.append(value)
    if any(common.norm_id(x) != common.norm_id(arxiv) or
           (re.search(r'v\d+$', x) and x != arxiv) for x in expected):
        rec['identity_status'] = 'conflicting_arxiv_identifiers'
        return rec
    rec['pdf_version'] = 'arxiv_' + re.search(r'v\d+$', arxiv).group()
    rec['identity_status'] = 'arxiv_header_matches_source' if expected else 'arxiv_header_only'
    return rec


def version_note(rec):
    return (f'version={rec["pdf_version"]}, identity={rec["identity_status"]}; '
            'publication metadata does not verify the downloaded edition')


class Download(bytes):
    """Bytes with the final response URL, preserving the fetch() bytes interface."""
    def __new__(cls, data, final_url):
        obj = super().__new__(cls, data)
        obj.final_url = final_url
        return obj


NAT64 = ipaddress.ip_network('64:ff9b::/96')


def check_url(url):
    """Refuse anything but http(s) to a public address, so a listed or redirected URL cannot reach local files,
    this machine or the local network."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise ValueError(f'not an http(s) URL: {url}')
    for *_, addr in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == 'https' else 80)):
        ip = ipaddress.ip_address(addr[0].split('%')[0])
        if ip.version == 6 and (ip in NAT64 or int(ip) >> 32 == 0):   # 64:ff9b::a.b.c.d and ::a.b.c.d reach a.b.c.d
            ip = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
        if not ip.is_global:
            raise ValueError(f'{u.hostname} is not a public address ({addr[0]})')


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(CheckedRedirect)


def fetch(url):
    """The file at url if it is a PDF, else None; at most MAX_BYTES, and MAX_SECONDS over all tries together.
    A body shorter than its Content-Length is a cut-off transfer and is retried, never saved."""
    check_url(url)
    end = time.monotonic() + MAX_SECONDS
    def once():
        if time.monotonic() > end:
            raise ValueError(f'gave up after {MAX_SECONDS} s')
        data = bytearray()
        with OPENER.open(urllib.request.Request(url, headers=UA), timeout=60) as r:
            length = int(r.headers.get('Content-Length') or 0)
            if length > MAX_BYTES:
                raise ValueError(f'larger than {MAX_BYTES // 2**20} MB')
            while chunk := r.read(1 << 20):
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError(f'larger than {MAX_BYTES // 2**20} MB')
                if time.monotonic() > end:
                    raise ValueError(f'download took more than {MAX_SECONDS} s')
            if time.monotonic() > end:                 # a last read that stalled before the end of the file
                raise ValueError(f'download took more than {MAX_SECONDS} s')
        if length and len(data) < length:
            raise http.client.IncompleteRead(bytes(data), length - len(data))
        return Download(data, r.geturl() if hasattr(r, 'geturl') else url)
    data = common.retry(once, tries=3, wait=5)
    return data if data[:4] == b'%PDF' else None


def is_pdf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'%PDF'
    except OSError:
        return False


def save(out, data):
    """Write data to out without ever replacing a file there and without leaving a half-written PDF under that name
    (common.write_new; also on drives with no hard links). False if out already exists."""
    return common.write_new(out, data)


def log_line(dest, rec):
    """Append one record to fetch_log.jsonl in the download folder: OK for a saved PDF, HAVE for a download identical
    to a PDF already held (file: that PDF, relative to the folder), MANUAL for one to get by hand. A write that fails
    half-way (a full disk) is cut back, so the log never ends in a broken line."""
    rec['fetched'] = datetime.datetime.now().isoformat(timespec='seconds')
    common.append_line(dest / 'fetch_log.jsonl', json.dumps(rec))


def stop(dest, msg, count):
    """Stop the fetch on a write error (a full disk), with the counts so far."""
    print('  '.join(f'{k.lower()} {v}' for k, v in count.items()), file=sys.stderr)
    sys.exit(f'{msg}. The fetch stopped; PDFs saved before this have their fetch_log.jsonl line in {dest}. '
             f'Free some space and run the same command again: PDFs already held are not fetched twice')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='*', help='DOIs, arXiv ids or OpenAlex W ids')
    ap.add_argument('--from', dest='src', help='JSONL from openalex_search.py (uses doi, arxiv or openalex)')
    ap.add_argument('--dest', help='folder for new PDFs (default: download_dir in literature.json)')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    a = ap.parse_args(argv)
    ids, skips = list(a.ids), 0
    if a.src and not Path(a.src).is_file():
        sys.exit(f'--from {a.src}: file not found')
    if a.src:
        for n, line in enumerate(open(a.src, encoding='utf-8'), 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if not isinstance(r, dict):
                    raise ValueError('not an object')
            except ValueError as e:
                sys.exit(f'{a.src} line {n}: not a JSON record ({e}); nothing fetched')
            ident = r.get('doi') or r.get('arxiv') or r.get('openalex')
            if ident:
                ids.append(ident)
            else:
                print(f'SKIP    line {n}: no doi, arxiv or openalex id ({r.get("title")})'); skips += 1
    global KEY
    cfg = common.load_config(a.config, required=not a.dest)
    KEY = common.api_key('OPENALEX_API_KEY', cfg, required=False)
    dest = Path(a.dest) if a.dest else cfg['download_dir']
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.exit(f'cannot create the download folder {dest} ({e}); nothing fetched')
    roots = [dest] + ([d for d in cfg['pdf_dirs'] if d != dest] if cfg else [])
    held, source_files = {}, []
    for k, v in common.sources(cfg).items():
        files = [p for p in v.get('pdfs', []) if p.is_file() and is_pdf(p)]
        source_files.extend(files)
        if v['doi'] and files:
            held[v['doi']] = (k, files)
        elif v['doi'] and v['pdf']:
            print(f'NOTE    sources key {k}: {v["pdf"]} not found; fetching its DOI again', file=sys.stderr)
    digests, count = None, {'OK': 0, 'HAVE': 0, 'MANUAL': 0, 'ERROR': 0, 'SKIP': skips}
    offline = 0                                  # papers in a row that failed on the network alone
    for n_done, ident in enumerate(ids):
        if offline == OFFLINE_STOP:
            left = len(ids) - n_done
            print('  '.join(f'{k.lower()} {v}' for k, v in count.items()), file=sys.stderr)
            sys.exit(f'{OFFLINE_STOP} papers in a row could not reach any server: the network looks down. Stopped with '
                     f'{left} of {len(ids)} not tried; run the same command again when online (PDFs already held are '
                     f'not fetched twice)')
        doi = common.doi_of(ident)
        requested_kind, requested_value = common._norm_id(ident)
        pinned = requested_kind == 'arxiv' and re.search(r'v\d+$', requested_value)
        if doi and held.get(doi):
            k, files = held[doi]
            match = next(((p, rec) for p in files
                          if (rec := pdf_provenance(p.read_bytes(), ident))
                          and (not pinned or rec.get('pdf_arxiv_id') == requested_value)), None)
            if match:
                p, rec = match
                try:
                    log_line(dest, {'id': ident, 'status': 'HAVE', 'file': os.path.relpath(p, dest),
                                    'sha256': common.sha256_file(p), **rec})
                except OSError as e:
                    stop(dest, f'cannot write {dest / "fetch_log.jsonl"} ({e})', count)
                print(f'HAVE    {ident} -> sources key {k} ({version_note(rec)})')
                count['HAVE'] += 1; continue
        try:
            w, failed = openalex(ident), None
        except Exception as e:
            w, failed = None, e              # an arXiv id can still be fetched straight from arXiv
        if isinstance(failed, urllib.error.HTTPError) and failed.code in (401, 403):
            sys.exit(f'OpenAlex refused the request (HTTP {failed.code}): OPENALEX_API_KEY is wrong or expired. '
                     f'Fix it, or remove it to fetch without a key')
        if failed:
            print(f'NOTE    {ident}: OpenAlex lookup failed ({failed})', file=sys.stderr)
        elif w is None:
            print(f'NOTE    {ident}: not in OpenAlex', file=sys.stderr)
        net_down = isinstance(failed, OSError) and not isinstance(failed, urllib.error.HTTPError)
        out = dest / (name_for(w, ident) if w else re.sub(r'\W', '_', ident) + '.pdf')
        have = next((h for r in roots for h in r.rglob(out.name)), None)
        if have and not is_pdf(have):
            print(f'ERROR   {ident}: {have} exists but is not a PDF (a broken download?); move it away and run again')
            count['ERROR'] += 1; continue
        if have:
            rec = pdf_provenance(have.read_bytes(), ident, w)
            if not pinned or rec.get('pdf_arxiv_id') == requested_value:
                try:
                    log_line(dest, {'id': ident, 'status': 'HAVE', 'file': os.path.relpath(have, dest),
                                    'sha256': common.sha256_file(have), **rec})
                except OSError as e:
                    stop(dest, f'cannot write {dest / "fetch_log.jsonl"} ({e})', count)
                print(f'HAVE    {ident} -> {have} ({version_note(rec)})'); count['HAVE'] += 1; continue
        urls, answered = candidates(ident, w), False       # answered: a server replied (an HTTP error, not a PDF)
        meta = {k: v for k, v in common.bib(w).items() if v} if w else {}   # for the citation in rank.py's CSV
        for url in urls:
            try:
                data = fetch(url)
            except Exception as e:
                answered = answered or not isinstance(e, OSError) or isinstance(e, urllib.error.HTTPError)
                print(f'  fail  {url}: {e}', file=sys.stderr); continue
            answered = True
            offline = 0
            if data:
                provenance = pdf_provenance(data, ident, w, url)
                if pinned and (provenance.get('pdf_arxiv_id') != requested_value or
                               provenance['identity_status'] == 'conflicting_arxiv_identifiers'):
                    print(f'  fail  {url}: requested arXiv revision not verified in PDF', file=sys.stderr)
                    continue
                if digests is None:
                    paths = source_files + [h for r in roots for h in r.rglob('*.pdf', case_sensitive=False)]
                    digests = {common.sha256_file(h): h for h in paths}
                d = hashlib.sha256(data).hexdigest()
                # Two unrecognised revisions can share every publication field and URL.
                base = Path(name_for(w or {}, ident, provenance))
                out = dest / f'{base.stem}_{d[:12]}.pdf'
                if d in digests:
                    try:
                        log_line(dest, {'id': ident, 'status': 'HAVE', 'url': url,
                                        'file': os.path.relpath(digests[d], dest), 'sha256': d, **meta, **provenance})
                    except OSError as e:
                        stop(dest, f'cannot write {dest / "fetch_log.jsonl"} ({e})', count)
                    print(f'HAVE    {ident} -> {digests[d]} (same file) ({version_note(provenance)})'); count['HAVE'] += 1; break
                try:
                    created = save(out, data)
                    if not created and common.sha256_file(out) != d:
                        print(f'ERROR   {ident}: {out} contains different bytes; nothing overwritten')
                        count['ERROR'] += 1; break
                except OSError as e:
                    stop(dest, f'cannot save {out} ({e})', count)
                status = 'OK' if created else 'HAVE'
                try:
                    log_line(dest, {'id': ident, 'status': status, 'url': url, 'file': out.name, 'sha256': d,
                                    'bytes': len(data), **meta, **provenance})
                except OSError as e:
                    if created:
                        out.unlink(missing_ok=True)   # preserve any file owned by another process
                    action = f'{out.name} removed again' if created else 'existing file preserved'
                    stop(dest, f'cannot write {dest / "fetch_log.jsonl"} ({e}); {action}', count)
                digests[d] = out
                print(f'{status:8}{ident} -> {out}  ({len(data) // 1024} kB, {url}; {version_note(provenance)})')
                count[status] += 1; break
            print(f'  fail  {url}: not a PDF', file=sys.stderr)
        else:
            if not answered and (net_down or urls):
                offline += 1
            else:
                offline = 0
            if failed:
                print(f'ERROR   {ident}: OpenAlex lookup failed ({failed})'); count['ERROR'] += 1; continue
            if urls and not answered:                       # every URL failed on the network: try again later
                print(f'ERROR   {ident}: no PDF URL could be reached (network)'); count['ERROR'] += 1; continue
            land = ((w or {}).get('primary_location') or {}).get('landing_page_url') or (f'https://doi.org/{doi}' if doi else ident)
            try:
                log_line(dest, {'id': ident, 'status': 'MANUAL', 'title': (w or {}).get('display_name'), 'url': land})
            except OSError as e:
                stop(dest, f'cannot write {dest / "fetch_log.jsonl"} ({e})', count)
            print(f'MANUAL  {ident}: {land}'); count['MANUAL'] += 1
    sys.stdout.flush()                               # the counts come last, after every paper's line
    print('  '.join(f'{k.lower()} {v}' for k, v in count.items()), file=sys.stderr)
    if count['MANUAL'] or count['ERROR'] or count['SKIP']:
        sys.exit(1)


if __name__ == '__main__':
    main()
