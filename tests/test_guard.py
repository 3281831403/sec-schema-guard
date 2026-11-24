"""Behavior tests for the sec-schema-guard exercise.

All inputs are fixed.  The first ten tests map one-to-one to the ten
specification defects; the last five cover the required correct semantics.
The tests do not read the clock, use randomness, touch the network, or
create temporary files.
"""

import json

import pytest

from schema.guard import (
    check_budget,
    number_bounds,
    parse_schema,
    resolve_ref,
    schema_batch,
    type_matches,
    validate,
    validate_document,
)


BUDGET = {"max_depth": 4, "max_width": 8}
POLICY = {"budget": BUDGET}


def test_defect_01_ref_cycle_is_detected():
    schema = {
        "$ref": "#/definitions/a",
        "definitions": {
            "a": {"$ref": "#/definitions/b"},
            "b": {"$ref": "#/definitions/a"},
        },
    }

    with pytest.raises(ValueError):
        resolve_ref(schema, "#/definitions/a")


def test_defect_02_boolean_is_not_an_integer():
    assert type_matches(True, "integer") is False
    assert type_matches(True, "number") is False
    assert type_matches(1, "integer") is True

    errors = validate(True, {"type": "integer"}, "$", BUDGET)

    assert [(error["path"], error["code"]) for error in errors] == [("$", "type")]


def test_defect_03_union_tries_every_branch():
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "integer"},
                    {"type": "string"},
                ]
            }
        },
        "required": ["payload"],
        "additionalProperties": False,
    }

    errors = validate({"payload": "not-an-integer"}, schema, "$", BUDGET)

    assert errors == []


def test_defect_04_undeclared_property_is_rejected():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    errors = validate({"name": "ok", "role": "admin"}, schema, "$", BUDGET)

    assert [(error["path"], error["code"]) for error in errors] == [
        ("$.role", "additional_property")
    ]


def test_defect_05_array_nesting_consumes_depth_budget():
    schema = {
        "type": "array",
        "items": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
    }

    errors = validate(
        [[[7]]],
        schema,
        "$",
        {"max_depth": 2, "max_width": 4},
    )

    assert [(error["path"], error["code"]) for error in errors] == [
        ("$[0][0]", "budget")
    ]


def test_defect_06_width_counts_elements_not_characters():
    assert check_budget({"max_depth": 3, "max_width": 3}, 3, 3) is True
    assert check_budget({"max_depth": 3, "max_width": 3}, 4, 3) is False
    assert check_budget({"max_depth": 3, "max_width": 3}, 3, 4) is False

    schema = {"type": "array", "items": {"type": "string"}}

    errors = validate(
        ["", "", "", ""],
        schema,
        "$",
        {"max_depth": 3, "max_width": 3},
    )

    assert [(error["path"], error["code"]) for error in errors] == [
        ("$", "budget")
    ]


def test_defect_07_number_bounds_include_endpoints():
    schema = {"minimum": 0, "maximum": 100}

    assert number_bounds(0, schema) is True
    assert number_bounds(100, schema) is True
    assert number_bounds(-0.01, schema) is False
    assert number_bounds(100.01, schema) is False


def test_defect_08_report_all_path_errors():
    schema = {
        "type": "object",
        "properties": {
            "left": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            "right": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
        "required": ["left", "right"],
        "additionalProperties": False,
    }

    errors = validate(
        {"left": {"value": "x"}, "right": {"value": "y"}},
        schema,
        "$",
        BUDGET,
    )

    assert [(error["path"], error["code"]) for error in errors] == [
        ("$.left.value", "type"),
        ("$.right.value", "type"),
    ]


def test_defect_09_budget_is_checked_before_validation():
    document = [0] * 5000
    document[-1] = "bad"
    schema = {"type": "array", "items": {"type": "integer"}}
    policy = {"budget": {"max_depth": 2, "max_width": 10}}

    report = validate_document(document, schema, policy)

    assert report["ok"] is False
    assert [(error["path"], error["code"]) for error in report["errors"]] == [
        ("$", "budget")
    ]


def test_defect_10_batch_keeps_documents_independent():
    schema = {
        "$ref": "#/definitions/item",
        "definitions": {
            "item": {
                "type": "object",
                "properties": {"score": {"type": "integer"}},
                "required": ["score"],
                "additionalProperties": False,
            }
        },
    }
    documents = [{"score": 1}, {"score": "bad"}]

    report = schema_batch(
        documents,
        schema,
        {"budget": {"max_depth": 3, "max_width": 4}},
    )

    assert report["results"][0] == {"ok": True, "errors": []}
    assert [
        (error["path"], error["code"])
        for error in report["results"][1]["errors"]
    ] == [("$.score", "type")]


def test_valid_document_passes_without_errors():
    schema_text = json.dumps(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 120,
                },
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        }
    )
    schema = parse_schema(schema_text)

    report = validate_document(
        {"name": "Ada", "age": 36},
        schema,
        POLICY,
    )

    assert report == {"ok": True, "errors": []}

    with pytest.raises(ValueError):
        parse_schema('{"type": "string", "unknown_keyword": true}')


def test_type_mismatch_reports_exact_path():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }

    report = validate_document({"name": 42}, schema, POLICY)

    assert report["ok"] is False
    assert [(error["path"], error["code"]) for error in report["errors"]] == [
        ("$.name", "type")
    ]


def test_boundary_values_are_accepted():
    schema = {
        "type": "object",
        "properties": {
            "low": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
            },
            "high": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
            },
        },
        "required": ["low", "high"],
        "additionalProperties": False,
    }

    report = validate_document({"low": 0, "high": 100}, schema, POLICY)

    assert report["ok"] is True
    assert report["errors"] == []


def test_cyclic_schema_is_rejected_without_recursion_error():
    schema = {
        "type": "object",
        "definitions": {
            "node": {
                "type": "object",
                "properties": {
                    "next": {"$ref": "#/definitions/node"},
                },
                "additionalProperties": False,
            }
        },
        "properties": {"root": {"$ref": "#/definitions/node"}},
        "required": ["root"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError):
        validate_document(
            {"root": {"next": {}}},
            schema,
            {"budget": {"max_depth": 4, "max_width": 4}},
        )


def test_two_batches_match_individual_validations():
    schema = {
        "$ref": "#/definitions/item",
        "definitions": {
            "item": {
                "type": "object",
                "properties": {"score": {"type": "integer"}},
                "required": ["score"],
                "additionalProperties": False,
            }
        },
    }
    documents = [{"score": 1}, {"score": "bad"}]
    policy = {"budget": {"max_depth": 3, "max_width": 4}}

    forward = schema_batch(documents, schema, policy)["results"]
    reverse = schema_batch(list(reversed(documents)), schema, policy)["results"]
    expected = [validate_document(document, schema, policy) for document in documents]

    assert forward == expected
    assert reverse == list(reversed(expected))