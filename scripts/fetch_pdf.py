"""Download open-access PDFs for DOIs or arXiv ids into the project's download_dir (literature.json).

Order tried: arXiv, then every OpenAlex location that lists a pdf_url.
A file is kept only if it starts with %PDF. Publisher pages that answer 403
are reported as MANUAL with their landing URL: ask a person to download them.
Existing files are never overwritten. A DOI already in the sources table counts as held, and a download that is
byte-identical to a PDF already in the folders is not saved. Only http(s) URLs on public addresses are fetched (every
redirect is checked too), at most 100 MB and 5 minutes per file. Each saved PDF gets a line in fetch_log.jsonl in the
download folder: id, URL, file and SHA-256. Exit status 1 if any paper was not obtained or skipped.
File names end in a short hash of the DOI, so two papers with the same author, year and title words don't collide.

  python fetch_pdf.py 10.1109/JSAC.2024.1234567 2601.11698
  python fetch_pdf.py --from $SP/x17.jsonl
"""
import argparse, datetime, hashlib, http.client, ipaddress, json, os, re, socket, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

KEY = None

UA = {'User-Agent': 'Mozilla/5.0 (research; literature fetch)'}
MAX_BYTES, MAX_SECONDS = 100 * 2**20, 300


def openalex(ident):
    """The OpenAlex work for a DOI, arXiv id or OpenAlex id; None if OpenAlex does not have it."""
    kind, v = common.norm_id(ident)
    path = 'works/' + (v if kind == 'openalex' else 'doi:' + urllib.parse.quote(common.doi_of(ident)))
    try:
        return common.open_json(urllib.request.Request(f'https://api.openalex.org/{path}',
                                                       headers={'Authorization': 'Bearer ' + KEY}), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def name_for(w, ident):
    surname = re.sub(r'\W', '', ((w.get('authorships') or [{}])[0].get('author', {}).get('display_name') or 'Anon').split()[-1])
    stop = {'a', 'an', 'the', 'of', 'for', 'and', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at'}
    words = [x for x in re.findall(r'[A-Za-z0-9]+', w.get('display_name') or '') if x.lower() not in stop][:5]
    tag = hashlib.sha1(((w.get('doi') or '').removeprefix('https://doi.org/') or common.doi_of(ident) or ident).lower()
                       .encode()).hexdigest()[:6]
    return f"{surname}{w.get('publication_year') or ''}_{''.join(x[:1].upper() + x[1:] for x in words)}_{tag}.pdf"


def candidates(ident, w):
    urls = []
    kind, v = common.norm_id(ident)
    arx = v if kind == 'arxiv' else None
    for l in (w or {}).get('locations') or []:
        land = l.get('landing_page_url') or ''
        if 'arxiv.org/abs/' in land:
            arx = arx or land.split('/abs/')[-1]
    if arx:
        urls.append(f'https://arxiv.org/pdf/{arx}')
    for l in [(w or {}).get('best_oa_location') or {}] + ((w or {}).get('locations') or []):
        if l.get('pdf_url') and l['pdf_url'] not in urls:
            urls.append(l['pdf_url'])
    return urls


def check_url(url):
    """Refuse anything but http(s) to a public address, so a listed or redirected URL cannot reach local files,
    this machine or the local network."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise ValueError(f'not an http(s) URL: {url}')
    for *_, addr in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == 'https' else 80)):
        if not ipaddress.ip_address(addr[0].split('%')[0]).is_global:
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
        if length and len(data) < length:
            raise http.client.IncompleteRead(bytes(data), length - len(data))
        return bytes(data)
    data = common.retry(once, tries=3, wait=5)
    return data if data[:4] == b'%PDF' else None


def save(out, data):
    """Write data to out without ever replacing a file there: written to a .part file first, then linked into place,
    so a crash leaves no half-written PDF under the final name. False if out already exists."""
    part = out.with_name(f'.{out.name}.{os.getpid()}.part')
    try:
        part.write_bytes(data)
        os.link(part, out)
        return True
    except FileExistsError:
        return False
    finally:
        part.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='*', help='DOIs, arXiv ids or OpenAlex W ids')
    ap.add_argument('--from', dest='src', help='JSONL from openalex_search.py (uses doi, arxiv or openalex)')
    ap.add_argument('--dest', help='folder for new PDFs (default: download_dir in literature.json)')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    a = ap.parse_args(argv)
    ids, skips = list(a.ids), 0
    if a.src:
        for n, line in enumerate(open(a.src, encoding='utf-8'), 1):
            if not line.strip():
                continue
            r = json.loads(line)
            ident = r.get('doi') or r.get('arxiv') or r.get('openalex')
            if ident:
                ids.append(ident)
            else:
                print(f'SKIP    line {n}: no doi, arxiv or openalex id ({r.get("title")})'); skips += 1
    global KEY
    cfg = common.load_config(a.config, required=not a.dest)
    KEY = common.api_key('OPENALEX_API_KEY', cfg)
    dest = Path(a.dest) if a.dest else cfg['download_dir']
    dest.mkdir(parents=True, exist_ok=True)
    roots = [dest] + ([d for d in cfg['pdf_dirs'] if d != dest] if cfg else [])
    held = {v['doi']: k for k, v in common.sources(cfg).items() if v['doi']}
    digests, count = None, {'OK': 0, 'HAVE': 0, 'MANUAL': 0, 'ERROR': 0, 'SKIP': skips}
    for ident in ids:
        doi = common.doi_of(ident)
        if doi and held.get(doi):
            print(f'HAVE    {ident} -> sources key {held[doi]}'); count['HAVE'] += 1; continue
        try:
            w, failed = openalex(ident), None
        except Exception as e:
            w, failed = None, e              # an arXiv id can still be fetched straight from arXiv
        if failed:
            print(f'NOTE    {ident}: OpenAlex lookup failed ({failed})', file=sys.stderr)
        elif w is None:
            print(f'NOTE    {ident}: not in OpenAlex', file=sys.stderr)
        out = dest / (name_for(w, ident) if w else re.sub(r'\W', '_', ident) + '.pdf')
        have = next((h for r in roots for h in r.rglob(out.name)), None)
        if have:
            print(f'HAVE    {ident} -> {have}'); count['HAVE'] += 1; continue
        for url in candidates(ident, w):
            try:
                data = fetch(url)
            except Exception as e:
                print(f'  fail  {url}: {e}', file=sys.stderr); continue
            if data:
                if digests is None:
                    digests = {common.sha256_file(h): h for r in roots for h in r.rglob('*.pdf')}
                d = hashlib.sha256(data).hexdigest()
                if d in digests:
                    print(f'HAVE    {ident} -> {digests[d]} (same file)'); count['HAVE'] += 1; break
                if not save(out, data):
                    print(f'HAVE    {ident} -> {out}'); count['HAVE'] += 1; break
                digests[d] = out
                with open(dest / 'fetch_log.jsonl', 'a', encoding='utf-8') as log:
                    log.write(json.dumps({'id': ident, 'url': url, 'file': out.name, 'sha256': d, 'bytes': len(data),
                                          'fetched': datetime.datetime.now().isoformat(timespec='seconds')}) + '\n')
                print(f'OK      {ident} -> {out}  ({len(data) // 1024} kB, {url})'); count['OK'] += 1; break
            print(f'  fail  {url}: not a PDF', file=sys.stderr)
        else:
            if failed:
                print(f'ERROR   {ident}: OpenAlex lookup failed ({failed})'); count['ERROR'] += 1; continue
            land = ((w or {}).get('primary_location') or {}).get('landing_page_url') or (f'https://doi.org/{doi}' if doi else ident)
            print(f'MANUAL  {ident}: {land}'); count['MANUAL'] += 1
    print('  '.join(f'{k.lower()} {v}' for k, v in count.items()), file=sys.stderr)
    if count['MANUAL'] or count['ERROR'] or count['SKIP']:
        sys.exit(1)


if __name__ == '__main__':
    main()
