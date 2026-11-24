"""Stubs for the sec-schema-guard exercise.

Every public function below is intentionally unimplemented.  The tests in
tests/test_guard.py are the executable contract; do not change them.
"""

from typing import Any


def parse_schema(text: str) -> dict:
    """Parse schema text and reject unknown schema keywords."""
    raise NotImplementedError


def resolve_ref(schema: dict, ref: str) -> dict:
    """Resolve a local reference, rejecting circular reference chains."""
    raise NotImplementedError


def type_matches(value: Any, type_name: str) -> bool:
    """Return whether value matches type_name, keeping bool and int distinct."""
    raise NotImplementedError


def validate(value: Any, schema: dict, path: str, budget: dict) -> list:
    """Validate value and return every path-specific error."""
    raise NotImplementedError


def check_budget(budget: dict, depth: int, width: int) -> bool:
    """Return False when depth or width exceeds its inclusive limit."""
    raise NotImplementedError


def number_bounds(value: Any, schema: dict) -> bool:
    """Check inclusive minimum and maximum bounds."""
    raise NotImplementedError


def validate_document(doc: Any, schema: dict, policy: dict) -> dict:
    """Validate one document, checking the full budget before validation."""
    raise NotImplementedError


def schema_batch(docs: list, schema: dict, policy: dict) -> dict:
    """Validate documents independently and return one report per document."""
    raise NotImplementedError