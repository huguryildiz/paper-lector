import csv, json

import numpy as np
import pytest

import rank
from conftest import FakeVoyage, WordTokenizer


@pytest.fixture
def offline(monkeypatch, tmp_path):
    fake = FakeVoyage()
    monkeypatch.setattr(rank, 'CACHE', tmp_path / 'cache' / 'embeddings.sqlite')
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
    assert 'Title three' not in head                                  # no abstract found: head comes from cleaned text


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
    with pytest.raises(SystemExit, match='already exists'):            # same queries: never overwrite a run
        rank.main(['--out', out, '--provider', 'bm25'])
    rank.main(['--out', out, '--provider', 'bm25', '--dry'])           # a dry run writes nothing, so it may reuse it
    q = project / 'queries.json'
    q.write_text(q.read_text().replace('"question"', '"fuse": ["Q0", "Q3"], "question"'))
    with pytest.raises(SystemExit, match='different question, queries or fuse'):
        rank.main(['--out', out, '--provider', 'bm25', '--dry'])
    rank.main(['--out', str(project / 'runs/q2'), '--provider', 'bm25'])   # new --out is fine


def test_missing_pdf_folder_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='PDF folder not found'):
        rank.main(['--out', str(project / 'runs/x'), '--dry', '--dirs', str(project / 'nope')])


def test_empty_pdf_folder_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'empty').mkdir()
    (project / 'literature.json').write_text('{"pdf_dirs": ["empty"], "queries": "queries.json"}')
    with pytest.raises(SystemExit, match='no PDFs in'):
        rank.main(['--out', str(project / 'runs/x'), '--dry'])


