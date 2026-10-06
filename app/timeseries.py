"""Limited observation differences between supplied receipts.

Matching metadata does not authenticate origin, browser state, completeness,
knowledge, remediation, review or legal conformance. Digests identify supplied
bytes; this module does not verify an attestation or a receipt chain.
"""
import hashlib
import json
from .models import VERSION


def _sha256_of_receipt(receipt):
    """Stable digest of supplied receipt data, not verification of its truth."""
    if isinstance(receipt, (bytes, bytearray)):
        return hashlib.sha256(bytes(receipt)).hexdigest()
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return hashlib.sha256(receipt.encode()).hexdigest()
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _as_receipt(receipt):
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return {}
    return receipt if isinstance(receipt, dict) else {}


def _summary(receipt):
    summary = _as_receipt(receipt).get('summary')
    return summary if isinstance(summary, dict) else {}


def _count(value):
    # bool is an int in Python, but is not a supplied count.
    return value if type(value) is int and value >= 0 else None


def _valid_rules(receipt):
    rules = receipt.get('rule_ids')
    return isinstance(rules, list) and all(isinstance(r, str) and r.strip() for r in rules)


def _detect_precision(receipt):
    """Infer usable identity precision, including explicit empty schema-1.2 lists."""
    receipt = _as_receipt(receipt)
    violations = receipt.get('violations')
    if (receipt.get('schema_version') == '1.2'
            and receipt.get('finding_fingerprint_version') == '1'
            and isinstance(violations, list)):
        from .receipt_builder import compute_finding_fingerprint
        valid = all(
            isinstance(v, dict)
            and all(isinstance(v.get(k), str) and v[k].strip() for k in ('id', 'source', 'target'))
            and v.get('finding_fingerprint') == compute_finding_fingerprint(v['id'], v['source'], v['target'])
            for v in violations
        )
        if (valid and _valid_rules(receipt)
                and set(receipt['rule_ids']) == {v['id'] for v in violations}):
            return 'target-level'
    if _valid_rules(receipt):
        return 'rule-level'
    return 'aggregate-only'


def _extract_rule_ids(receipt):
    receipt = _as_receipt(receipt)
    return set(receipt['rule_ids']) if _valid_rules(receipt) else set()


def _finding_map(receipt):
    """Only call after target-level validation; canonical identity includes source."""
    return {v['finding_fingerprint']: {
        'finding_fingerprint': v['finding_fingerprint'], 'id': v['id'],
        'source': v['source'], 'target': v['target'], 'impact': v.get('impact'),
    } for v in receipt['violations']}


def _valid_pending(value):
    # A supplied unresolved check needs an identity, not an inferred outcome.
    return isinstance(value, list) and all(
        isinstance(check, dict)
        and isinstance(check.get('id'), str) and check['id'].strip()
        and isinstance(check.get('target'), str)
        for check in value
    )


