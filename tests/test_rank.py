import csv, json

import numpy as np
import pytest

import rank
from conftest import FakeVoyage, WordTokenizer


@pytest.fixture
def offline(monkeypatch):
    fake = FakeVoyage()
    monkeypatch.setattr(rank, 'call', fake)
    monkeypatch.setattr(rank, 'tokenizer', WordTokenizer)
    monkeypatch.setattr(rank, 'WIN', 60)
    monkeypatch.setattr(rank, 'STEP', 50)
    monkeypatch.setenv('VOYAGE_API_KEY', 'test')
    return fake


def test_windows_cut_bibliography_and_label_pages(project):
    rank.WIN, rank.STEP = 60, 50
    try:
        wins, head, cut, has_ab, n = rank.windows(project / 'papers/topic/Switch2024.pdf', WordTokenizer())
    finally:
        rank.WIN, rank.STEP = 1200, 1000
    assert cut is True
    assert not any('Title three' in w['text'] for w in wins)
    assert {w['pages'] for w in wins} >= {'p. 1', 'p. 2'}
    assert any('youngest' in w['text'] and '2' in w['pages'] for w in wins)


def test_bm25_prefers_matching_doc():
    s = rank.bm25_scores(['seawater links', 'quantum switch scheduling', 'switch'], 'switch scheduling')
    assert s[1] > s[2] > s[0] == 0


def test_min_ranks_share_ties():
    assert rank.min_ranks(np.array([0.5, 0.9, 0.5, 0.1])).tolist() == [2, 1, 2, 4]


def test_pick_respects_overlap():
    wins = [{'span': (0, 100)}, {'span': (10, 110)}, {'span': (90, 190)}, {'span': (200, 300)}]
    assert rank.pick(wins, np.array([4, 3, 2, 1])) == [0, 2, 3]


def test_dry_run_makes_no_api_call(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/r'), '--dry'])
    assert offline.calls == []
    assert 'estimated' in capsys.readouterr().err
    assert not (project / 'runs').exists()


def test_budget_stops_before_api(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='above --budget'):
        rank.main(['--out', str(project / 'runs/r'), '--budget', '10'])
    assert offline.calls == []


def test_full_run_columns_fusion_and_run_record(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/r'), '--expect', 'Switch2024'])
    rows = list(csv.DictReader(open(project / 'runs/r_hybrid.csv')))
    assert list(rows[0])[:5] == ['paper', 'fused_rank', 'fused_score', 'Q0_main_rank', 'Q0_main_score']
    assert 'Q3_context_pages' in rows[0] and not any(k.startswith('Q4') for k in rows[0])
    assert {r['paper'] for r in rows} == {'Switch2024', 'Ocean2023', 'queue2022'}   # sources key kept
    assert rows[0]['paper'] == 'Switch2024' and rows[0]['fused_rank'] == '1'
    q3 = {r['paper']: int(r['Q3_context_rank']) for r in rows}
    assert q3['Ocean2023'] == 1                       # context query still ranked, just not fused
    run = json.load(open(project / 'runs/r_run.json'))
    assert run['fuse'] == ['Q0', 'Q1'] and run['corpus']['papers'] == 3
    assert run['models']['rerank'] == 'rerank-3' and run['usage']['rerank'] > 0
    assert all(b['truncation'] is False for e, b in offline.calls)


def test_dense_variant_and_ids_filter(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'ids.csv').write_text('paper\nqueue2022\nOcean2023\n')
    rank.main(['--out', str(project / 'runs/d'), '--variants', 'dense', '--ids', str(project / 'ids.csv')])
    rows = list(csv.DictReader(open(project / 'runs/d_dense.csv')))
    assert {r['paper'] for r in rows} == {'queue2022', 'Ocean2023'}


def test_missing_id_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'ids.csv').write_text('paper\nnope\n')
    with pytest.raises(SystemExit, match='no PDF'):
        rank.main(['--out', str(project / 'runs/x'), '--ids', str(project / 'ids.csv')])


def test_bm25_provider_needs_no_key_or_api(project, offline, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('VOYAGE_API_KEY')
    (project / 'literature.json').write_text('{"pdf_dirs": ["papers"], "sources": "sources.csv", "queries": "queries.json", '
                                             '"rank": {"provider": "bm25"}}')
    rank.main(['--out', str(project / 'runs/b'), '--budget', '10'])   # budget only guards API tokens
    assert offline.calls == []
    rows = list(csv.DictReader(open(project / 'runs/b_bm25.csv')))
    assert rows[0]['paper'] == 'Switch2024'
    assert {r['paper']: int(r['Q3_context_rank']) for r in rows}['Ocean2023'] == 1
    assert all(r['Q0_main_pages'] for r in rows)
    run = json.load(open(project / 'runs/b_run.json'))
    assert run['models']['provider'] == 'bm25' and run['models']['rerank'] is None and run['usage'] == {}


def test_provider_flag_overrides_config(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/f'), '--provider', 'bm25'])
    assert offline.calls == [] and (project / 'runs/f_bm25.csv').exists()


def test_bm25_rejects_variants(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='voyage provider only'):
        rank.main(['--out', str(project / 'runs/v'), '--provider', 'bm25', '--variants', 'dense'])


def test_changed_queries_refuse_previous_out(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    out = str(project / 'runs/q')
    rank.main(['--out', out, '--provider', 'bm25'])
    rank.main(['--out', out, '--provider', 'bm25'])                   # same queries: rerun allowed
    q = project / 'queries.json'
    q.write_text(q.read_text().replace('underwater seawater ocean links', 'ocean links'))
    with pytest.raises(SystemExit, match='different queries'):
        rank.main(['--out', out, '--provider', 'bm25', '--dry'])
    rank.main(['--out', str(project / 'runs/q2'), '--provider', 'bm25'])   # new --out is fine
