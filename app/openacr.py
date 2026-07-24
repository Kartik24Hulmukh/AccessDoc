"""OpenACR-compatible YAML exporter for AccessDoc.

SECURITY: all user-controlled values are emitted through _yq(), which produces
a safe YAML double-quoted scalar (escapes backslash/quote, strips control chars
and newlines). This prevents YAML-injection via client_name, url, etc.
"""
import datetime
from .models import VERSION

EN_301_549_MAP = {
    "1.1.1": "9.1.1.1", "1.2.1": "9.1.2.1", "1.2.2": "9.1.2.2",
    "1.3.1": "9.1.3.1", "1.3.4": "9.1.3.4", "1.3.5": "9.1.3.5",
    "1.4.1": "9.1.4.1", "1.4.3": "9.1.4.3", "1.4.4": "9.1.4.4",
    "1.4.6": "9.1.4.6", "1.4.12": "9.1.4.12",
    "2.1.1": "9.2.1.1", "2.1.2": "9.2.1.2",
    "2.2.1": "9.2.2.1", "2.2.2": "9.2.2.2",
    "2.4.1": "9.2.4.1", "2.4.2": "9.2.4.2", "2.4.3": "9.2.4.3",
    "2.4.4": "9.2.4.4", "2.4.6": "9.2.4.6", "2.4.9": "9.2.4.9",
    "2.5.3": "9.2.5.3", "2.5.5": "9.2.5.5", "2.5.8": "9.2.5.8",
    "3.1.1": "9.3.1.1", "3.1.2": "9.3.1.2",
    "3.3.1": "9.3.3.1", "3.3.2": "9.3.3.2",
    "4.1.1": "9.4.1.1", "4.1.2": "9.4.1.2",
}


def _yq(value):
    """Return a safe YAML double-quoted scalar body (without the quotes).

    Escapes backslash and double-quote and removes control characters and
    newlines so a hostile value cannot break out of its quoted scalar.
    """
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = "".join(ch for ch in s if ord(ch) >= 0x20)
    return s


def generate_openacr_yaml(summary, violations, client_name="Client", audit_date=""):
    today = audit_date or datetime.date.today().isoformat()
    failing_scs = {}
    for v in violations:
        for sc in v.wcag_scs:
            failing_scs.setdefault(sc, []).append(v.id)

    criteria_lines = []
    for sc, rules in sorted(failing_scs.items()):
        en_clause = EN_301_549_MAP.get(sc, f"9.{sc}")
        rule_str = ", ".join(rules[:5])
        criteria_lines.append(
            f"  - criterion_number: \"{_yq(sc)}\"\n"
            f"    en_301_549_clause: \"{_yq(en_clause)}\"\n"
            f"    level: \"AA\"\n"
            f"    components:\n"
            f"      - name: web\n"
            f"        adherence: \"Does Not Support\"\n"
            f"        remarks: \"axe-core rules: {_yq(rule_str)}\"\n"
        )

    criteria_block = "".join(criteria_lines) or \
        "  - criterion_number: \"N/A\"\n    components:\n      - name: web\n        adherence: \"Supports\"\n"

    return (
        f"---\nschema_version: \"0.1\"\n"
        f"product:\n  name: \"{_yq(client_name)}\"\n  version: \"audited {_yq(today)}\"\n"
        f"report_date: \"{_yq(today)}\"\n"
        f"generator:\n  name: AccessDoc\n  version: \"{_yq(VERSION)}\"\n"
        f"evaluation_methods_used: \"Automated (axe-core {_yq(summary.engine_version or 'unknown')})\"\n"
        f"chapters:\n  - id: \"chapter-9\"\n"
        f"    label: \"EN 301 549 Chapter 9 - Web\"\n"
        f"    criteria:\n{criteria_block}"
        f"notes: |\n"
        f"  Automated scan only. axe-core detects ~30-57% of WCAG issues.\n"
        f"  Manual testing required for legal compliance.\n"
    )
