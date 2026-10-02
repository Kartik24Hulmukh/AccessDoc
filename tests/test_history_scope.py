"""Synthetic local supplied-metadata history regression tests; no source authentication."""
import copy
import json
import pytest
from app.models import AuditSummary, AuditViolation
from app.receipt_builder import build_receipt
from app.timeseries import build_trend, _detect_precision
from app.duediligence import build_due_diligence, render_due_diligence_md


def receipt(targets=('#a',), source='automated', date='2026-01-01'):
    vs = [AuditViolation('label', 'serious', 'Synthetic', '', source=source, target=t) for t in targets]
    r = build_receipt(AuditSummary(serious=len(vs), total_violations=len(vs),
                      url='https://example.test/login', engine_version='4.11.2'), vs,
                      {'audit_date': date, 'client_name': 'Synthetic'})
    return r, vs


def trend(p, c, vs):
    return json.loads(build_trend(p, c, vs))


@pytest.mark.parametrize('field,value', [
    ('url', 'https://example.test/other'), ('client_name', 'Other'),
    ('engine_version', '4.12'), ('catalog_version', 'other'),
    ('axe_core_verified_version', 'other'), ('scope', {'routes': ['/other']}),
    ('state', 'signed-in'), ('viewport', {'width': 800}), ('exclusions', ['menu']),
    ('authentication_context', 'member'), ('schema_version', '9.9'),
])
def test_incompatible_metadata_suppresses_all_deltas(field, value):
    p, _ = receipt(('#a',)); c, vs = receipt(('#b',))
    c[field] = value
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'not-comparable'
    assert out['delta_total_violations'] is None
    assert out['new_rules'] == [] and out['not_observed_rules'] == []
    assert 'not_observed_findings' not in out
    assert out['warnings']
    rec = build_due_diligence([p, c])
    assert rec['blocking_delta'] is None and rec['trend'] == 'not-comparable'
    assert rec['not_observed_count'] is None


@pytest.mark.parametrize('field', ['url', 'client_name', 'engine_version', 'catalog_version'])
def test_unknown_required_metadata_is_not_matching_scope(field):
    p, _ = receipt(); c, vs = receipt(())
    p.pop(field)
    assert trend(p, c, vs)['comparison_status'] == 'not-comparable'


def test_matching_supplied_metadata_only_permits_limited_comparison():
    p, _ = receipt(('#a', '#b')); c, vs = receipt(('#a', '#c'))
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'limited'
    assert out['comparison_precision'] == 'target-level'
    assert len(out['not_observed_findings']) == 1
    assert len(out['persisting_findings']) == 1
    assert len(out['introduced_findings']) == 1
    assert all('source' in x for x in out['persisting_findings'])
    assert out['warnings']  # same URL cannot authenticate browser state
    assert 'remediated_count' not in out and 'fixed_rules' not in out
    assert 'improved' not in out and 'regressed' not in out


def test_empty_valid_receipt_retains_target_precision():
    p, _ = receipt(); c, vs = receipt(())
    out = trend(p, c, vs)
    assert _detect_precision(c) == 'target-level'
    assert out['not_observed_count'] == 1


@pytest.mark.parametrize('change', ['version', 'missing_version', 'fingerprint', 'mixed', 'target', 'source'])
def test_bad_target_identity_downgrades_to_rules(change):
    p, _ = receipt(); c, vs = receipt(('#b',))
    if change == 'version': p['finding_fingerprint_version'] = '2'
    elif change == 'missing_version': p.pop('finding_fingerprint_version')
    elif change == 'fingerprint': p['violations'][0]['finding_fingerprint'] = 'forged'
    elif change == 'mixed': p['violations'].append(None)
    else: p['violations'][0].pop(change)
    out = trend(p, c, vs)
    assert out['comparison_precision'] == 'rule-level'
    assert 'not_observed_findings' not in out
    assert out['warnings']


def test_current_receipt_is_authoritative_not_unrelated_objects():
    p, _ = receipt(); c, _ = receipt()
    _, unrelated = receipt(('#other',))
    out = trend(p, c, unrelated)
    assert out['persisting_count'] == 1 and out['not_observed_count'] == 0


def test_source_aware_history_identity():
    p, _ = receipt(); c, _ = receipt(source='manual', date='2026-02-01')
    rec = build_due_diligence([p, c])
    assert rec['not_observed_count'] == 1
    assert rec['persisting_count'] == 0
    assert rec['introduced_count'] == 1
    assert rec['introduced'][0]['source'] == 'manual'


def test_all_history_links_checked_not_just_endpoints():
    p, _ = receipt(date='2026-01-01'); m, _ = receipt(date='2026-02-01'); c, _ = receipt(date='2026-03-01')
    m['url'] = 'https://example.test/other'
    rec = build_due_diligence([p, m, c])
    assert rec['comparison_status'] == 'not-comparable'
    assert rec['blocking_delta'] is None
    assert len(rec['timeline']) == 3


def test_history_weakest_precision_not_just_endpoints():
    p, _ = receipt(date='2026-01-01'); m, _ = receipt(date='2026-02-01'); c, _ = receipt(date='2026-03-01')
    m.pop('violations'); m.pop('finding_fingerprint_version'); m['schema_version'] = '1.1'
    rec = build_due_diligence([p, m, c])
    assert rec['comparison_precision'] == 'rule-level'
    assert rec['not_observed_count'] is None


