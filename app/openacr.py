"""OpenACR-compatible YAML exporter for AccessDoc (GSA OpenACR 0.1.0 schema).

SECURITY: all user-controlled values are emitted through _yq(), which produces
a safe YAML double-quoted scalar (escapes backslash/quote, strips control chars
and newlines). This prevents YAML-injection via client_name, url, etc.
"""
from __future__ import annotations
import datetime
from .models import VERSION
from .wcag_levels import chapter_for, WCAG_LEVELS

EN_301_549_MAP = {
    "1.1.1": "9.1.1.1", "1.2.1": "9.1.2.1", "1.2.2": "9.1.2.2",
    "1.3.1": "9.1.3.1", "1.3.2": "9.1.3.2", "1.3.4": "9.1.3.4", "1.3.5": "9.1.3.5",
    "1.4.1": "9.1.4.1", "1.4.2": "9.1.4.2", "1.4.3": "9.1.4.3", "1.4.4": "9.1.4.4",
    "1.4.6": "9.1.4.6", "1.4.12": "9.1.4.12",
    "2.1.1": "9.2.1.1", "2.1.2": "9.2.1.2", "2.1.4": "9.2.1.4",
    "2.2.1": "9.2.2.1", "2.2.2": "9.2.2.2",
    "2.4.1": "9.2.4.1", "2.4.2": "9.2.4.2", "2.4.3": "9.2.4.3",
    "2.4.4": "9.2.4.4", "2.4.6": "9.2.4.6", "2.4.9": "9.2.4.9",
    "2.5.1": "9.2.5.1", "2.5.3": "9.2.5.3", "2.5.5": "9.2.5.5", "2.5.8": "9.2.5.8",
    "3.1.1": "9.3.1.1", "3.1.2": "9.3.1.2",
    "3.2.2": "9.3.2.2",
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


def generate_openacr_yaml(
    summary,
    violations,
    client_name: str = "Client",
    audit_date: str = "",
    author_name: str | None = None,
    author_email: str | None = None,
    author_company_name: str | None = None,
):
    """Generate GSA OpenACR 0.1.0-conformant YAML using exact WCAG levels."""
    today = audit_date or datetime.date.today().isoformat()
    auth_name = author_name or client_name
    auth_comp = author_company_name or client_name
    clean_email_domain = "".join(c for c in client_name.lower() if c.isalnum()) or "client"
    auth_mail = author_email or f"accessibility@{clean_email_domain}.invalid"

    failing_scs = {}
    for v in violations:
        for sc in v.wcag_scs:
            failing_scs.setdefault(sc, []).append(v.id)

    chapters_dict = {
        "success_criteria_level_a": [],
        "success_criteria_level_aa": [],
        "success_criteria_level_aaa": [],
    }
    unmapped_scs = []

    for sc, rules in sorted(failing_scs.items()):
        rule_str = ", ".join(rules[:5])
        ch = chapter_for(sc)
        if ch in chapters_dict:
            crit_block = (
                f"      - num: \"{_yq(sc)}\"\n"
                f"        components:\n"
                f"          - name: \"web\"\n"
                f"            adherence:\n"
                f"              level: \"does-not-support\"\n"
                f"              notes: \"axe-core rules: {_yq(rule_str)}\"\n"
            )
            chapters_dict[ch].append(crit_block)
        else:
            unmapped_scs.append(f"{sc} (rules: {rule_str})")

    engine = _yq(summary.engine_version or "axe-core")
    disclaimer_note = "Criteria with zero automated failures are marked disabled rather than 'Supports': absence of automated findings is not evidence of conformance."

    chapters_lines = ["chapters:\n"]

    # success_criteria_level_a
    chapters_lines.append("  success_criteria_level_a:\n")
    if chapters_dict["success_criteria_level_a"]:
        chapters_lines.append("    criteria:\n")
        chapters_lines.extend(chapters_dict["success_criteria_level_a"])
    else:
        chapters_lines.append(f"    notes: \"{disclaimer_note}\"\n")
        chapters_lines.append("    disabled: true\n")

    # success_criteria_level_aa
    chapters_lines.append("  success_criteria_level_aa:\n")
    if chapters_dict["success_criteria_level_aa"]:
        chapters_lines.append("    criteria:\n")
        chapters_lines.extend(chapters_dict["success_criteria_level_aa"])
    else:
        chapters_lines.append(f"    notes: \"{disclaimer_note}\"\n")
        chapters_lines.append("    disabled: true\n")

    # success_criteria_level_aaa
    chapters_lines.append("  success_criteria_level_aaa:\n")
    if chapters_dict["success_criteria_level_aaa"]:
        chapters_lines.append("    criteria:\n")
        chapters_lines.extend(chapters_dict["success_criteria_level_aaa"])
    else:
        chapters_lines.append(f"    notes: \"{disclaimer_note}\"\n")
        chapters_lines.append("    disabled: true\n")

    # functional_performance_criteria (Section 508 Chapter 5)
    chapters_lines.append("  functional_performance_criteria:\n")
    chapters_lines.append(f"    notes: \"{disclaimer_note}\"\n")
    chapters_lines.append("    disabled: true\n")

    # hardware & software chapters marked disabled for web assessment
    chapters_lines.append("  hardware:\n    disabled: true\n")
    chapters_lines.append("  software:\n    disabled: true\n")

    # support_documentation_and_services (Chapter 12)
    chapters_lines.append("  support_documentation_and_services:\n")
    chapters_lines.append(f"    notes: \"{disclaimer_note}\"\n")
    chapters_lines.append("    disabled: true\n")

    chapters_block = "".join(chapters_lines)

    notes_text = (
        "  Automated scan only. axe-core detects ~30-57% of WCAG issues.\n"
        "  Manual testing required for legal compliance.\n"
    )
    if unmapped_scs:
        notes_text += f"  Unmapped criteria (not in standard WCAG levels): {', '.join(unmapped_scs)}\n"

    return (
        f"---\n"
        f"title: \"[{_yq(client_name)}] Accessibility Conformance Report\"\n"
        f"product:\n"
        f"  name: \"{_yq(client_name)}\"\n"
        f"  version: \"audited {_yq(today)}\"\n"
        f"  description: \"Web application accessibility assessment generated by AccessDoc v{_yq(VERSION)}\"\n"
        f"author:\n"
        f"  name: \"{_yq(auth_name)}\"\n"
        f"  company_name: \"{_yq(auth_comp)}\"\n"
        f"  email: \"{_yq(auth_mail)}\"\n"
        f"  website: \"https://github.com/Kartik24Hulmukh/AccessDoc\"\n"
        f"report_date: \"{_yq(today)}\"\n"
        f"evaluation_methods_used: \"Automated (axe-core {engine})\"\n"
        f"notes: |\n"
        f"{notes_text}"
        f"legal_disclaimer: \"Automated scan evidence only. AccessDoc does not provide legal advice or guarantee conformance.\"\n"
        f"{chapters_block}"
    )
