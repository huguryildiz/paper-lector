"""Draw the README example image from a rank.py CSV.

Every number in the image comes from the CSV and its run record (_rank_run.json, or _run.json for older runs); titles, authors and gold labels come from papers.json.

  python make_svg.py runs/2026-10-18_audit_paper-lector_rank.csv ../../assets/example-output.svg
"""
import csv, json, sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP = 5
GOLD = '#F2B544'


def short(s, n=58):
    return s if len(s) <= n else s[:n - 1].rstrip(' :,-') + '…'


def wrap(s, n=86):
    lines, cur = [], ''
    for w in s.split():
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur); cur = w
        else:
            cur = f'{cur} {w}'.strip()
    return lines + [cur]


def main(csv_path, out_path):
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
    record = csv_path[:-len('.csv')] + '_run.json' if csv_path.endswith('_rank.csv') else csv_path.rsplit('_', 1)[0] + '_run.json'
    run = json.load(open(record))['models']                     # x_<name>_rank_run.json; older runs x_run.json
    models = f'{run["embed"]} + {run["rerank"]}' if run['embed'] else run['provider']
    meta = {p['file']: p for p in json.load(open(HERE / 'papers.json'))}
    question = json.load(open(HERE / 'queries/queries.json'))['question']
    main_col = next(c[:-5] for c in rows[0] if c.endswith('_rank') and c != 'fused_rank')
    subj_col = [c[:-5] for c in rows[0] if c.endswith('_rank') and c != 'fused_rank'][1]
    rows.sort(key=lambda r: int(r['fused_rank']))
    gold_ranks = sorted(int(r['fused_rank']) for r in rows if meta[r['paper']]['role'] == 'gold')

    qlines = wrap(question)
    y0 = 62 + 22 * (len(qlines) - 1)
    head_y = y0 + 40
    first_row = head_y + 20
    height = first_row + 52 * TOP + 62
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 {height}" width="880" height="{height}" '
         f'font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif">',
         '<title>paper-lector example output</title>',
         f'<rect width="880" height="{height}" rx="14" fill="#0b1220"/>',
         f'<rect x="0.5" y="0.5" width="879" height="{height - 1}" rx="14" fill="none" stroke="#24324a"/>',
         '<text x="28" y="38" fill="#8b9bb4" font-size="12" letter-spacing="1.5" font-weight="600">QUESTION (LITSEARCH)</text>']
    for i, line in enumerate(qlines):
        o.append(f'<text x="28" y="{62 + 22 * i}" fill="#e6edf3" font-size="16" font-weight="600">{escape(line)}</text>')
    o.append(f'<line x1="28" y1="{head_y + 10}" x2="852" y2="{head_y + 10}" stroke="#24324a"/>')
    for x, label, anchor in ((28, '#', 'start'), (64, 'PAPER', 'start'), (596, 'MAIN', 'middle'),
                             (680, 'SUBJECT', 'middle'), (852, 'START AT', 'end')):
        o.append(f'<text x="{x}" y="{head_y}" fill="#8b9bb4" font-size="11" letter-spacing="1.2" font-weight="600" '
                 f'text-anchor="{anchor}">{label}</text>')
    for i, r in enumerate(rows[:TOP]):
        m = meta[r['paper']]
        top = first_row + 52 * i
        mid = top + 32
        if i % 2 == 0:
            o.append(f'<rect x="16" y="{top}" width="848" height="48" rx="8" fill="#111b2e"/>')
        o.append(f'<text x="34" y="{mid}" fill="{GOLD}" font-size="18" font-weight="700" text-anchor="middle">{r["fused_rank"]}</text>')
        o.append(f'<text x="64" y="{mid - 9}" fill="#e6edf3" font-size="14.5" font-weight="600">{escape(short(m["title"]))}</text>')
        byline = f'{m["author"].split()[-1]} et al., {m["year"]}'
        o.append(f'<text x="64" y="{mid + 9}" fill="#8b9bb4" font-size="12.5">{escape(byline)}'
                 + (f'<tspan fill="#5fd39a" font-weight="600">  ·  LitSearch gold</tspan>' if m['role'] == 'gold' else '')
                 + '</text>')
        o.append(f'<text x="596" y="{mid}" fill="#c9d4e3" font-size="14" text-anchor="middle">{r[main_col + "_rank"]}</text>')
        o.append(f'<text x="680" y="{mid}" fill="#c9d4e3" font-size="14" text-anchor="middle">{r[subj_col + "_rank"]}</text>')
        start = r[main_col + '_pages'].split(';')[0].strip()
        o.append(f'<rect x="766" y="{mid - 17}" width="86" height="24" rx="12" fill="{GOLD}" fill-opacity="0.16" '
                 f'stroke="{GOLD}" stroke-opacity="0.5"/>')
        o.append(f'<text x="809" y="{mid}" fill="{GOLD}" font-size="13" font-weight="600" text-anchor="middle">{escape(start)}</text>')
    foot = first_row + 52 * TOP + 22
    o.append(f'<text x="28" y="{foot}" fill="#6b7a92" font-size="12">Top {TOP} of {len(rows)} PDFs · '
             f'{models} · fused over main and subject · '
             f'the {len(gold_ranks)} LitSearch gold papers rank {", ".join(map(str, gold_ranks))}</text>')
    o.append('</svg>')
    Path(out_path).write_text('\n'.join(o) + '\n', encoding='utf-8')
    print(f'{out_path}: gold papers at fused ranks {gold_ranks}')


if __name__ == '__main__':
    main(*sys.argv[1:3])
