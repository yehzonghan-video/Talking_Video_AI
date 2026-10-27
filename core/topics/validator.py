"""Validate suggested alternatives against the caller's catalog."""
from core.topics.topic_manager import Catalog


def validate_alternatives(catalog: Catalog, selections: list[dict]) -> list[dict]:
    return [catalog.validate(selection) for selection in selections]
