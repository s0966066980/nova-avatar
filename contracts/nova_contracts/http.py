# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The loopback HTTP shape of a layer service, and its OpenAPI document.

There is no HTTP server yet (spec decision 21). Each layer contract module that
will become a loopback service declares ``HTTP_API``: one ``HttpOperation`` per
method of its service Protocol, named after that method.
``scripts/generate_openapi.py`` writes ``contracts/openapi/<module>.json`` from
it and CI checks the committed files are current.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, TypeAdapter

from nova_contracts import CONTRACT_VERSION
from nova_contracts.common import ErrorBody, ServiceHealth

_REF = "#/components/schemas/{model}"


@dataclass(frozen=True)
class JsonBody:
    """A JSON request or response body holding one contract model."""

    model: type[BaseModel]


@dataclass(frozen=True)
class BinaryBody:
    """A raw body, such as encoded audio or chunked 16 kHz s16le PCM."""

    media_types: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class EventStream:
    """A ``text/event-stream`` response; each event's data is one ``event_type`` as JSON.

    ``event_type`` is usually an ``Annotated`` union tagged by a ``type`` field;
    ``name`` is its schema name under ``components``.
    """

    name: str
    event_type: Any
    description: str


Body = Union[JsonBody, BinaryBody, EventStream]


@dataclass(frozen=True)
class HttpOperation:
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    # The service Protocol method this operation carries.
    operation_id: str
    summary: str
    query: Optional[type[BaseModel]] = None
    request: Optional[Body] = None
    # ``None``: 204 No Content.
    response: Optional[Body] = None


@dataclass(frozen=True)
class HttpApi:
    title: str
    description: str
    # The layer's service Protocol; every method has exactly one operation.
    service: type
    operations: tuple[HttpOperation, ...]


def health_operation() -> HttpOperation:
    """``GET /health``: every service reports ``contract_version`` (ADR 0027)."""
    return HttpOperation("GET", "/health", "health", "Contract version and readiness",
                         response=JsonBody(ServiceHealth))


def engine_operation(settings: type[BaseModel]) -> HttpOperation:
    """``PUT /engine``: the console switches the service's engine (spec decision 8)."""
    return HttpOperation("PUT", "/engine", "apply_engine",
                         "Load an engine, then switch to it; the current one stays on failure",
                         request=JsonBody(settings), response=JsonBody(settings))


def openapi_document(api: HttpApi) -> dict[str, Any]:
    """The OpenAPI 3.1 document of one layer service, ready for ``json.dumps``."""
    named: dict[str, Any] = {"ErrorBody": ErrorBody}
    for operation in api.operations:
        if operation.query is not None:
            named[operation.query.__name__] = operation.query
        for body in (operation.request, operation.response):
            if isinstance(body, JsonBody):
                named[body.model.__name__] = body.model
            elif isinstance(body, EventStream):
                named[body.name] = body.event_type
    keys = sorted(named)
    refs, definitions = TypeAdapter.json_schemas(
        [(key, "validation", TypeAdapter(named[key])) for key in keys], ref_template=_REF)
    schemas: dict[str, Any] = dict(definitions.get("$defs", {}))
    for key in keys:
        schema = refs[(key, "validation")]
        if schema != {"$ref": _REF.format(model=key)}:
            schemas[key] = schema  # an unnamed type such as a tagged union
    paths: dict[str, dict[str, Any]] = {}
    for operation in api.operations:
        paths.setdefault(operation.path, {})[operation.method.lower()] = _operation(operation)
    return {
        "openapi": "3.1.0",
        "info": {"title": api.title, "description": api.description,
                 "version": CONTRACT_VERSION},
        "paths": paths,
        "components": {"schemas": dict(sorted(schemas.items()))},
    }


def _operation(operation: HttpOperation) -> dict[str, Any]:
    document: dict[str, Any] = {"operationId": operation.operation_id,
                                "summary": operation.summary}
    if operation.query is not None:
        schema = operation.query.model_json_schema(ref_template=_REF)
        required = set(schema.get("required", ()))
        document["parameters"] = [
            {"name": name, "in": "query", "required": name in required, "schema": field}
            for name, field in schema["properties"].items()
        ]
    if operation.request is not None:
        document["requestBody"] = {"required": True, "content": _content(operation.request)}
    if operation.response is None:
        ok = {"204": {"description": "Done"}}
    else:
        ok = {"200": {"description": "OK", "content": _content(operation.response)}}
    document["responses"] = {
        **ok,
        "default": {"description": "Refused or failed; `detail` is shown to operators",
                    "content": {"application/json": {"schema": _ref("ErrorBody")}}},
    }
    return document


def _content(body: Body) -> dict[str, Any]:
    if isinstance(body, JsonBody):
        return {"application/json": {"schema": _ref(body.model.__name__)}}
    if isinstance(body, EventStream):
        # OpenAPI 3.1 cannot describe one stream item; the schema is each
        # event's ``data:`` payload.
        return {"text/event-stream": {"description": body.description,
                                      "schema": _ref(body.name)}}
    return {media_type: {"description": body.description,
                         "schema": {"type": "string", "format": "binary"}}
            for media_type in body.media_types}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": _REF.format(model=name)}


__all__ = [
    "BinaryBody",
    "EventStream",
    "HttpApi",
    "HttpOperation",
    "JsonBody",
    "engine_operation",
    "health_operation",
    "openapi_document",
]
