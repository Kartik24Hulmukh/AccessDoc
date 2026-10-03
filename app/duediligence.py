"""A deterministic summary of supplied receipt history, not a diligence proof.

Receipt dates and observations are caller-supplied. This module does not verify
signatures, chronology, source truth, reviewer approval, knowledge or action.
"""
from .timeseries import _comparison_context, _count, _summary, _finding_map

DUE_DILIGENCE_SCHEMA_VERSION = '1.1'
_IMPACTS = ('critical', 'serious', 'moderate', 'minor')


def _counts(receipt):
    summary = _summary(receipt)
    return {key: _count(summary.get(key)) for key in _IMPACTS}


def _total(counts):
    return sum(counts.values()) if all(v is not None for v in counts.values()) else None


def _date_of(receipt):
    value = receipt.get('audit_date') or receipt.get('date')
    return value if isinstance(value, str) else ''


def _blocking(counts):
    a, b = counts['critical'], counts['serious']
    return a + b if a is not None and b is not None else None


def build_due_diligence(receipts):
    """Summarize supplied dates/counts, comparing only compatible history links."""
    if not receipts:
        raise ValueError('at least one receipt is required to build a due-diligence record')
    chain = [r for r in receipts if isinstance(r, dict)]
    if not chain:
        raise ValueError('no valid receipt dicts supplied')
    chain = sorted(chain, key=_date_of)
    timeline = []
    for r in chain:
        counts = _counts(r)
        timeline.append({
            'audit_date': _date_of(r), 'counts': counts, 'total': _total(counts),
            'accessdoc_version': r.get('accessdoc_version', ''),
        })
    # Do not make endpoint differences look meaningful if intermediate evidence
    # changes route/tool/scope or has weaker identity precision.
    links = list(zip(chain, chain[1:])) or [(chain[0], chain[0])]
    contexts = [_comparison_context(a, b) for a, b in links]
    compatible = all(c[0] for c in contexts)
    order = {'aggregate-only': 1, 'rule-level': 2, 'target-level': 3}
    precision = min((c[1] for c in contexts), key=order.get)
    warnings = list(dict.fromkeys(w for c in contexts for w in c[4]))
    if len(chain) != len(receipts):
        compatible = False
        warnings.append('Invalid supplied history entries; comparison suppressed, valid rows retained.')
    warnings.append('Dates are caller-supplied, not independently timestamped. '
                    'Timeline order is not a verified receipt chain.')
    first_counts, last_counts = _counts(chain[0]), _counts(chain[-1])
    before, after = _blocking(first_counts), _blocking(last_counts)
    delta = after - before if compatible and before is not None and after is not None else None
    differences = {'not_observed': [], 'persisting': [], 'introduced': []}
    finding_comparison = compatible and precision == 'target-level'
    if finding_comparison:
        first, last = _finding_map(chain[0]), _finding_map(chain[-1])
        differences = {
            'not_observed': [first[k] for k in sorted(set(first) - set(last))],
            'persisting': [last[k] for k in sorted(set(first) & set(last))],
            'introduced': [last[k] for k in sorted(set(last) - set(first))],
        }
    return {
        'schema_version': DUE_DILIGENCE_SCHEMA_VERSION,
        'audits_in_record': len(chain),
        'period_start': _date_of(chain[0]), 'period_end': _date_of(chain[-1]),
        'timeline': timeline,
        'comparison_status': 'limited' if compatible else 'not-comparable',
        'comparison_basis': 'supplied-metadata-only', 'comparison_precision': precision,
        'warnings': warnings,
        **differences,
        **{key + '_count': len(value) if finding_comparison else None
           for key, value in differences.items()},
        'blocking_before': before, 'blocking_after': after, 'blocking_delta': delta,
        'trend': ('not-comparable' if not compatible else 'unavailable' if delta is None
                  else 'decreased' if delta < 0 else 'increased' if delta > 0 else 'unchanged'),
    }


def render_due_diligence_md(record):
    """Render neutral supplied observations, without proof or action claims."""
    def show(value):
        return 'n/a' if value is None or value == '' else str(value)

    def text(value):
        # Supplied labels stay literal, including pipe/newline/backtick input.
        value = str(value).replace('\\', '\\\\').replace('\r', ' ').replace('\n', ' ')
        for char in '|`*_[]#~':
            value = value.replace(char, '\\' + char)
        return value.replace('<', '&lt;').replace('>', '&gt;')

    lines = []
    a = lines.append
    a('# Due-Diligence Record — Supplied Evidence Summary')
    a('')
    a('> **What this is.** A summary assembled from supplied receipts and dates.')
    a('> Matching supplied metadata permits only limited observation differences; '
      'it does not authenticate browser state, scope, source truth or completeness.')
    a('> **What this is NOT.** It is not a conformance claim, not a legal opinion, '
      'and not proof of knowledge, remediation, reasonable steps or reviewer approval.')
    a('> Automated scanning detects only a subset of WCAG issues (~30-57%); '
      'absence of findings is not evidence of conformance.')
    a('')
    a(f"- Supplied receipts in record: **{record['audits_in_record']}**")
    a(f"- Supplied period: **{text(show(record['period_start']))}** to **{text(show(record['period_end']))}**")
    a(f"- Comparison: **{record['comparison_status']}** ({record['comparison_precision']})")
    a(f"- Change in supplied critical + serious counts: **{record['trend']}** "
      f"({show(record['blocking_before'])} -> {show(record['blocking_after'])}); "
      f"delta: {show(record['blocking_delta'])}")
    a('')
    a('## Timeline (supplied dates, not verified chronology)')
    a('')
    a('| Supplied audit date | Critical | Serious | Moderate | Minor | Severity subtotal |')
    a('|---|---|---|---|---|---|')
    for t in record['timeline']:
        counts = t['counts']
        a('| ' + ' | '.join([text(show(t['audit_date']))]
                           + [show(counts[k]) for k in _IMPACTS]
                           + [show(t['total'])]) + ' |')
    a('')
    a('## Supplied observation differences')
    a('')
    a(f"- **Not observed at end** (supplied at start): {show(record['not_observed_count'])}")
    a(f"- **Observed at both endpoints**: {show(record['persisting_count'])}")
    a(f"- **Observed only at end**: {show(record['introduced_count'])}")
    a('')
    a('These are endpoint observations, not evidence of fixes, continuous '
      'persistence or newly caused barriers. n/a means classification was not available.')
    for key, heading in (('persisting', 'Observed at both endpoints'),
                         ('introduced', 'Observed only at end')):
        if record[key]:
            a('')
            a('### ' + heading)
            a('')
            for v in record[key][:50]:
                a(f"- {text(v['id'])} ({text(v.get('impact') or 'unspecified')}) — "
                  f"{text(v['target'])}; supplied source: {text(v['source'])}")
            if len(record[key]) > 50:
                a(f"- {len(record[key]) - 50} additional supplied observations not listed.")
    a('')
    a('## Limitations')
    a('')
    for warning in record['warnings']:
        a('- ' + text(warning))
    a('')
    a('No attestation, signature, manifest or receipt-chain verification is performed '
      'by this summary. It is not an append-only or independently authenticated record.')
    return '\n'.join(lines) + '\n'
