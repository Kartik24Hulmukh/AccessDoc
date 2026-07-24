"""Provenance-labeled plain-language enrichment.

The deterministic core NEVER invents remediation. Explanations come from a
curated static KB keyed by WCAG SC. Any generative field is labeled
PROVENANCE_AI. Research: LLM repair F1 ~0.65, <26% full-fix (arXiv 2605.27716).
"""
from .models import VERSION

PROVENANCE_DETERMINISTIC = "deterministic-kb"
PROVENANCE_AI = "AI-ASSISTED - verify"

_SC_KB = {
    "1.1.1": {"title": "Non-text Content",
              "plain": "Images and non-text content need a text alternative so screen-reader users know what they convey.",
              "fix": "Add meaningful alt text; use alt=\"\" only for decorative images."},
    "1.2.1": {"title": "Audio-only / Video-only",
              "plain": "Pre-recorded audio-only or video-only content needs an alternative.",
              "fix": "Provide a transcript (audio) or an audio description / transcript (video)."},
    "1.2.2": {"title": "Captions (Prerecorded)",
              "plain": "Videos with sound need synchronized captions.",
              "fix": "Add accurate captions for all speech and meaningful sound."},
    "1.3.1": {"title": "Info and Relationships",
              "plain": "Structure conveyed visually must also be available programmatically.",
              "fix": "Use semantic HTML (headings, lists, table headers, labels) not just styling."},
    "1.4.1": {"title": "Use of Color",
              "plain": "Color must not be the only way information is conveyed.",
              "fix": "Add text labels, underlines, or icons in addition to color."},
    "1.4.3": {"title": "Contrast (Minimum)",
              "plain": "Text must have enough contrast against its background to be readable.",
              "fix": "Ensure >= 4.5:1 for normal text, 3:1 for large text."},
    "1.4.4": {"title": "Resize Text",
              "plain": "Text must remain usable when zoomed to 200%.",
              "fix": "Use relative units and a responsive layout; set a proper viewport."},
    "2.1.1": {"title": "Keyboard",
              "plain": "All functionality must work with a keyboard alone.",
              "fix": "Ensure interactive elements are focusable and operable without a mouse."},
    "2.4.1": {"title": "Bypass Blocks",
              "plain": "Users need a way to skip repeated blocks.",
              "fix": "Add a skip link and proper landmarks."},
    "2.4.2": {"title": "Page Titled",
              "plain": "Each page needs a descriptive title.",
              "fix": "Set a unique, meaningful <title>."},
    "2.4.4": {"title": "Link Purpose",
              "plain": "Link text should make sense out of context.",
              "fix": "Use descriptive link text instead of 'click here'."},
    "2.4.6": {"title": "Headings and Labels",
              "plain": "Headings and labels must be descriptive.",
              "fix": "Use a logical heading hierarchy; avoid empty headings."},
    "3.1.1": {"title": "Language of Page",
              "plain": "The page language must be declared.",
              "fix": "Set a valid lang attribute on <html>."},
    "3.3.2": {"title": "Labels or Instructions",
              "plain": "Form fields need labels or instructions.",
              "fix": "Associate a visible <label> with each control."},
    "4.1.1": {"title": "Parsing",
              "plain": "Markup must be well-formed (no duplicate IDs).",
              "fix": "Ensure unique IDs and valid nesting."},
    "4.1.2": {"title": "Name, Role, Value",
              "plain": "UI components must expose name, role, and value to AT.",
              "fix": "Use native elements or correct ARIA roles/attributes."},
}


def explain_sc(sc):
    return _SC_KB.get(sc)


def enrich_violations(violations):
    items = []
    seen = set()
    for v in violations:
        if v.id in seen:
            continue
        seen.add(v.id)
        explanations = []
        for sc in v.wcag_scs:
            kb = _SC_KB.get(sc)
            if kb:
                explanations.append({
                    "wcag_sc": sc,
                    "title": kb["title"],
                    "plain_language": kb["plain"],
                    "how_to_fix": kb["fix"],
                    "provenance": PROVENANCE_DETERMINISTIC,
                })
        items.append({
            "rule_id": v.id,
            "impact": v.impact,
            "source": v.source,
            "explanations": explanations,
        })
    return {
        "enricher_version": VERSION,
        "knowledge_base": "accessdoc-wcag-kb",
        "note": "Explanations are deterministic. Any AI-assisted text is labeled '%s'." % PROVENANCE_AI,
        "items": items,
    }
