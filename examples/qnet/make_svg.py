"""Draw the animated README card for the qnet run from its rank CSV.

Every number comes from the CSV and its _rank_run.json; titles and authors come from the search JSONL files of the run.
Colors follow assets/icon.svg and the social preview: near-black ground, teal glass, gold reading leads.

  python make_svg.py runs/<prefix>_<name>_rank.csv ../../assets/qnet-output.svg
"""
import csv, json, re, sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP = 5
W = 880
STEP = 1.6                      # seconds the reading cursor rests on each row
HOLD = round(100 / TOP * 0.7)   # share of a cycle a row stays lit, in percent
TEAL, TEAL2, GOLD = '#2DD4BF', '#5EEAD4', '#F2B544'
INK, MUTED, FAINT = '#E6EDF3', '#8B9BB4', '#5F6B7A'
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
SERIF = "Georgia, 'Times New Roman', serif"


def short(s, n=60):
    return s if len(s) <= n else s[:n - 1].rstrip(' :,-') + '…'


def wrap(s, n=92):
    lines, cur = [], ''
    for w in s.split():
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur); cur = w
        else:
            cur = f'{cur} {w}'.strip()
    return lines + [cur]


def scan_frames():
    """Keyframes moving the cursor row by row: rest on a row, then slide to the next, back to the top at the end."""
    out = []
    for i in range(TOP):
        a, b = 100 * i / TOP, 100 * (i + 0.7) / TOP
        out.append(f'{a:.1f}%,{b:.1f}%{{transform:translateY({56 * i}px)}}')
    return ''.join(out) + '100%{transform:translateY(0)}'


def links(r):
    """Every link rank.py may have written for this search record."""
    out = []
    if r.get('doi'):
        out.append('https://doi.org/' + r['doi'])
    if r.get('arxiv'):
        out.append('https://arxiv.org/abs/' + r['arxiv'])
    if r.get('openalex'):
        out.append('https://openalex.org/' + r['openalex'])
    return out


def icon(x, y, s):
    """The paper-lector icon (assets/icon.svg) at (x, y), s pixels wide, without its animation."""
    k = s / 256
    return (f'<g transform="translate({x} {y}) scale({k:.4f})">'
            '<rect width="256" height="256" rx="56" fill="#141719"/>'
            f'<rect x="2" y="2" width="252" height="252" rx="54" fill="none" stroke="{TEAL}" stroke-opacity="0.3" stroke-width="4"/>'
            f'<rect x="68" y="52" width="116" height="150" rx="10" fill="{TEAL}" fill-opacity="0.1" stroke="{TEAL}" stroke-opacity="0.6" stroke-width="3"/>'
            f'<path d="M60 70 a10 10 0 0 1 10 -10 h70 l36 36 v104 a10 10 0 0 1 -10 10 h-96 a10 10 0 0 1 -10 -10 z" fill="#0F1A1A" stroke="{TEAL2}" stroke-width="5"/>'
            f'<rect x="74" y="108" width="88" height="16" rx="5" fill="{GOLD}"/>'
            f'<rect x="78" y="138" width="80" height="8" rx="4" fill="{TEAL2}" fill-opacity="0.5"/>'
            f'<rect x="78" y="156" width="64" height="8" rx="4" fill="{TEAL2}" fill-opacity="0.5"/>'
            f'<circle cx="168" cy="168" r="30" fill="{GOLD}" fill-opacity="0.12" stroke="{GOLD}" stroke-width="12"/>'
            f'<line x1="190" y1="190" x2="214" y2="214" stroke="{GOLD}" stroke-width="16" stroke-linecap="round"/>'
            '</g>')


