"""Secure schema guard.

The module implements a small JSON-schema-like validator used for external
data ingress.  The ten hardening points, in the order reported by the task:

1. ``resolve_ref`` detects circular local ``$ref`` chains.
2. ``bool`` is a distinct type and never matches ``integer`` / ``number``.
3. ``anyOf`` tries *every* branch and only fails when all branches fail.
4. Undeclared object properties are rejected by default.
5. Array nesting consumes the same depth budget as object nesting.
6. Width counts properties / elements, not string characters.
7. ``minimum`` / ``maximum`` are inclusive bounds.
8. Validation collects every path-specific error instead of stopping early.
9. ``validate_document`` checks the whole-document budget before validating.
10. Batch validation keeps every document's resolution/error state separate.

Only the Python standard library is used.
"""

import json
from typing import Any


# Schema keywords understood by this validator.  parse_schema rejects every
# other keyword recursively.
KNOWN_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "anyOf",
        "$ref",
        "definitions",
        "minimum",
        "maximum",
    }
)

# Codes that callers rely on.
TYPE = "type"
ADDITIONAL_PROPERTY = "additional_property"
REQUIRED = "required"
BOUNDS = "bounds"
BUDGET = "budget"


def parse_schema(text: str) -> dict:
    """Parse schema text and reject unknown schema keywords."""
    schema = json.loads(text)
    if not isinstance(schema, dict):
        raise ValueError("schema must be a JSON object")
    _check_keywords(schema)
    return schema


def _check_keywords(node: Any) -> None:
    """Recursively reject schema nodes carrying an unknown keyword."""
    if isinstance(node, dict):
        for key in node:
            if key not in KNOWN_KEYWORDS:
                raise ValueError(f"unknown schema keyword: {key!r}")

        properties = node.get("properties")
        if isinstance(properties, dict):
            for sub_schema in properties.values():
                _check_keywords(sub_schema)

        definitions = node.get("definitions")
        if isinstance(definitions, dict):
            for sub_schema in definitions.values():
                _check_keywords(sub_schema)

        any_of = node.get("anyOf")
        if isinstance(any_of, list):
            for sub_schema in any_of:
                _check_keywords(sub_schema)

        if "items" in node:
            _check_keywords(node["items"])

        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            _check_keywords(additional)


def _walk_pointer(root: Any, ref: str) -> Any:
    """Resolve a single local JSON Pointer (RFC 6901) against root."""
    if ref == "#" or ref == "":
        return root

    if not ref.startswith("#/"):
        raise ValueError(f"unsupported reference (only local pointers): {ref!r}")

    node = root
    for token in ref[2:].split("/"):
        # Unescape in the RFC order: "~1" -> "/" first, then "~0" -> "~".
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if key not in node:
                raise ValueError(f"reference not found: {ref!r}")
            node = node[key]
        elif isinstance(node, list):
            try:
                index = int(key)
            except ValueError as exc:
                raise ValueError(f"invalid array index in reference: {ref!r}") from exc
            node = node[index]
        else:
            raise ValueError(f"reference path does not resolve: {ref!r}")
    return node


def _resolve_ref_chain(root: dict, ref: str):
    """Follow a local ``$ref`` chain hop by hop.

    Returns ``(target, hops)`` where ``hops`` is every reference visited
    (including the starting one) and ``target`` is the first node that no
    longer carries a ``$ref``.  Repeating a reference means a cycle, which is
    rejected with ``ValueError`` instead of looping forever.
    """
    seen = set()
    hops = []
    current = ref

    while True:
        if not isinstance(current, str) or not current.startswith("#"):
            raise ValueError(f"unsupported reference: {current!r}")
        # Defect 1: circular reference detection.
        if current in seen:
            raise ValueError(f"circular reference detected: {current!r}")
        seen.add(current)
        hops.append(current)

        node = _walk_pointer(root, current)
        if isinstance(node, dict) and "$ref" in node:
            current = node["$ref"]
            continue
        return node, tuple(hops)


def resolve_ref(schema: dict, ref: str) -> dict:
    """Resolve a local reference, rejecting circular reference chains."""
    target, _ = _resolve_ref_chain(schema, ref)
    return target