def _comparison_context(prior, current):
    """Conservative compatibility of supplied metadata, never authenticated scope."""
    prior, current = _as_receipt(prior), _as_receipt(current)
    warnings = [
        'Comparison uses supplied metadata only. Matching URL/client/tool metadata '
        'does not authenticate browser state, tested scope, origin or completeness. '
        'Absence is not verified remediation; presence does not establish knowledge '
        'or reviewer approval.'
    ]
    compatible = True
    for receipt in (prior, current):
        if receipt.get('schema_version') not in ('1.1', '1.2'):
            warnings.append('Missing or unsupported receipt schema; comparison suppressed.')
            compatible = False
            break
    for key in ('url', 'client_name', 'engine_version', 'catalog_version'):
        a, b = prior.get(key), current.get(key)
        if not (isinstance(a, str) and a.strip() and isinstance(b, str) and b.strip()):
            warnings.append(f'Missing or invalid supplied {key}; comparison suppressed.')
            compatible = False
        elif a != b:
            warnings.append(f'Supplied {key} differs; comparison suppressed.')
            compatible = False
    # These optional fields are checked if present, not invented or authenticated.
    for key in ('axe_core_verified_version', 'scope', 'state', 'viewport',
                'exclusions', 'authentication_context'):
        if key in prior or key in current:
            if (key not in prior or key not in current or prior[key] is None
                    or current[key] is None or type(prior[key]) is not type(current[key])
                    or prior[key] != current[key]):
                warnings.append(f'Supplied {key} differs or is unavailable; comparison suppressed.')
                compatible = False
    if 'pending_checks' not in prior and 'pending_checks' not in current:
        warnings.append('Pending-check coverage is unknown in legacy supplied receipts; '
                        'missing fields are not evidence of a clean or complete scan.')
    elif (not _valid_pending(prior.get('pending_checks'))
          or not _valid_pending(current.get('pending_checks'))
          or prior['pending_checks'] != current['pending_checks']):
        compatible = False
        warnings.append('Supplied pending-check coverage differs or is unknown/invalid; '
                        'comparison suppressed. Missing is not equivalent to empty.')
    elif prior['pending_checks']:
        warnings.append('Matching supplied pending checks remain unresolved, not passes '
                        'or evidence of complete coverage.')
    pp, cp = _detect_precision(prior), _detect_precision(current)
    order = {'aggregate-only': 1, 'rule-level': 2, 'target-level': 3}
    precision = min((pp, cp), key=order.get)
    if pp != cp:
        warnings.append(f'Precision differs ({pp} / {cp}); using {precision}.')
    if precision != 'target-level':
        warnings.append('Target identity unavailable or invalid (schema, fingerprint version, '
                        'source, target or fingerprint); no finding-level classifications.')
    if precision == 'rule-level':
        warnings.append('Rule-level differences do not identify individual targets or source-specific findings.')
    if precision == 'aggregate-only':
        warnings.append('Aggregate-only evidence cannot classify rules or individual findings.')
    return compatible, precision, pp, cp, warnings


def build_trend(prior_receipt, current_receipt, current_violations):
    """Return neutral supplied-observation differences, suppressing incompatible scope.

    current_violations is retained for call compatibility; identity and counts are
    read from the supplied current receipt, not reconstructed from another list.
    """
    prior, current = _as_receipt(prior_receipt), _as_receipt(current_receipt)
    compatible, precision, pp, cp, warnings = _comparison_context(prior, current)
    prior_summary, current_summary = _summary(prior), _summary(current)
    ptotal = _count(prior_summary.get('total_violations'))
    ctotal = _count(current_summary.get('total_violations'))
    delta = ctotal - ptotal if compatible and ptotal is not None and ctotal is not None else None
    new, absent, shared = [], [], []
    if compatible and precision != 'aggregate-only':
        p, c = _extract_rule_ids(prior), _extract_rule_ids(current)
        new, absent, shared = sorted(c - p), sorted(p - c), sorted(p & c)
    trend = {
        'schema_version': '1.3',
        'generator': {'name': 'accessdoc', 'version': VERSION},
        'prev_receipt_sha256': _sha256_of_receipt(prior_receipt),
        'comparison_status': 'limited' if compatible else 'not-comparable',
        'comparison_basis': 'supplied-metadata-only',
        'comparison_precision': precision, 'prior_precision': pp, 'current_precision': cp,
        'prior_summary': prior_summary, 'current_summary': current_summary,
        'delta_total_violations': delta, 'new_rules': new,
        'not_observed_rules': absent, 'persisting_rules': shared,
        'note': 'Differences describe supplied observations only, not verified fixes, '
                'regressions, reasonable steps, awareness or conformance. Digests '
                'identify supplied receipt data; no signature or chain verification is performed.',
        'warnings': warnings,
    }
    if compatible and precision == 'target-level':
        p, c = _finding_map(prior), _finding_map(current)
        for label, keys, entries in (
            ('not_observed', set(p) - set(c), p),
            ('persisting', set(p) & set(c), c),
            ('introduced', set(c) - set(p), c),
        ):
            trend[label + '_findings'] = [entries[k] for k in sorted(keys)]
            trend[label + '_count'] = len(keys)
    return json.dumps(trend, indent=2)


def rule_ids_for_receipt(violations):
    """Embed supplied rule IDs; IDs alone cannot establish target-level precision."""
    return sorted({v.id for v in violations})
