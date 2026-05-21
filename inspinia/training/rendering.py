from __future__ import annotations

from inspinia.training.markdown import render_markdown


def render_training_markdown(source: str) -> str:
    return str(render_markdown(source))
