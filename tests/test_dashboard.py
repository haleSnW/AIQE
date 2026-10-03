"""Offline dashboard contract regressions using public synthetic fixtures only."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from AIQE.contract import load_run, MetricStatus, compute_run_metrics
from AIQE.comparison import compare_runs
from AIQE.dashboard import (
    LoadedRun, RunGroup, _comparison_key, comparison_payload, load_runs,
    write_dashboard,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'synthetic'

def run(name):
    result = load_run(FIXTURES / 'valid' / (name + '.json'))
    result.metrics = compute_run_metrics(result)
    return result

def test_incomparable_dashboard_has_no_derived_changes():
    b, c = run('run_g_baseline'), run('run_l_dataset_v2')
    p = comparison_payload(LoadedRun(b, Path('b')), LoadedRun(c, Path('c')))
    assert not p['comparable']
    assert not p['case_transitions']
    assert all(m['display_delta'] is None for m in p['metric_series'].values())

@pytest.mark.parametrize('field,value', [('metric_version','future'), ('metric_unit','seconds'), ('status',MetricStatus.PARTIAL)])
def test_incompatible_metric_has_no_delta_anywhere(field, value):
    b, c = run('run_g_baseline'), run('run_g_candidate')
    metric_id = 'case_pass_rate'
    c.metrics = [replace(m, **{field:value}) if m.metric_id == metric_id else m for m in c.metrics]
    assert metric_id not in compare_runs(b,c).metric_deltas
    p = comparison_payload(LoadedRun(b,Path('b')),LoadedRun(c,Path('c')))
    assert p['metric_series'][metric_id]['display_delta'] is None

def test_html_generation_reports_invalid_inputs(tmp_path):
    path,payload = write_dashboard([FIXTURES/'valid', FIXTURES/'invalid'], tmp_path/'index.html')
    assert payload['totals']['run_count'] > 0
    assert payload['totals']['unreadable_count'] == 7
    html = path.read_text()
    embedded = html.split('<script type="application/json" id="aiqe-data">')[1].split('</script>')[0]
    assert json.loads(embedded) == payload

def test_duplicate_run_id_across_distinct_paths_rejects_all_conflicts(tmp_path):
    source = FIXTURES / 'valid' / 'run_g_baseline.json'
    first = tmp_path / 'first.json'
    second = tmp_path / 'second.json'
    first.write_bytes(source.read_bytes())
    second.write_bytes(source.read_bytes())

    loaded, failures = load_runs([first, second])

    assert loaded == []
    assert len(failures) == 2
    assert {failure.reason_code for failure in failures} == {'DUPLICATE_RUN_ID'}
    assert {Path(failure.source_path).name for failure in failures} == {
        'first.json',
        'second.json',
    }


def test_repeated_same_path_is_deduplicated_not_rejected():
    source = FIXTURES / 'valid' / 'run_g_baseline.json'

    loaded, failures = load_runs([source, source])

    assert len(loaded) == 1
    assert failures == []


def test_duplicate_run_id_rejected_even_when_records_and_groups_differ(
    tmp_path, monkeypatch
):
    first_run = run('run_g_baseline')
    second_run = run('run_l_dataset_v2')
    second_run = replace(
        second_run,
        metadata=replace(
            second_run.metadata,
            run_id=first_run.metadata.run_id,
        ),
    )

    first = tmp_path / 'first.json'
    second = tmp_path / 'second.json'
    first.write_text('{}', encoding='utf-8')
    second.write_text('{}', encoding='utf-8')

    runs_by_path = {
        first.resolve(): first_run,
        second.resolve(): second_run,
    }

    import AIQE.dashboard as dashboard_module

    monkeypatch.setattr(
        dashboard_module,
        'load_run',
        lambda path: runs_by_path[Path(path).resolve()],
    )

    loaded, failures = dashboard_module.load_runs([first, second])

    assert loaded == []
    assert len(failures) == 2
    assert {failure.reason_code for failure in failures} == {'DUPLICATE_RUN_ID'}


def test_comparison_and_group_keys_do_not_collide():
    assert _comparison_key('a||b', 'c') != _comparison_key('a', 'b||c')
    assert _comparison_key('a||b', 'c') == json.dumps(['a||b', 'c'], separators=(',', ':'))
    assert RunGroup('a@b', 'c', 'd', 'e').key != RunGroup('a', 'b@c', 'd', 'e').key


def test_metric_table_includes_candidate_only_metric_without_delta():
    baseline, candidate = run('run_g_baseline'), run('run_g_candidate')
    extra = replace(candidate.metrics[0], metric_id='new_metric', metric_unit='tokens')
    candidate.metrics.append(extra)
    payload = comparison_payload(LoadedRun(baseline, Path('b')), LoadedRun(candidate, Path('c')))
    row = payload['metric_series']['new_metric']
    assert row['baseline'] is None
    assert row['candidate']['metric_unit'] == 'tokens'
    assert row['display_delta'] is None


def test_cli_is_offline_only():
    from AIQE.dashboard import main
    with pytest.raises(SystemExit) as exc:
        main(['--serve'])
    assert exc.value.code == 2


def test_preexisting_temp_symlink_cannot_receive_dashboard_data(tmp_path):
    victim = tmp_path / 'victim.txt'
    victim.write_text('original', encoding='utf-8')
    target = tmp_path / 'index.html'
    target.with_suffix('.html.tmp').symlink_to(victim)
    write_dashboard([FIXTURES / 'valid'], target)
    assert victim.read_text(encoding='utf-8') == 'original'
    assert 'AIQE Dashboard' in target.read_text(encoding='utf-8')