def test_aggregate_only_has_no_rule_classifications():
    p, _ = receipt(); c, vs = receipt()
    p.pop('violations'); p.pop('rule_ids')
    out = trend(p, c, vs)
    assert out['comparison_precision'] == 'aggregate-only'
    assert out['persisting_rules'] == [] and out['new_rules'] == []
    assert out['delta_total_violations'] == 0


@pytest.mark.parametrize('bad', [None, [], 'bad json', '[]', 42])
def test_malformed_receipts_do_not_crash_or_infer(bad):
    c, vs = receipt()
    out = trend(bad, c, vs)
    assert out['comparison_status'] == 'not-comparable'
    assert out['delta_total_violations'] is None


def test_rendered_record_does_not_claim_knowledge_remediation_or_attestation():
    p, _ = receipt(); c, _ = receipt((), date='2026-02-01')
    rec = build_due_diligence([p, c]); md = render_due_diligence_md(rec)
    assert 'knowledge_established' not in rec and 'remediated_count' not in rec
    assert 'Knowledge established' not in md and 'Actions evidenced' not in md
    assert 'Each audit in this record is covered' not in md
    assert 'not independently' in md and 'supplied' in md
    assert 'Not observed' in md


def test_no_mutation_and_string_current_receipt_supported():
    p, _ = receipt(); c, vs = receipt()
    old = copy.deepcopy([p, c])
    assert trend(json.dumps(p), json.dumps(c), vs)['persisting_count'] == 1
    build_due_diligence([p, c])
    assert [p, c] == old


@pytest.mark.parametrize('prior_value,current_value', [
    (None, []), ([], [{'id': 'label', 'target': '#a'}]),
    ([{'id': 'label', 'target': '#a'}], [{'id': 'label', 'target': '#b'}]),
    ([], 'bad'), ([], None),
])
def test_pending_coverage_mismatch_suppresses_differences(prior_value, current_value):
    p, _ = receipt(); c, vs = receipt(())
    if prior_value is not None: p['pending_checks'] = prior_value
    else: p.pop('pending_checks', None)
    c['pending_checks'] = current_value
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'not-comparable'
    assert out['delta_total_violations'] is None
    assert 'not_observed_findings' not in out
    rec = build_due_diligence([p, c])
    assert rec['not_observed_count'] is None


def test_absent_legacy_pending_is_explicitly_unknown_not_clean():
    p, _ = receipt(); c, vs = receipt()
    p.pop('pending_checks', None); c.pop('pending_checks', None)
    out = trend(p, c, vs)
    assert any('pending' in w.lower() and 'unknown' in w.lower() for w in out['warnings'])


def test_matching_unresolved_pending_is_not_a_pass_or_clean_claim():
    p, _ = receipt(); c, vs = receipt()
    p['pending_checks'] = c['pending_checks'] = [{'id': 'label', 'target': '#a'}]
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'limited'
    assert any('pending' in w.lower() and 'unresolved' in w.lower() for w in out['warnings'])


@pytest.mark.parametrize('bad', [True, -1, '2', [], {}])
def test_invalid_summary_counts_are_not_coerced(bad):
    p, _ = receipt(); c, vs = receipt()
    p['summary']['total_violations'] = bad
    p['summary']['serious'] = bad
    out = trend(p, c, vs)
    assert out['delta_total_violations'] is None
    rec = build_due_diligence([p, c])
    assert rec['blocking_delta'] is None
    assert 'n/a' in render_due_diligence_md(rec)


@pytest.mark.parametrize('bad', [[5], [{}], ['x']])
def test_matching_malformed_pending_is_not_compatible_coverage(bad):
    p, _ = receipt(); c, vs = receipt()
    p['pending_checks'] = c['pending_checks'] = bad
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'not-comparable'


def test_rule_level_schema_transition_is_limited_not_rejected():
    p, _ = receipt(); c, vs = receipt(('#b',))
    p['schema_version'] = '1.1'; p.pop('finding_fingerprint_version'); p.pop('violations')
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'limited'
    assert out['comparison_precision'] == 'rule-level'
    assert out['persisting_rules'] == ['label']
    assert 'not_observed_findings' not in out


def test_matching_explicit_scope_is_still_not_authenticated():
    p, _ = receipt(); c, vs = receipt()
    for r in (p, c):
        r.update(scope={'routes': ['/login']}, state='signed-out', viewport={'width': 800})
    out = trend(p, c, vs)
    assert out['comparison_status'] == 'limited'
    assert any('does not authenticate' in w for w in out['warnings'])


def test_supplied_history_labels_cannot_inject_markdown_approval():
    p, _ = receipt(('**APPROVED**|<script>\n# header',)); c = copy.deepcopy(p)
    rec = build_due_diligence([p, c]); md = render_due_diligence_md(rec)
    assert '**APPROVED**' not in md
    assert '\\*\\*APPROVED\\*\\*' in md
    assert '<script>' not in md
    assert '\n# header' not in md


def test_breaking_trend_schema_is_distinct_from_receipt_and_history_schemas():
    p, _ = receipt(); c, vs = receipt()
    assert p['schema_version'] == c['schema_version'] == '1.2'
    out = trend(p, c, vs)
    assert out['schema_version'] == '1.3'
    assert build_due_diligence([p, c])['schema_version'] == '1.1'
    for removed in ('remediated_findings', 'remediated_count', 'fixed_rules'):
        assert removed not in out
