"""Fixed OpenAI endpoint and a strict seven-point response contract."""

import json
from http import HTTPStatus
from time import monotonic

from django.views.decorators.debug import sensitive_variables

from .admin_reviews import SCORE_MAX
from .admin_reviews import provider_input

FORMAT = {
    "type": "json_schema",
    "name": "asterproof_scored_review",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "enum": list(range(SCORE_MAX + 1))},
            "feedback": {"type": "string"},
        },
        "additionalProperties": False,
        "required": ["score", "feedback"],
    },
}
MAX_FEEDBACK_CHARS = 24_000
MAX_RESPONSE_CHARS = MAX_FEEDBACK_CHARS * 8
PREVIEW_PARSE_INTERVAL = 1


class ReviewProviderError(Exception):
    def __init__(self, message, *, uncertain=False):
        self.uncertain = uncertain
        super().__init__(message)


@sensitive_variables("key", "client")
def request_review(review, key, *, on_preview):
    import openai

    payload = provider_input(review.target.snapshot, review.problem_label)
    try:
        with openai.OpenAI(
            api_key=key, base_url="https://api.openai.com/v1", timeout=240, max_retries=0,
            admin_api_key="", organization="", project="", webhook_secret="",
            default_headers={"Authorization": f"Bearer {key}"},
        ) as client:
            stream = client.responses.create(
                stream=True,
                model=review.model,
                store=False,
                reasoning={"effort": review.effort},
                max_output_tokens=review.output_limit,
                input=[
                    {"role": "system", "content": review.instructions},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text={"format": FORMAT},
            )
            with stream:
                return _read_stream(stream, on_preview)
    except openai.APIConnectionError:
        message = "OpenAI did not confirm the outcome. This request was not retried."
        raise ReviewProviderError(message, uncertain=True) from None
    except openai.APIStatusError as error:
        uncertain = (
            error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR or error.status_code == HTTPStatus.REQUEST_TIMEOUT
        )
        message = (
            "OpenAI did not confirm the outcome. This request was not retried."
            if uncertain else "OpenAI rejected the request. Check the key, model access, and project limits."
        )
        raise ReviewProviderError(message, uncertain=uncertain) from None


def _read_stream(stream, on_preview):
    from pydantic_core import from_json

    raw = ""
    last_preview = -PREVIEW_PARSE_INTERVAL
    for event in stream:
        if event.type in {"response.completed", "response.incomplete", "response.failed"}:
            return event.response
        if event.type != "response.output_text.delta" or len(raw) > MAX_RESPONSE_CHARS:
            continue
        raw += event.delta
        now = monotonic()
        if len(raw) > MAX_RESPONSE_CHARS or now - last_preview < PREVIEW_PARSE_INTERVAL:
            continue
        try:
            partial = from_json(raw, allow_partial="trailing-strings")
        except ValueError:
            continue
        if isinstance(partial, dict) and isinstance(partial.get("feedback"), str):
            on_preview(partial["feedback"][:MAX_FEEDBACK_CHARS])
            last_preview = now
    message = "OpenAI closed the stream without confirming the outcome."
    raise ReviewProviderError(message, uncertain=True)


def scored_result(raw):
    try:
        report = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(report, dict) or set(report) != {"score", "feedback"}:
        return None
    score, feedback = report["score"], report["feedback"]
    if (
        type(score) is not int or not 0 <= score <= SCORE_MAX
        or not isinstance(feedback, str) or not feedback.strip()
        or len(feedback) > MAX_FEEDBACK_CHARS or "\x00" in feedback
    ):
        return None
    try:
        feedback.encode("utf-8")
    except UnicodeError:
        return None
    return score, feedback.strip()
