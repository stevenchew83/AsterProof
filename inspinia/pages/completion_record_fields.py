from __future__ import annotations

from datetime import date

from inspinia.pages.models import UserProblemCompletion

BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
BOOLEAN_FALSE_VALUES = {"0", "false", "no", "n", "off"}
POST_MORTEM_MAX_LENGTH = 240

COMPLETION_METADATA_FIELDS = (
    "status",
    "time_spent_minutes",
    "first_idea_found",
    "proof_completed",
    "main_obstacle",
    "key_technique",
    "post_mortem",
    "reattempt_date",
    "confidence",
)
SOLVED_STATUSES = {
    UserProblemCompletion.Status.SOLVED,
    UserProblemCompletion.Status.CHECKED,
    UserProblemCompletion.Status.WRITTEN,
    UserProblemCompletion.Status.PUBLISHED,
}


def _choice_values(choices) -> set[str]:
    return {value for value, _label in choices}


def _choice_label(choices, value: str) -> str:
    if not value:
        return ""
    labels = dict(choices)
    return str(labels.get(value, value))


def _parse_nullable_bool(raw_value: str) -> tuple[bool | None, str | None]:
    value = (raw_value or "").strip().casefold()
    if not value:
        return None, None
    if value in BOOLEAN_TRUE_VALUES:
        return True, None
    if value in BOOLEAN_FALSE_VALUES:
        return False, None
    return None, "Boolean values must be yes or no."


def _parse_minutes(raw_value: str) -> tuple[int | None, str | None]:
    value = (raw_value or "").strip()
    if not value:
        return None, None
    try:
        minutes = int(value)
    except ValueError:
        return None, "Time spent must be a whole number of minutes."
    if minutes < 0:
        return None, "Time spent cannot be negative."
    return minutes, None


def _parse_optional_date(raw_value: str) -> tuple[date | None, str | None]:
    value = (raw_value or "").strip()
    if not value:
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, "Reattempt date must be a valid YYYY-MM-DD value."


def has_completion_metadata(post_data) -> bool:
    return any(field in post_data for field in COMPLETION_METADATA_FIELDS)


def completion_metadata_from_post(
    post_data,
    *,
    default_status: str = UserProblemCompletion.Status.SOLVED,
) -> tuple[dict[str, object], str | None]:
    status = (post_data.get("status") or "").strip() or default_status
    main_obstacle = (post_data.get("main_obstacle") or "").strip()
    confidence = (post_data.get("confidence") or "").strip()
    time_spent_minutes, time_spent_error = _parse_minutes(post_data.get("time_spent_minutes") or "")
    first_idea_found, first_idea_error = _parse_nullable_bool(post_data.get("first_idea_found") or "")
    proof_completed, proof_error = _parse_nullable_bool(post_data.get("proof_completed") or "")
    reattempt_date, reattempt_error = _parse_optional_date(post_data.get("reattempt_date") or "")
    post_mortem = (post_data.get("post_mortem") or "").strip()
    error_message = None
    if status not in _choice_values(UserProblemCompletion.Status.choices):
        error_message = "Status is not valid."
    elif main_obstacle and main_obstacle not in _choice_values(UserProblemCompletion.MainObstacle.choices):
        error_message = "Main obstacle is not valid."
    elif confidence and confidence not in _choice_values(UserProblemCompletion.Confidence.choices):
        error_message = "Confidence is not valid."
    elif time_spent_error:
        error_message = time_spent_error
    elif first_idea_error:
        error_message = "First idea found must be yes or no."
    elif proof_error:
        error_message = "Proof completed must be yes or no."
    elif reattempt_error:
        error_message = reattempt_error
    elif len(post_mortem) > POST_MORTEM_MAX_LENGTH:
        error_message = f"Post-mortem must be {POST_MORTEM_MAX_LENGTH} characters or fewer."

    if error_message is not None:
        return {}, error_message

    return {
        "status": status,
        "time_spent_minutes": time_spent_minutes,
        "first_idea_found": first_idea_found,
        "proof_completed": proof_completed,
        "main_obstacle": main_obstacle,
        "key_technique": (post_data.get("key_technique") or "").strip()[:160],
        "post_mortem": post_mortem,
        "reattempt_date": reattempt_date,
        "confidence": confidence,
    }, None


def format_time_spent_minutes(minutes: int | None) -> str:
    if minutes is None:
        return ""
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def boolean_label(value: bool | None) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return ""


def is_completion_status_solved(status: str) -> bool:
    return status in SOLVED_STATUSES


def completion_metadata_payload(completion: UserProblemCompletion | None) -> dict[str, object]:
    if completion is None:
        return {
            "status": UserProblemCompletion.Status.UNATTEMPTED,
            "status_label": UserProblemCompletion.Status.UNATTEMPTED.label,
            "time_spent_minutes": None,
            "time_spent_display": "",
            "first_idea_found": None,
            "first_idea_found_label": "",
            "proof_completed": None,
            "proof_completed_label": "",
            "main_obstacle": "",
            "main_obstacle_label": "",
            "key_technique": "",
            "post_mortem": "",
            "reattempt_date": "",
            "reattempt_date_sort": "9999-12-31",
            "confidence": "",
            "confidence_label": "",
        }

    return {
        "status": completion.status,
        "status_label": completion.get_status_display(),
        "time_spent_minutes": completion.time_spent_minutes,
        "time_spent_display": format_time_spent_minutes(completion.time_spent_minutes),
        "first_idea_found": completion.first_idea_found,
        "first_idea_found_label": boolean_label(completion.first_idea_found),
        "proof_completed": completion.proof_completed,
        "proof_completed_label": boolean_label(completion.proof_completed),
        "main_obstacle": completion.main_obstacle,
        "main_obstacle_label": _choice_label(UserProblemCompletion.MainObstacle.choices, completion.main_obstacle),
        "key_technique": completion.key_technique,
        "post_mortem": completion.post_mortem,
        "reattempt_date": completion.reattempt_date.isoformat() if completion.reattempt_date else "",
        "reattempt_date_sort": completion.reattempt_date.isoformat() if completion.reattempt_date else "9999-12-31",
        "confidence": completion.confidence,
        "confidence_label": _choice_label(UserProblemCompletion.Confidence.choices, completion.confidence),
    }
