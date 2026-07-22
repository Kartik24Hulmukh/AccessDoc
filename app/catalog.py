"""WCAG 2.2 rule catalog - axe-core rule IDs mapped to success criteria."""

CATALOG_VERSION = "wcag-2.2-accessdoc-2026-07"
AXE_CORE_VERIFIED_VERSION = "4.11.2"
COVERAGE_NOTE = (
    f"Rule catalog {CATALOG_VERSION} covers axe-core {AXE_CORE_VERIFIED_VERSION}. "
    "Automated scanning detects 30-57 % of WCAG issues; manual review is required."
)

RULE_SC_MAP = {
    # Perceivable
    "image-alt":                   ["1.1.1"],
    "input-image-alt":             ["1.1.1"],
    "area-alt":                    ["1.1.1"],
    "object-alt":                  ["1.1.1"],
    "svg-img-alt":                 ["1.1.1"],
    "role-img-alt":                ["1.1.1"],
    "video-caption":                ["1.2.2"],
    "audio-caption":                ["1.2.1"],
    "td-headers-attr":             ["1.3.1"],
    "th-has-data-cells":           ["1.3.1"],
    "table-duplicate-name":        ["1.3.1"],
    "definition-list":             ["1.3.1"],
    "dlitem":                      ["1.3.1"],
    "list":                        ["1.3.1"],
    "listitem":                    ["1.3.1"],
    "landmark-unique":             ["1.3.1"],
    "orientation":                 ["1.3.4"],
    "autocomplete-valid":          ["1.3.5"],
    "color-contrast":              ["1.4.3"],
    "color-contrast-enhanced":     ["1.4.6"],
    "text-spacing":                ["1.4.12"],
    "meta-viewport":               ["1.4.4"],
    "link-in-text-block":          ["1.4.1", "2.4.4"],
    # Operable
    "accesskeys":                  ["2.1.1"],
    "tabindex":                    ["2.1.1", "2.4.3"],
    "scrollable-region-focusable": ["2.1.1"],
    "focus-trap":                  ["2.1.2"],
    "bypass":                      ["2.4.1"],
    "page-has-heading-one":        ["2.4.6"],
    "heading-order":               ["2.4.6"],
    "document-title":              ["2.4.2"],
    "link-name":                   ["2.4.4"],
    "target-size":                 ["2.5.5", "2.5.8"],
    "meta-refresh":                ["2.2.1"],
    "blink":                       ["2.2.2"],
    "marquee":                     ["2.2.2"],
    # Understandable
    "html-has-lang":               ["3.1.1"],
    "html-lang-valid":             ["3.1.1"],
    "html-xml-lang-mismatch":      ["3.1.1"],
    "valid-lang":                  ["3.1.2"],
    "label":                       ["3.3.2"],
    "label-content-name-mismatch": ["2.5.3"],
    "select-name":                 ["3.3.2", "4.1.2"],
    "form-field-multiple-labels":  ["3.3.2"],
    "error-message":               ["3.3.1"],
    # Robust
    "duplicate-id":                ["4.1.1"],
    "duplicate-id-active":         ["4.1.1"],
    "duplicate-id-aria":           ["4.1.1"],
    "aria-allowed-attr":           ["4.1.2"],
    "aria-allowed-role":           ["4.1.2"],
    "aria-command-name":           ["4.1.2"],
    "aria-hidden-body":            ["4.1.2"],
    "aria-hidden-focus":           ["1.3.1", "4.1.2"],
    "aria-input-field-name":       ["4.1.2"],
    "aria-required-attr":          ["4.1.2"],
    "aria-required-children":      ["4.1.2"],
    "aria-required-parent":        ["4.1.2"],
    "aria-roles":                  ["4.1.2"],
    "aria-toggle-field-name":      ["4.1.2"],
    "aria-valid-attr":             ["4.1.2"],
    "aria-valid-attr-value":       ["4.1.2"],
    "button-name":                 ["4.1.2"],
    "frame-title":                 ["4.1.2"],
    "input-button-name":           ["4.1.2"],
    "empty-heading":               ["2.4.6"],
    "identical-links-same-purpose":["2.4.9"],
}


def get_wcag_scs(rule_id):
    return RULE_SC_MAP.get(rule_id, [])


def catalog_summary():
    all_scs = set()
    for scs in RULE_SC_MAP.values():
        all_scs.update(scs)
    return {
        "rule_count": len(RULE_SC_MAP),
        "sc_count": len(all_scs),
        "catalog_version": CATALOG_VERSION,
        "axe_core_verified_version": AXE_CORE_VERIFIED_VERSION,
        "coverage_note": COVERAGE_NOTE,
    }
