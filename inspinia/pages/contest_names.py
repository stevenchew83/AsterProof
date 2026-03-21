import re

PROJECT_CONTEST_NAME_MAX_LENGTH = 64
STATEMENT_CONTEST_NAME_MAX_LENGTH = 128


def normalize_contest_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def normalize_text_list(values: list[str] | tuple[str, ...]) -> list[str]:
    normalized_values: list[str] = []
    seen_values: set[str] = set()
    for raw_value in values or []:
        normalized_value = re.sub(r"\s+", " ", str(raw_value or "").strip())
        if not normalized_value:
            continue
        seen_key = normalized_value.casefold()
        if seen_key in seen_values:
            continue
        seen_values.add(seen_key)
        normalized_values.append(normalized_value)
    return normalized_values
