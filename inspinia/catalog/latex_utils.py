import re


_BANNED_COMMANDS = (
    r"\write18",
    r"\input",
    r"\include",
    r"\openout",
    r"\read",
)


def lint_statement_source(source: str, statement_format: str) -> list[str]:
    """Return non-fatal validation errors for statement content."""
    if statement_format not in {"latex", "markdown_tex"}:
        return []

    issues: list[str] = []
    if "\x00" in source:
        issues.append("LaTeX content contains a null byte.")

    for command in _BANNED_COMMANDS:
        if command in source:
            issues.append(f"Disallowed LaTeX command detected: {command}")

    open_braces = 0
    escaped = False
    for char in source:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            open_braces += 1
        elif char == "}":
            open_braces -= 1
            if open_braces < 0:
                issues.append("Unbalanced braces in LaTeX content.")
                break

    if open_braces > 0:
        issues.append("Unbalanced braces in LaTeX content.")

    return issues


def to_plaintext(source: str, statement_format: str) -> str:
    if statement_format == "plain":
        return source.strip()

    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", source)
    text = re.sub(r"[$`*_#~]", " ", text)
    text = re.sub(r"[{}\\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
