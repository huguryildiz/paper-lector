"""Download open-access PDFs for DOIs or arXiv ids into the project's download_dir (literature.json).

Order tried: arXiv, then every OpenAlex location that lists a pdf_url.
A file is kept only if it starts with %PDF. Publisher pages that answer 403
are reported as MANUAL with their landing URL: ask a person to download them.
Existing files are never overwritten.

  python fetch_pdf.py 10.1109/JSAC.2024.1234567 2601.11698
  python fetch_pdf.py --from $SP/x17.jsonl
"""
import argparse, json, re, sys, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

KEY = None

UA = {'User-Agent': 'Mozilla/5.0 (research; literature fetch)'}


def openalex(ident):
    doi = ident if ident.startswith('10.') else '10.48550/arXiv.' + ident.removeprefix('arXiv:')
    req = urllib.request.Request('https://api.openalex.org/works/doi:' + urllib.parse.quote(doi),
                                 headers={'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def name_for(w):
    surname = re.sub(r'\W', '', ((w.get('authorships') or [{}])[0].get('author', {}).get('display_name') or 'Anon').split()[-1])
    stop = {'a', 'an', 'the', 'of', 'for', 'and', 'in', 'on', 'with', 'to', 'via', 'under', 'by', 'at'}
    words = [x for x in re.findall(r'[A-Za-z0-9]+', w.get('display_name') or '') if x.lower() not in stop][:5]
    return f"{surname}{w.get('publication_year') or ''}_{''.join(x[:1].upper() + x[1:] for x in words)}.pdf"


def candidates(ident, w):
    urls = []
    arx = None if ident.startswith('10.') and not ident.lower().startswith('10.48550/arxiv.') else ident.split('arXiv.')[-1].removeprefix('arXiv:')
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


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = r.read()
    return data if data[:4] == b'%PDF' else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ids', nargs='*', help='DOIs or arXiv ids')
    ap.add_argument('--from', dest='src', help='JSONL from openalex_search.py (uses doi or arxiv)')
    ap.add_argument('--dest', help='folder for new PDFs (default: download_dir in literature.json)')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    a = ap.parse_args()
    ids = list(a.ids)
    if a.src:
        for line in open(a.src, encoding='utf-8'):
            r = json.loads(line)
            if r.get('doi') or r.get('arxiv'):
                ids.append(r['doi'] or r['arxiv'])
    global KEY
    cfg = common.load_config(a.config, required=not a.dest)
    KEY = common.api_key('OPENALEX_API_KEY', cfg)
    dest = Path(a.dest) if a.dest else cfg['download_dir']
    dest.mkdir(parents=True, exist_ok=True)
    roots = [dest] + ([d for d in cfg['pdf_dirs'] if d != dest] if cfg else [])
    for ident in ids:
        try:
            w = openalex(ident)
        except Exception as e:
            w = None
            print(f'NOTE    {ident}: not in OpenAlex ({e})', file=sys.stderr)
        out = dest / (name_for(w) if w else re.sub(r'\W', '_', ident) + '.pdf')
        have = next((h for r in roots for h in r.rglob(out.name)), None)
        if have:
            print(f'HAVE    {ident} -> {have}'); continue
        for url in candidates(ident, w):
            try:
                data = fetch(url)
            except Exception as e:
                print(f'  fail  {url}: {e}', file=sys.stderr); continue
            if data:
                out.write_bytes(data); print(f'OK      {ident} -> {out}  ({len(data) // 1024} kB)'); break
            print(f'  fail  {url}: not a PDF', file=sys.stderr)
        else:
            land = ((w or {}).get('primary_location') or {}).get('landing_page_url') or f'https://doi.org/{ident}'
            print(f'MANUAL  {ident}: {land}')


if __name__ == '__main__':
    main()
