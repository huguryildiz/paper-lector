import json

import search_overlap


def write(tmp_path, name, mode, works):
    (tmp_path / f'{name}.jsonl').write_text(''.join(json.dumps(w) + '\n' for w in works))
    (tmp_path / f'{name}.query.json').write_text(json.dumps({'mode': mode}))
    return str(tmp_path / f'{name}.jsonl')


def test_low_overlap_lists_semantic_only_titles(tmp_path, capsys):
    kw = write(tmp_path, 'k', 'exact', [{'openalex': 'W1', 'doi': '10.1/a', 'title': 'A'}, {'openalex': 'W2', 'title': 'B'}])
    sem = write(tmp_path, 's', 'semantic', [{'openalex': 'W9', 'doi': '10.1/a', 'title': 'A'},   # same DOI, other id
                                           {'openalex': 'W3', 'title': 'C', 'year': 2021}, {'arxiv': '2101.1', 'title': 'D'}])
    search_overlap.main([kw, sem])
    out = capsys.readouterr().out
    assert 'distinct works: 4' in out and 'shared: 1' in out
    assert '1 of 3 (33%)  LOW OVERLAP' in out
    assert 'only semantic: 2021  C' in out and 'only semantic: -  D' in out and 'only semantic: -  A' not in out


def test_high_overlap_has_no_warning_and_unknown_mode_no_share(tmp_path, capsys):
    kw = write(tmp_path, 'k', 'exact', [{'openalex': 'W1'}, {'openalex': 'W2'}])
    sem = write(tmp_path, 's', 'semantic', [{'openalex': 'W1'}, {'openalex': 'W2'}, {'openalex': 'W3'}])
    search_overlap.main([kw, sem])
    out = capsys.readouterr().out
    assert '2 of 3 (67%)' in out and 'LOW OVERLAP' not in out
    (tmp_path / 's.query.json').unlink()
    search_overlap.main([kw, sem])
    assert 'semantic works' not in capsys.readouterr().out


def test_empty_keyword_file_still_gives_overlap(tmp_path, capsys):
    kw = write(tmp_path, 'k', 'exact', [])
    sem = write(tmp_path, 's', 'semantic', [{'openalex': 'W3', 'title': 'C', 'year': 2021}])
    search_overlap.main([kw, sem])
    out = capsys.readouterr().out
    assert '0 of 1 (0%)  LOW OVERLAP' in out and 'only semantic: 2021  C' in out


def test_cut_keyword_search_is_named(tmp_path, capsys):
    kw = write(tmp_path, 'k', 'exact', [{'openalex': 'W1'}])
    (tmp_path / 'k.query.json').write_text(json.dumps({'mode': 'exact', 'count': 900, 'written': 200,
                                                       'keyless_first_page_only': True}))
    sem = write(tmp_path, 's', 'semantic', [{'openalex': 'W2', 'title': 'B'}])
    search_overlap.main([kw, sem])
    out = capsys.readouterr().out
    assert 'LOW OVERLAP' in out and 'keyword search holds 200 of 900 works in k.jsonl (first page only, no API key)' in out
    (tmp_path / 'k.query.json').write_text(json.dumps({'mode': 'exact', 'count': 900, 'written': 50, 'max': 50,
                                                       'keyless_first_page_only': False}))
    search_overlap.main([kw, sem])
    assert '50 of 900 works in k.jsonl (capped by --max 50)' in capsys.readouterr().out


def test_empty_semantic_file_gives_undefined_overlap(tmp_path, capsys):
    kw = write(tmp_path, 'k', 'exact', [{'openalex': 'W1'}])
    sem = write(tmp_path, 's', 'semantic', [])
    search_overlap.main([kw, sem])
    out = capsys.readouterr().out
    assert 'overlap undefined: no semantic works' in out and 'semantic works the keyword' not in out
    (tmp_path / 'k.query.json').write_text(json.dumps({'mode': 'exact', 'count': 900, 'written': 200,
                                                       'keyless_first_page_only': True}))
    search_overlap.main([kw, sem])
    assert '200 of 900 works in k.jsonl (first page only, no API key)' in capsys.readouterr().out
