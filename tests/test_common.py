import json

import pytest

import common


def test_config_found_from_subfolder_and_paths_resolved(project):
    sub = project / 'papers' / 'topic'
    cfg = common.load_config(start=sub)
    assert cfg['path'] == project / 'literature.json'
    assert cfg['pdf_dirs'] == [project / 'papers']
    assert cfg['download_dir'] == project / 'papers' / 'new'
    assert cfg['queries'] == project / 'queries.json'


def test_config_search_stops_at_project_root(tmp_path):
    (tmp_path / 'literature.json').write_text('{"pdf_dirs": ["x"]}')
    inner = tmp_path / 'repo'
    (inner / '.git').mkdir(parents=True)
    assert common.load_config(start=inner, required=False) is None
    with pytest.raises(SystemExit, match='No literature.json'):
        common.load_config(start=inner)


def test_config_rejects_bad_pdf_dirs(project):
    (project / 'literature.json').write_text('{"pdf_dirs": "papers"}')
    with pytest.raises(SystemExit, match='pdf_dirs'):
        common.load_config(start=project)


def test_config_rank_provider_default_and_validation(project):
    assert common.load_config(start=project)['provider'] == 'voyage'
    (project / 'literature.json').write_text('{"pdf_dirs": ["papers"], "rank": {"provider": "openai"}}')
    with pytest.raises(SystemExit, match='provider is one of voyage, bm25'):
        common.load_config(start=project)


def test_sources_paths_relative_to_config(project):
    s = common.sources(common.load_config(start=project))
    assert s['queue2022']['pdf'] == project / 'papers' / 'topic' / 'Queue2022.pdf'
    assert s['queue2022']['doi'] == '10.1/q'


def test_api_key_order(project, monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('VOYAGE_API_KEY', raising=False)
    cfg = common.load_config(start=project)
    with pytest.raises(SystemExit, match='VOYAGE_API_KEY is not set'):
        common.api_key('VOYAGE_API_KEY', cfg)
    (project / '.env').write_text('VOYAGE_API_KEY="from-project"\n')
    assert common.api_key('VOYAGE_API_KEY', cfg) == 'from-project'
    monkeypatch.setenv('VOYAGE_API_KEY', 'from-env')
    assert common.api_key('VOYAGE_API_KEY', cfg) == 'from-env'


def test_queries_default_fuse_and_empty_slot(project):
    question, Q, fuse = common.load_queries(project / 'queries.json')
    assert list(Q) == ['Q0', 'Q1', 'Q2', 'Q3']          # empty Q4 skipped
    assert fuse == ['Q0', 'Q1']                         # main and subject
    assert question.startswith('Which user')


@pytest.mark.parametrize('bad, msg', [
    ({'queries': {'Q0': {'label': 'goal', 'text': 'x'}}}, 'must be one of'),
    ({'queries': {'Q0': {'label': 'subject', 'text': 'x'}}}, 'label "main" is required'),
    ({'queries': {'A': {'label': 'main', 'text': 'x'}}}, 'must look like Q0'),
    ({'queries': {'Q0': {'label': 'main', 'text': 'x'}}, 'fuse': ['Q1']}, 'fuse'),
])
def test_queries_validation(tmp_path, bad, msg):
    p = tmp_path / 'q.json'
    p.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match=msg):
        common.load_queries(p)