def main(csv_path, out_path):
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
    run = json.load(open(csv_path[:-len('.csv')] + '_run.json'))
    models = f'{run["models"]["embed"]} + {run["models"]["rerank"]}' if run['models']['rerank'] else run['models']['provider']
    recs = {}
    for f in run['abstracts']['files']:
        for line in open(Path(csv_path).parent / Path(f['path']).name, encoding='utf-8'):
            r = json.loads(line)
            for k in links(r):
                recs.setdefault(k, r)
    pdf = sorted((r for r in rows if r['fused_rank']), key=lambda r: int(r['fused_rank']))
    fused = [run['queries'][q]['label'] for q in run['fuse']]
    question = run['question']

    qlines = wrap(question)
    head = 134 + 22 * (len(qlines) - 1) + 40
    first = head + 20
    height = first + 56 * TOP + 70
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
         f'font-family="{FONT}" role="img" aria-label="paper-lector example output: top {TOP} of {len(pdf)} PDFs">',
         '<title>paper-lector example output (quantum network scheduling)</title>',
         '<defs>'
         '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#121518"/>'
         '<stop offset="1" stop-color="#08090B"/></linearGradient>'
         f'<linearGradient id="row" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{TEAL}" stop-opacity="0.12"/>'
         f'<stop offset="1" stop-color="{TEAL}" stop-opacity="0.03"/></linearGradient>'
         f'<linearGradient id="rule" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{TEAL}"/>'
         f'<stop offset="1" stop-color="{TEAL}" stop-opacity="0"/></linearGradient>'
         '<filter id="glow" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="3" result="b"/>'
         '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
         '</defs>',
         '<style>'
         # every row is drawn in full; the animation only moves a gold reading cursor down the rows and lights the
         # row and page label under it, so a viewer that shows the first frame or no animation still shows the table
         f'.hl,.p{{animation:{STEP * TOP}s ease-in-out infinite}}'
         f'.hl{{animation-name:hl}}@keyframes hl{{0%,{HOLD}%{{stroke-opacity:.75}}{HOLD + 6}%,100%{{stroke-opacity:.18}}}}'
         f'.p{{animation-name:pl}}@keyframes pl{{0%,{HOLD}%{{fill-opacity:.38}}{HOLD + 6}%,100%{{fill-opacity:.16}}}}'
         f'.scan{{animation:scan {STEP * TOP}s ease-in-out infinite}}@keyframes scan{{{scan_frames()}}}'
         '@media (prefers-reduced-motion:reduce){.hl,.p,.scan{animation:none}}'
         '</style>',
         f'<rect width="{W}" height="{height}" rx="16" fill="url(#bg)"/>',
         f'<rect x="1" y="1" width="{W - 2}" height="{height - 2}" rx="15" fill="none" stroke="{TEAL}" stroke-opacity="0.28" stroke-width="1.5"/>',
         icon(28, 24, 44),
         f'<text x="86" y="44" fill="{INK}" font-family="{SERIF}" font-size="20" font-weight="700" letter-spacing="1.5">'
         f'PAPER-<tspan fill="{TEAL2}">LECTOR</tspan></text>',
         f'<text x="86" y="63" fill="{MUTED}" font-size="10.5" letter-spacing="2.6">EXAMPLE RUN · QUANTUM NETWORK SCHEDULING</text>',
         f'<rect x="28" y="86" width="64" height="3" rx="1.5" fill="url(#rule)"/>',
         f'<text x="28" y="112" fill="{MUTED}" font-size="11.5" letter-spacing="1.6" font-weight="600">QUESTION</text>']
    for i, line in enumerate(qlines):
        o.append(f'<text x="28" y="{134 + 22 * i}" fill="{INK}" font-size="15.5" font-weight="600">{escape(line)}</text>')
    for x, label, anchor in ((34, '#', 'middle'), (64, 'PAPER', 'start'), (592, 'ABSTRACT', 'middle'),
                             (678, 'CITED BY', 'middle'), (852, 'START AT', 'end')):
        o.append(f'<text x="{x}" y="{head}" fill="{MUTED}" font-size="11" letter-spacing="1.2" font-weight="600" '
                 f'text-anchor="{anchor}">{label}</text>')
    o.append(f'<line x1="28" y1="{head + 10}" x2="852" y2="{head + 10}" stroke="{TEAL}" stroke-opacity="0.25"/>')
    o.append(f'<rect class="scan" x="16" y="{first}" width="4" height="50" rx="2" fill="{GOLD}" filter="url(#glow)"/>')
    for i, r in enumerate(pdf[:TOP]):
        rec = recs.get(r['link'], {})
        title = rec.get('title') or r['paper']
        names = rec.get('authors') or ([rec['first_author']] if rec.get('first_author') else [])
        by = f'{names[0].split()[-1]}{" et al." if len(names) > 1 else ""}, {rec.get("year", "")}' if names else ''
        top = first + 56 * i
        mid = top + 32
        delay = f'animation-delay:{STEP * i:.1f}s'
        o.append('<g>')
        o.append(f'<rect class="hl" x="26" y="{top}" width="838" height="50" rx="9" fill="url(#row)" stroke="{TEAL}" '
                 f'stroke-opacity="{0.75 if i == 0 else 0.18}" style="{delay}"/>')
        o.append(f'<text x="44" y="{mid + 1}" fill="{GOLD}" font-family="{SERIF}" font-size="20" font-weight="700" '
                 f'text-anchor="middle">{r["fused_rank"]}</text>')
        o.append(f'<text x="64" y="{mid - 8}" fill="{INK}" font-size="14" font-weight="600">{escape(short(title))}</text>')
        o.append(f'<text x="64" y="{mid + 10}" fill="{MUTED}" font-size="12">{escape(by)}</text>')
        o.append(f'<text x="592" y="{mid}" fill="#C9D4E3" font-size="14" text-anchor="middle">{r["abs_fused_rank"] or "–"}</text>')
        o.append(f'<text x="678" y="{mid}" fill="#C9D4E3" font-size="14" text-anchor="middle">{r["cited_by"] or "–"}</text>')
        start = r['start_pages'].split(';')[0].strip()
        o.append(f'<rect class="p" x="764" y="{mid - 17}" width="88" height="24" rx="12" fill="{GOLD}" '
                 f'fill-opacity="{0.38 if i == 0 else 0.16}" stroke="{GOLD}" stroke-opacity="0.6" style="{delay}"/>')
        o.append(f'<text x="808" y="{mid}" fill="{GOLD}" font-size="13" font-weight="600" text-anchor="middle">{escape(start)}</text>')
        o.append('</g>')
    foot = first + 56 * TOP + 22
    o.append(f'<text x="28" y="{foot}" fill="{FAINT}" font-size="12">Top {TOP} of {len(pdf)} PDFs · {len(rows)} papers ranked on '
             f'abstracts · {escape(models)} · fused over {", ".join(fused)}</text>')
    o.append('</svg>')
    Path(out_path).write_text('\n'.join(o) + '\n', encoding='utf-8')
    print(f'{out_path}: top {TOP} of {len(pdf)} PDFs')


if __name__ == '__main__':
    main(*sys.argv[1:3])
