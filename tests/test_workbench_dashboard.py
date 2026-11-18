"""Workbench export gates and meaningful missing/stale/regression cases."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from AIQE.dashboard import (DashboardError, OutputNotSafeError, build_workbench_payload,
                            check_output_safety, main, render_html, write_dashboard)
from examples.showcase_workbench import generate, synthetic_documents


def save(tmp_path, document, name='work.json'):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding='utf-8')
    return path


def test_workbench_preserves_validated_decisions_and_unknowns(tmp_path):
    paths = [save(tmp_path, d, str(n)+'.json') for n, d in enumerate(synthetic_documents())]
    target, payload = write_dashboard([], tmp_path/'index.html', workbench_paths=paths)
    items = payload['workbench']['items']
    assert [i['facts']['status'] for i in items] == ['accepted', 'rejected', 'pending_review']
    assert items[1]['facts']['q6_findings'] == ['lost_detection']
    assert items[2]['facts']['stale'] is True
    assert items[2]['facts']['effort']['total_minutes'] is None
    assert items[2]['facts']['effort_trust']['verified_minutes'] is None
    assert items[0]['facts']['effort_trust']['verified_minutes'] is None
    assert payload['workbench']['unreadable'] == []
    html = target.read_text()
    assert 'Quality Workbench' in html and 'connect-src \'none\'' in html
    assert 'Detection preservation' in html and 'Human effort coverage' in html
    assert 'id="status"' in html and 'id="source"' in html and 'id="freshness"' in html


def test_invalid_json_raw_fields_and_native_reports_are_visible(tmp_path):
    valid = synthetic_documents()[0]
    raw = deepcopy(valid)
    raw['response'] = 'PRIVATE_RAW_RESPONSE_MUST_NOT_EXPORT'
    raw['PRIVATE_RAW_KEY_MUST_NOT_EXPORT'] = 'unapproved'
    save(tmp_path, raw, 'raw.json')
    (tmp_path/'duplicate.json').write_text('{"x":1,"x":2}')
    (tmp_path/'nonfinite.json').write_text('{"x":NaN}')
    save(tmp_path, {'metadata': {'source_type': 'synthetic'}}, 'native.json')
    target, payload = write_dashboard([], tmp_path/'index.html', workbench_paths=[tmp_path])
    assert not payload['workbench']['items']
    assert len(payload['workbench']['unreadable']) == 4
    assert {x['reason_code'] for x in payload['workbench']['unreadable']} == {'INVALID_JSON', 'FIELD_NOT_ALLOWED'}
    assert 'PRIVATE_RAW_RESPONSE_MUST_NOT_EXPORT' not in target.read_text()
    assert 'PRIVATE_RAW_KEY_MUST_NOT_EXPORT' not in target.read_text()


def test_duplicate_identity_rejects_all_copies_but_same_path_deduplicates(tmp_path):
    doc = synthetic_documents()[0]
    a = save(tmp_path, doc, 'a.json')
    assert len(build_workbench_payload([a, a])['items']) == 1
    b = save(tmp_path, doc, 'b.json')
    result = build_workbench_payload([a, b])
    assert result['items'] == []
    assert len(result['unreadable']) == 2
    assert all(x['reason_code'] == 'DUPLICATE_WORK_ITEM' for x in result['unreadable'])


def test_local_internal_keeps_output_safety_gate(tmp_path, monkeypatch):
    doc = synthetic_documents()[0]
    doc['source_type'], doc['data_classification'] = 'local_test', 'internal'
    path = save(tmp_path, doc)
    target, payload = write_dashboard([], tmp_path/'outside.html', workbench_paths=[path])
    assert payload['workbench']['items'][0]['facts']['source_type'] == 'local_test'
    import AIQE.dashboard as dashboard
    monkeypatch.setattr(dashboard, '_find_git_root', lambda _: Path('/invented-repo'))
    monkeypatch.setattr(dashboard, '_git_ignores', lambda *_: True)
    with pytest.raises(OutputNotSafeError, match='public_synthetic'):
        check_output_safety(tmp_path/'ignored.html', payload)
    monkeypatch.setattr(dashboard, '_git_ignores', lambda *_: False)
    with pytest.raises(OutputNotSafeError):
        check_output_safety(tmp_path/'unignored.html', payload)


def test_script_delimiters_cannot_escape_inline_json(tmp_path):
    doc = synthetic_documents()[0]
    doc['work_item']['frozen_scope'] = '</script><script>alert("unsafe")</script>'
    path = save(tmp_path, doc)
    _, payload = write_dashboard([], tmp_path/'index.html', workbench_paths=[path])
    html = render_html(payload)
    assert doc['work_item']['frozen_scope'] not in html
    assert '\\u003c/script\\u003e' in html


def test_cli_and_empty_inputs_keep_failure_visible(tmp_path, capsys):
    path = save(tmp_path, synthetic_documents()[0])
    assert main(['--workbench', str(path), '--out', str(tmp_path/'cli.html')]) == 0
    assert 'Workbench: 1 items; 0 rejected files' in capsys.readouterr().out
    missing = build_workbench_payload([tmp_path/'absent'])
    assert missing['unreadable'][0]['reason_code'] == 'NO_WORKBENCH_FILES'
    with pytest.raises(SystemExit):
        main(['--runs', str(path), '--workbench', str(path)])
    with pytest.raises(DashboardError):
        write_dashboard([path], tmp_path/'mixed.html', workbench_paths=[path])


def test_showcase_stays_synthetic_and_reproducible(tmp_path):
    a = generate(tmp_path/'a').read_bytes()
    b = generate(tmp_path/'b').read_bytes()
    assert a == b
    assert str(tmp_path).encode() not in a
    assert b'Synthetic demonstration' in a
    assert b'public_synthetic' in a
    assert b'local_test' in a  # filter option is not a source assertion
    for path in (tmp_path/'a/documents').glob('*.json'):
        doc = json.loads(path.read_text())
        assert doc['source_type'] == 'synthetic'
        assert doc['data_classification'] == 'public_synthetic'
