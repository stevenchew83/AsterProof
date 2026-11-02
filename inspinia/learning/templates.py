"""Optional teaching prompts; creating a draft never implies note coverage."""

_TEMPLATE_SECTIONS = {
    "overview": [
        "Scope and intuition",
        "A map of the ideas",
        "Before you begin",
        "Suggested routes",
        "Practice and further study",
    ],
    "concept": [
        "Definition and notation",
        "Assumptions and examples",
        "Important results",
        "Proof and intuition",
        "Common misconceptions",
        "Practice and hints",
    ],
    "lecture": [
        "Learning objectives",
        "Prerequisites and assumptions",
        "Mathematical statement",
        "Proof and intuition",
        "Worked example and equality cases",
        "Recognition cues and common mistakes",
        "Practice",
        "Hints",
        "Further exploration",
    ],
    "technique": [
        "When to recognise this method",
        "When the connection is misleading",
        "How the method works",
        "Worked example",
        "Failure modes",
        "Practice and hints",
    ],
    "standalone": ["The idea", "Explanation", "Examples", "Sources and permissions"],
}
TEACHING_TEMPLATES = {
    key: "\n\n".join(f"## {heading}" for heading in headings) + "\n" for key, headings in _TEMPLATE_SECTIONS.items()
}
