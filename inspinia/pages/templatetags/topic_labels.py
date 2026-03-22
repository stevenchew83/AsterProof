from django import template

from inspinia.pages.topic_labels import display_topic_label

register = template.Library()


@register.filter
def topic_label(value: str | None) -> str:
    return display_topic_label(value)
