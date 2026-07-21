from __future__ import annotations

CATALOG_VERSION = "wcag-2.2-accessdoc-2026-01"
BASE = "https://www.w3.org/TR/WCAG22/#"

# Curated seed catalog. Unknown rules never receive guessed WCAG mappings.
RULES = {
 "image-alt": dict(sc="1.1.1", title="Non-text Content", level="A", slug="non-text-content", impact="People using screen readers may miss the purpose or information conveyed by images.", remediation="Provide concise alternative text that communicates the image purpose. Use an empty alt attribute for decorative images and test in context.", effort="S"),
 "button-name": dict(sc="4.1.2", title="Name, Role, Value", level="A", slug="name-role-value", impact="People using assistive technology may be unable to identify or operate unnamed buttons.", remediation="Give every button an accessible name using visible text, aria-label, or aria-labelledby. Keep the programmatic name aligned with the visible label.", effort="XS"),
 "link-name": dict(sc="2.4.4", title="Link Purpose (In Context)", level="A", slug="link-purpose-in-context", impact="Screen-reader users may not understand where a link goes or what action it performs.", remediation="Provide descriptive link text or an accessible name that identifies the link purpose in context.", effort="XS"),
 "color-contrast": dict(sc="1.4.3", title="Contrast (Minimum)", level="AA", slug="contrast-minimum", impact="People with low vision or color-vision differences may be unable to read the content.", remediation="Adjust foreground and background colors to meet at least 4.5:1 for normal text or 3:1 for large text. Retest all states.", effort="S"),
 "html-has-lang": dict(sc="3.1.1", title="Language of Page", level="A", slug="language-of-page", impact="Screen readers may pronounce content incorrectly when the page language is missing.", remediation="Set a valid lang attribute on the root html element, such as lang=\"en\".", effort="XS"),
 "document-title": dict(sc="2.4.2", title="Page Titled", level="A", slug="page-titled", impact="Users may have difficulty identifying the page or distinguishing browser tabs.", remediation="Provide a concise, unique title element describing the page topic or purpose.", effort="XS"),
 "label": dict(sc="3.3.2", title="Labels or Instructions", level="A", slug="labels-or-instructions", impact="Users may not know what information a form control requires.", remediation="Associate a visible, descriptive label with each form control and provide instructions where format or constraints are not obvious.", effort="S"),
 "input-button-name": dict(sc="4.1.2", title="Name, Role, Value", level="A", slug="name-role-value", impact="Assistive technology may announce an unlabeled form button without a usable purpose.", remediation="Add a meaningful value or accessible name to input buttons and verify it is announced correctly.", effort="XS"),
 "heading-order": dict(sc="1.3.1", title="Info and Relationships", level="A", slug="info-and-relationships", impact="A confusing heading hierarchy can make content difficult to navigate and understand.", remediation="Use headings to represent the page outline without skipping levels for visual styling. Confirm the hierarchy reflects content relationships.", effort="S"),
 "landmark-one-main": dict(sc="1.3.1", title="Info and Relationships", level="A", slug="info-and-relationships", impact="People navigating by landmarks may have difficulty locating the main content.", remediation="Provide one main landmark for the primary page content and avoid duplicate unlabelled main regions.", effort="XS"),
 "aria-required-attr": dict(sc="4.1.2", title="Name, Role, Value", level="A", slug="name-role-value", impact="Custom controls may expose incomplete semantics and fail for assistive technology users.", remediation="Add all ARIA attributes required by the role and prefer native HTML controls where possible.", effort="S"),
 "duplicate-id-aria": dict(sc="4.1.2", title="Name, Role, Value", level="A", slug="name-role-value", impact="Duplicate referenced IDs can cause labels and descriptions to resolve to the wrong element.", remediation="Ensure IDs used by ARIA relationships are unique within the document.", effort="S"),
 "focus-order-semantics": dict(sc="2.4.3", title="Focus Order", level="A", slug="focus-order", impact="Keyboard and screen-reader users may encounter controls in an order that does not preserve meaning or operability.", remediation="Ensure focus follows a logical task and reading sequence. Avoid positive tabindex values and test dynamic interfaces manually.", effort="M"),
 "target-size": dict(sc="2.5.8", title="Target Size (Minimum)", level="AA", slug="target-size-minimum", impact="People with limited dexterity may have difficulty activating small controls.", remediation="Provide pointer targets at least 24 by 24 CSS pixels or satisfy a documented exception, with adequate spacing.", effort="S"),
}

IMPACT_TO_SEVERITY = {"critical":"critical", "serious":"high", "moderate":"medium", "minor":"low", None:"needs-review", "null":"needs-review"}


def lookup(rule_id: str):
    row = RULES.get(str(rule_id or "").strip())
    if not row:
        return dict(sc="Unmapped", title="Manual review required", level="N/A", impact="The source rule is not yet in the reviewed AccessDoc mapping catalog.", remediation="Review the original tool guidance, map applicable WCAG 2.2 criteria explicitly, and confirm the finding before client delivery.", effort="Unknown", normative_url="https://www.w3.org/TR/WCAG22/")
    return {**row, "normative_url": BASE + row["slug"]}
