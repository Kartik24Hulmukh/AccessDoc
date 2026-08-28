"""WCAG conformance level for each success criterion AccessDoc can report.

WHY THIS FILE EXISTS
--------------------
The OpenACR emitter decided Level A vs Level AA with:

    sc.endswith(".1") and sc[0] in "1234" and sc.split(".")[1] == "1"

Against the criteria in EN_301_549_MAP that expression identifies only a small fraction
of Level A criteria and misfiles others under success_criteria_level_aa.
It also misfiles Level AAA criteria under AA while the AAA chapter is emitted
as disabled: true.

A conformance level is a fact about the standard. It is never inferable from the
shape of the criterion number. Look it up.
"""

# Complete mapping for WCAG 2.1 / 2.2 criteria to conformance level (A, AA, AAA).
WCAG_LEVELS = {
    # Principle 1: Perceivable
    # 1.1 Text Alternatives
    "1.1.1": "A",    # Non-text Content
    # 1.2 Time-based Media
    "1.2.1": "A",    # Audio-only and Video-only (Prerecorded)
    "1.2.2": "A",    # Captions (Prerecorded)
    "1.2.3": "A",    # Audio Description or Media Alternative (Prerecorded)
    "1.2.4": "AA",   # Captions (Live)
    "1.2.5": "AA",   # Audio Description (Prerecorded)
    "1.2.6": "AAA",  # Sign Language (Prerecorded)
    "1.2.7": "AAA",  # Extended Audio Description (Prerecorded)
    "1.2.8": "AAA",  # Media Alternative (Prerecorded)
    "1.2.9": "AAA",  # Audio-only (Live)
    # 1.3 Adaptable
    "1.3.1": "A",    # Info and Relationships
    "1.3.2": "A",    # Meaningful Sequence
    "1.3.3": "A",    # Sensory Characteristics
    "1.3.4": "AA",   # Orientation
    "1.3.5": "AA",   # Identify Input Purpose
    "1.3.6": "AAA",  # Identify Purpose
    # 1.4 Distinguishable
    "1.4.1": "A",    # Use of Color
    "1.4.2": "A",    # Audio Control
    "1.4.3": "AA",   # Contrast (Minimum)
    "1.4.4": "AA",   # Resize Text
    "1.4.5": "AA",   # Images of Text
    "1.4.6": "AAA",  # Contrast (Enhanced)
    "1.4.7": "AAA",  # Low or No Background Audio
    "1.4.8": "AAA",  # Visual Presentation
    "1.4.9": "AAA",  # Images of Text (No Exception)
    "1.4.10": "AA",  # Reflow
    "1.4.11": "AA",  # Non-text Contrast
    "1.4.12": "AA",  # Text Spacing
    "1.4.13": "AA",  # Content on Hover or Focus

    # Principle 2: Operable
    # 2.1 Keyboard Accessible
    "2.1.1": "A",    # Keyboard
    "2.1.2": "A",    # No Keyboard Trap
    "2.1.3": "AAA",  # Keyboard (No Exception)
    "2.1.4": "A",    # Character Key Shortcuts
    # 2.2 Enough Time
    "2.2.1": "A",    # Timing Adjustable
    "2.2.2": "A",    # Pause, Stop, Hide
    "2.2.3": "AAA",  # No Timing
    "2.2.4": "AAA",  # Interruptions
    "2.2.5": "AAA",  # Re-authenticating
    "2.2.6": "AAA",  # Timeouts
    # 2.3 Seizures and Physical Reactions
    "2.3.1": "A",    # Three Flashes or Below Threshold
    "2.3.2": "AAA",  # Three Flashes
    "2.3.3": "AAA",  # Animation from Interactions
    # 2.4 Navigable
    "2.4.1": "A",    # Bypass Blocks
    "2.4.2": "A",    # Page Titled
    "2.4.3": "A",    # Focus Order
    "2.4.4": "A",    # Link Purpose (In Context)
    "2.4.5": "AA",   # Multiple Ways
    "2.4.6": "AA",   # Headings and Labels
    "2.4.7": "AA",   # Focus Visible
    "2.4.8": "AAA",  # Location
    "2.4.9": "AAA",  # Link Purpose (Link Only)
    "2.4.10": "AAA", # Section Headings
    "2.4.11": "AA",  # Focus Not Obscured (Minimum) - WCAG 2.2
    "2.4.12": "AAA", # Focus Not Obscured (Enhanced) - WCAG 2.2
    "2.4.13": "AAA", # Focus Appearance - WCAG 2.2
    # 2.5 Input Modalities
    "2.5.1": "A",    # Pointer Gestures
    "2.5.2": "A",    # Pointer Cancellation
    "2.5.3": "A",    # Label in Name
    "2.5.4": "A",    # Motion Actuation
    "2.5.5": "AAA",  # Target Size
    "2.5.6": "AAA",  # Concurrent Input Mechanisms
    "2.5.7": "AA",   # Dragging Movements - WCAG 2.2
    "2.5.8": "AA",   # Target Size (Minimum) - WCAG 2.2

    # Principle 3: Understandable
    # 3.1 Readable
    "3.1.1": "A",    # Language of Page
    "3.1.2": "AA",   # Language of Parts
    "3.1.3": "AAA",  # Unusual Words
    "3.1.4": "AAA",  # Abbreviations
    "3.1.5": "AAA",  # Reading Level
    "3.1.6": "AAA",  # Pronunciation
    # 3.2 Predictable
    "3.2.1": "A",    # On Focus
    "3.2.2": "A",    # On Input
    "3.2.3": "AA",   # Consistent Navigation
    "3.2.4": "AA",   # Consistent Identification
    "3.2.5": "AAA",  # Change on Request
    "3.2.6": "A",    # Consistent Help - WCAG 2.2
    # 3.3 Input Assistance
    "3.3.1": "A",    # Error Identification
    "3.3.2": "A",    # Labels or Instructions
    "3.3.3": "AA",   # Error Suggestion
    "3.3.4": "AA",   # Error Prevention (Legal, Financial, Data)
    "3.3.5": "AAA",  # Help
    "3.3.6": "AAA",  # Error Prevention (All)
    "3.3.7": "A",    # Redundant Entry - WCAG 2.2
    "3.3.8": "AA",   # Accessible Authentication (Minimum) - WCAG 2.2
    "3.3.9": "AAA",  # Accessible Authentication (Enhanced) - WCAG 2.2

    # Principle 4: Robust
    # 4.1 Compatible
    "4.1.1": "A",    # Parsing - Obsolete in WCAG 2.2
    "4.1.2": "A",    # Name, Role, Value
    "4.1.3": "AA",   # Status Messages
}

WCAG_22_ONLY = {"2.4.11", "2.4.12", "2.4.13", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8", "3.3.9"}
REMOVED_IN_WCAG_22 = {"4.1.1"}

_CHAPTER = {
    "A": "success_criteria_level_a",
    "AA": "success_criteria_level_aa",
    "AAA": "success_criteria_level_aaa",
}


def level_for(sc):
    """Return 'A' | 'AA' | 'AAA' for a success-criterion number, or None.

    Returning None is deliberate: an unknown criterion must be reported as
    unmapped, never guessed into a chapter. Guessing is the bug this replaces.
    """
    return WCAG_LEVELS.get(str(sc).strip())


def chapter_for(sc):
    """Return the GSA OpenACR chapter key for a criterion, or None if unmapped."""
    lvl = level_for(sc)
    return _CHAPTER.get(lvl) if lvl else None


def partition(scs):
    """Split criteria into {chapter_key: [sc, ...]} plus an 'unmapped' list."""
    out = {v: [] for v in _CHAPTER.values()}
    unmapped = []
    for sc in scs:
        key = chapter_for(sc)
        (out[key] if key else unmapped).append(sc)
    return out, unmapped