def test_embedding_cache_skips_paid_calls_on_rerun(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/c1')])
    first = [e for e, _ in offline.calls].count('embeddings')
    offline.calls.clear()
    rank.main(['--out', str(project / 'runs/c2')])
    assert first > 0 and [e for e, _ in offline.calls].count('embeddings') == 0
    assert open(project / 'runs/c1_hybrid.csv').read() == open(project / 'runs/c2_hybrid.csv').read()
    run = json.load(open(project / 'runs/c2_run.json'))
    assert run['usage'].get('embed', 0) == 0 and run['usage']['embed_cached'] > 0


def test_same_file_name_in_two_folders_keeps_both(project, monkeypatch, capsys):
    from conftest import make_pdf
    other = project / 'papers' / 'other'
    other.mkdir()
    make_pdf(other / 'Ocean2023.pdf', [['A different paper about ocean acoustics']])
    make_pdf(other / 'Queue2022.pdf', [['Not the sources-table queue paper']])
    known = {'queue2022': {'pdf': project / 'papers/topic/Queue2022.pdf', 'doi': ''}}
    out = rank.find_pdfs([project / 'papers'], known)
    assert out['queue2022'] == project / 'papers/topic/Queue2022.pdf'
    assert out['Queue2022'] == other / 'Queue2022.pdf'           # same basename as a sources PDF, still ranked
    assert {out['Ocean2023'], out['Ocean2023-2']} == {other / 'Ocean2023.pdf', project / 'papers/topic/Ocean2023.pdf'}
    assert 'ranked as Ocean2023-2' in capsys.readouterr().err



def test_unreadable_pdf_recorded_and_fails_frozen_ids(project, offline, monkeypatch):
    from conftest import make_pdf
    monkeypatch.chdir(project)
    make_pdf(project / 'papers/topic/Scan2020.pdf', [[]])
    rank.main(['--out', str(project / 'runs/s'), '--provider', 'bm25'])
    run = json.load(open(project / 'runs/s_run.json'))
    assert run['corpus']['skipped'][0]['id'] == 'Scan2020' and 'Scan2020' not in run['corpus']['ids']
    (project / 'ids.csv').write_text('paper\nScan2020\nOcean2023\n')
    with pytest.raises(SystemExit, match='frozen corpus is incomplete'):
        rank.main(['--out', str(project / 'runs/s2'), '--provider', 'bm25', '--ids', str(project / 'ids.csv')])


def test_identical_copy_skipped_and_near_duplicate_reported(project, offline, monkeypatch):
    from conftest import make_pdf
    monkeypatch.chdir(project)
    src = project / 'papers/topic/Switch2024.pdf'
    (project / 'papers/copy').mkdir()
    (project / 'papers/copy/SwitchCopy.pdf').write_bytes(src.read_bytes())
    make_pdf(project / 'papers/copy/SwitchPreprint.pdf', [
        ['Age based scheduling at a quantum switch (preprint)', 'Abstract',
         'We study which user receives a stored entangled pair.'] + ['lorem ipsum dolor sit amet consectetur'] * 40,
        ['Our policy serves the youngest stored pair first', 'threshold structure of the optimal policy']])
    rank.main(['--out', str(project / 'runs/dup'), '--provider', 'bm25'])
    run = json.load(open(project / 'runs/dup_run.json'))
    kept = [i for i in run['corpus']['ids'] if i in ('Switch2024', 'SwitchCopy')]
    assert len(kept) == 1                                                  # byte-identical copy not ranked twice
    assert sorted([kept[0], 'SwitchPreprint']) in [sorted(p) for p in run['corpus']['possible_duplicates']]
    assert not any('Ocean2023' in p or 'queue2022' in p for p in run['corpus']['possible_duplicates'])


def test_missing_pdftotext_names_the_install(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank.shutil, 'which', lambda name: None)
    with pytest.raises(SystemExit, match='brew install poppler'):
        rank.main(['--out', str(project / 'runs/x'), '--dry'])


def test_offline_tokenizer_download_fails_cleanly(monkeypatch, tmp_path):
    import urllib.request
    monkeypatch.setattr(rank, 'TOK_PATH', tmp_path / 'tok.json')
    def no_net(url, path):
        open(path, 'w').write('{"partial')
        raise OSError('no network')
    monkeypatch.setattr(urllib.request, 'urlretrieve', no_net)
    with pytest.raises(SystemExit, match='rank.py --setup'):
        rank.tokenizer()
    assert not (tmp_path / 'tok.json').exists() and not (tmp_path / 'tok.part').exists()   # no half file left


def test_turkish_abstract_bibliography_and_terms():
    t = 'Başlık\nÖZET\n' + 'kelime ' * 80 + '\nGİRİŞ\nmetin\n'
    assert rank.abstract(t).startswith('kelime')
    assert rank.abstract('Giriş\nözellikle ' + 'kelime ' * 80 + '\nGiriş\n') is None       # "öz" inside a word is no heading
    refs = '\n'.join(f'[{i}] Yazar, Başlık, 2020.' for i in range(1, 6))
    body, cut, _ = rank.clean('satır metin\n' * 400 + 'KAYNAKLAR\n' + refs + '\nEK A\nek tablo\n')
    assert cut and 'Yazar' not in body and 'ek tablo' in body
    s = rank.bm25_scores(['güç tüketimi düşük', 'power routing', 'GÜÇ TÜKETİMİ'], 'güç tüketimi')
    assert s[0] > 0 and s[1] == 0 and s[2] > 0


@pytest.mark.parametrize('ab, intro, bib, app, ref', [
    ('Zusammenfassung', '1 Einleitung', 'Literaturverzeichnis', 'Anhang A', 'Müller, K. (2019). Titel. Verlag.'),
    ('RÉSUMÉ', 'INTRODUCTION', 'RÉFÉRENCES', 'ANNEXES', 'Dupont, J. (2018). Titre. Revue.'),
    ('Resumen', 'Introducción', 'Referencias bibliográficas', 'Apéndice A', 'García, L. (2020). Título. Revista.'),
    ('Riassunto', 'Introduzione', 'Bibliografia', 'Appendice', 'Rossi, M. (2017). Titolo. Rivista.'),
    ('Resumo', 'Introdução', 'Referências', 'Anexo A', 'Silva, P. (2021). Título. Revista.'),
    ('Аннотация', 'Введение', 'Список литературы', 'Приложение А', 'Иванов И.И. Название // Журнал. 2020. Т. 5.'),
])
def test_headings_in_other_languages(ab, intro, bib, app, ref):
    assert rank.abstract(f'Title\n{ab}\n' + 'word ' * 80 + f'\n{intro}\nbody\n').startswith('word')
    refs = '\n'.join(f'{i}. {ref}' for i in range(1, 6))
    body, cut, _ = rank.clean('line text\n' * 400 + bib + '\n' + refs + '\n' + app + '\nappendix table\n')
    assert cut and ref not in body and 'appendix table' in body