def type_matches(value: Any, type_name: str) -> bool:
    """Return whether value matches type_name, keeping bool and int distinct."""
    # Defect 2: bool is its own JSON type and must not pass integer/number.
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "null":
        return value is None
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def _is_real_number(value: Any) -> bool:
    """A numeric value excluding booleans (which subclass int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_budget(budget: dict, depth: int, width: int) -> bool:
    """Return False when depth or width exceeds its inclusive limit."""
    # Defect 6 (width is an element/property count supplied by the caller).
    # Limits are inclusive: equal to the limit is still allowed (defect 5/6).
    max_depth = budget.get("max_depth", depth)
    max_width = budget.get("max_width", width)
    return depth <= max_depth and width <= max_width


def number_bounds(value: Any, schema: dict) -> bool:
    """Check inclusive minimum and maximum bounds."""
    if not _is_real_number(value):
        return False

    # Defect 7: closed intervals, endpoints are accepted.
    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        return False

    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        return False

    return True


def _width(value: Any) -> int:
    """Width = number of object properties or array elements; 0 for scalars."""
    if isinstance(value, (dict, list)):
        return len(value)
    return 0


def _error(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def validate(value: Any, schema: dict, path: str, budget: dict) -> list:
    """Validate value and return every path-specific error.

    This public entry starts a fresh resolution/error context.  Internal
    recursion uses :func:`_validate` to carry the schema root, data depth and
    the set of references currently being expanded.
    """
    return _validate(
        value,
        schema,
        path,
        budget,
        root=schema,
        depth=1,
        active_refs=frozenset(),
    )


def _validate(
    value: Any,
    schema: Any,
    path: str,
    budget: dict,
    root: dict,
    depth: int,
    active_refs: frozenset,
) -> list:
    # A budget violation stops expansion of this node and reports its exact
    # path (defects 5 and 6).  Depth counts every nesting layer, including
    # arrays; width is the raw element/property count.
    if not check_budget(budget, depth, _width(value)):
        return [_error(path, BUDGET, f"budget exceeded at {path}")]

    if not isinstance(schema, dict):
        return []

    # Reference indirection adds no data depth and keeps the same path.
    if "$ref" in schema:
        ref = schema["$ref"]
        target, hops = _resolve_ref_chain(root, ref)
        # Re-entering a reference that is still being expanded means the
        # schema graph contains a cycle (e.g. node -> next -> node).
        for hop in hops:
            if hop in active_refs:
                raise ValueError(f"circular reference detected: {hop!r}")
        return _validate(
            value,
            target,
            path,
            budget,
            root,
            depth,
            active_refs.union(hops),
        )

    errors = []

    declared_type = schema.get("type")
    if declared_type is not None and not type_matches(value, declared_type):
        # A type mismatch makes further structural checks meaningless.
        return [_error(path, TYPE, f"expected {declared_type} at {path}")]

    # Numeric bounds (inclusive).  Only apply to real numbers; other types are
    # handled by their own type rules.
    if ("minimum" in schema or "maximum" in schema) and _is_real_number(value):
        if not number_bounds(value, schema):
            errors.append(_error(path, BOUNDS, f"value is out of bounds at {path}"))

    # Defect 3: anyOf must try every branch.  One clean branch is a pass.
    if "anyOf" in schema:
        branch_errors = []
        matched = False
        for branch in schema["anyOf"]:
            result = _validate(
                value, branch, path, budget, root, depth, active_refs
            )
            if not result:
                matched = True
                break
            branch_errors.append(result)
        if not matched:
            # Surface the path-specific failures from every attempted branch.
            for result in branch_errors:
                errors.extend(result)

    _validate_object(value, schema, path, budget, root, depth, active_refs, errors)
    _validate_array(value, schema, path, budget, root, depth, active_refs, errors)

    return errors


def _validate_object(
    value, schema, path, budget, root, depth, active_refs, errors
) -> None:
    if not isinstance(value, dict):
        return

    has_object_rules = any(
        key in schema
        for key in ("properties", "required", "additionalProperties")
    ) or schema.get("type") == "object"
    if not has_object_rules:
        return

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Declared properties, in declaration order, so sibling errors stay stable.
    for name, sub_schema in properties.items():
        child_path = f"{path}.{name}"
        if name in value:
            errors.extend(
                _validate(
                    value[name],
                    sub_schema,
                    child_path,
                    budget,
                    root,
                    depth + 1,
                    active_refs,
                )
            )
        elif name in required:
            errors.append(
                _error(child_path, REQUIRED, f"missing required property {name!r}")
            )

    # Defect 4: undeclared properties are rejected unless explicitly allowed.
    additional = schema.get("additionalProperties", False)
    if additional is True:
        return

    for name in value:
        if name in properties:
            continue
        child_path = f"{path}.{name}"
        if isinstance(additional, dict):
            errors.extend(
                _validate(
                    value[name],
                    additional,
                    child_path,
                    budget,
                    root,
                    depth + 1,
                    active_refs,
                )
            )
        else:
            errors.append(
                _error(
                    child_path,
                    ADDITIONAL_PROPERTY,
                    f"undeclared property {name!r}",
                )
            )


def _validate_array(
    value, schema, path, budget, root, depth, active_refs, errors
) -> None:
    if not isinstance(value, list):
        return
    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return

    for index, item in enumerate(value):
        child_path = f"{path}[{index}]"
        # Defect 5: descending into each element adds a layer, so nested
        # arrays consume depth budget just like nested objects.
        errors.extend(
            _validate(
                item,
                item_schema,
                child_path,
                budget,
                root,
                depth + 1,
                active_refs,
            )
        )


def _document_exceeds_budget(value: Any, budget: dict, depth: int = 1) -> bool:
    """Whole-document pre-scan.

    Returns True as soon as any node violates the depth/width budget.  The
    scan never expands schema references and short-circuits on the first
    violation, so a very wide root is rejected cheaply.
    """
    if not check_budget(budget, depth, _width(value)):
        return True

    if isinstance(value, dict):
        return any(
            _document_exceeds_budget(child, budget, depth + 1)
            for child in value.values()
        )
    if isinstance(value, list):
        return any(
            _document_exceeds_budget(child, budget, depth + 1) for child in value
        )
    return False


def validate_document(doc: Any, schema: dict, policy: dict) -> dict:
    """Validate one document, checking the full budget before validation."""
    budget = (policy or {}).get("budget", {})

    # Defect 9: budget first.  A pre-validation failure is reported as a
    # single budget error at the root and skips all field expansion.
    if _document_exceeds_budget(doc, budget, 1):
        return {
            "ok": False,
            "errors": [_error("$", BUDGET, "document exceeds the configured budget")],
        }

    errors = validate(doc, schema, "$", budget)
    return {"ok": not errors, "errors": errors}


def schema_batch(docs: list, schema: dict, policy: dict) -> dict:
    """Validate documents independently and return one report per document."""
    # Defect 10: no shared reference cache, error list or result is carried
    # between documents; each call builds a fresh validation context.
    results = [validate_document(doc, schema, policy) for doc in docs]
    return {"results": results}
