import json

import pytest

import common


def test_config_found_from_subfolder_and_paths_resolved(project):
    sub = project / 'papers' / 'topic'
    cfg = common.load_config(start=sub)
    assert cfg['path'] == project / 'literature.json'
    assert cfg['pdf_dirs'] == [project / 'papers']
    assert cfg['download_dir'] == project / 'papers' / 'new'
    assert cfg['queries'] == project / 'queries/queries.json'


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
    question, Q, fuse = common.load_queries(project / 'queries/queries.json')
    assert list(Q) == ['Q0', 'Q1', 'Q2', 'Q3']          # empty Q4 skipped
    assert fuse == ['Q0', 'Q1']                         # main and subject
    assert question.startswith('Which user')


@pytest.mark.parametrize('bad, msg', [
    ({'queries': {'Q0': {'label': 'goal', 'text': 'x'}}}, 'must be one of'),
    ({'queries': {'Q0': {'label': 'subject', 'text': 'x'}}}, 'label "main" is required'),
    ({'queries': {'A': {'label': 'main', 'text': 'x'}}}, 'must look like Q0'),
    ({'queries': {'Q0': {'label': 'main', 'text': 'x'}}, 'fuse': ['Q1']}, 'fuse'),
    ({'queries': {'Q0': {'label': 'main', 'text': 'x'}}, 'fuse': ['Q0', 'Q0']}, 'names a query twice'),
    ({'queries': {'Q0': {'label': 'main', 'text': 'x'}}, 'fuse': {'Q0': 1}}, 'non-empty list'),
    ({'queries': {'Q0': {'label': 'main', 'text': 'x'}}, 'fuse': {}}, 'non-empty list'),
    ({'queries': {'Q0': {'label': 'main', 'text': 123}}}, 'must be a string'),
    ({'queries': {'Q0': None}}, 'must be an object'),
    ([1, 2], 'one JSON object'),
])
def test_queries_validation(tmp_path, bad, msg):
    p = tmp_path / 'q.json'
    p.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match=msg):
        common.load_queries(p)


def test_missing_sources_table_is_skipped(project, capsys):
    (project / 'sources.csv').unlink()
    assert common.sources(common.load_config(start=project)) == {}
    assert 'not found' in capsys.readouterr().err


def test_open_json_retries_network_errors(monkeypatch):
    import io, urllib.error
    calls = []
    def fake(req, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError('connection reset') if len(calls) == 1 else TimeoutError()
        return io.BytesIO(b'{"ok": 1}')
    monkeypatch.setattr(common.urllib.request, 'urlopen', fake)
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    assert common.open_json('req', timeout=1) == {'ok': 1} and len(calls) == 3
    calls.clear()
    def bad(req, timeout):
        calls.append(1); raise urllib.error.HTTPError('u', 404, 'nf', {}, None)
    monkeypatch.setattr(common.urllib.request, 'urlopen', bad)
    with pytest.raises(urllib.error.HTTPError):
        common.open_json('req', timeout=1)
    assert len(calls) == 1                                       # 404 is not retried


def test_duplicate_source_keys_are_refused(project):
    (project / 'sources.csv').write_text('key,pdf_path,doi\nk,a.pdf,10.1/a\nk,b.pdf,10.1/b\n')
    with pytest.raises(SystemExit, match='appears twice'):
        common.sources(common.load_config(start=project))


@pytest.mark.parametrize('raw, want', [
    ('10.1109/ABC.1', ('doi', '10.1109/abc.1')),
    ('https://doi.org/10.1109/ABC.1', ('doi', '10.1109/abc.1')),
    ('doi:10.1/x', ('doi', '10.1/x')),
    ('10.48550/arxiv.2205.06300', ('arxiv', '2205.06300')),
    ('10.48550/arXiv.2205.06300', ('arxiv', '2205.06300')),
    ('arXiv:2205.06300', ('arxiv', '2205.06300')),
    ('https://arxiv.org/abs/2205.06300v2', ('arxiv', '2205.06300v2')),
    ('https://openalex.org/W123', ('openalex', 'W123')),
    ('W123', ('openalex', 'W123')),
])
def test_norm_id(raw, want):
    assert common.norm_id(raw) == want


def test_retry_covers_cut_off_body(monkeypatch):
    import http.client
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b'part')
        return 'ok'
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    assert common.retry(flaky) == 'ok' and len(calls) == 2
