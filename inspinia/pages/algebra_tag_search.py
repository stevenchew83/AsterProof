"""Search reviewed algebra aliases without adding taxonomy or coverage rows."""

from django.db.models import Q

from inspinia.pages.algebra_vocabulary import combined_import_policy

ALGEBRA_PATTERN = r"^\s*(A|ALG|ALGEBRA)\s*$"
SUPPRESSED_PATTERN = r"^\s*(invalid|corrupt|metadata)\s*$"


def tag_token_query(token: str, *, source: str, field: str = "technique") -> Q:
    """Retain the normal match and add aliases only on eligible algebra rows."""
    query = Q(**{f"{field}__icontains": token})
    matches = Q()
    for rule in combined_import_policy()["mappings"]:
        if rule["field"] != field:
            continue
        if any(token.casefold() in value.casefold() for value in (rule["source"], rule["target"])):
            matches |= Q(**{f"{field}__icontains": rule["source"]})
            matches |= Q(**{f"{field}__icontains": rule["target"]})
    if field == "technique":
        matches |= Q(raw_tag__icontains=token)
    if not matches:
        return query
    if source == "problem":
        scope = Q(record__is_active=True, record__topic__iregex=ALGEBRA_PATTERN)
    else:
        scope = Q(statement__is_active=True) & (
            Q(statement__topic__iregex=ALGEBRA_PATTERN)
            | Q(statement__topic__iregex=r"^\s*$", statement__linked_problem__topic__iregex=ALGEBRA_PATTERN)
        )
    return query | (scope & ~Q(normalization_status__iregex=SUPPRESSED_PATTERN) & matches)
