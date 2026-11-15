"""Small helpers for HTML parsed with BeautifulSoup."""

from __future__ import annotations

from bs4 import Tag


def attr(tag: Tag, name: str) -> str:
    """
    An attribute as text: '' when absent, a multi-valued one (``class``)
    joined by spaces. ``tag.get(name) or ""`` with a type that says so.
    """
    value = tag.get(name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return " ".join(value)


def required_attr(tag: Tag, name: str) -> str:
    """``tag[name]`` as text; KeyError when absent, like ``tag[name]``."""
    value = tag[name]
    return value if isinstance(value, str) else " ".join(value)
