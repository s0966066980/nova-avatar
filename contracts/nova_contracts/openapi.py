# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""OpenAPI documents of the loopback services, generated from the Pydantic models.

The models are the single source (ADR 0028). The documents under
``contracts/openapi/`` are committed and CI checks they match this output.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from nova_contracts import llm, stt, tts
from nova_contracts.version import CONTRACT_VERSION

_REF = "#/components/schemas/"


class Health(BaseModel):
    status: str
    contract_version: str


class EngineRequest(BaseModel):
    engine: str


def _ref(name: str) -> dict[str, Any]:
    return {"$ref": _REF + name}


def _json(name: str) -> dict[str, Any]:
    return {"application/json": {"schema": _ref(name)}}


def _document(title: str, models: list[Any], paths: dict[str, Any]) -> dict[str, Any]:
    _, definitions = models_json_schema(
        [(model, "validation") for model in [Health, EngineRequest, *models]],
        ref_template=_REF + "{model}",
    )
    common = {
        "/health": {"get": {"operationId": "health", "responses": {"200": {
            "description": "The service is up and reports its contract version.",
            "content": _json("Health")}}}},
        "/engine": {"put": {"operationId": "set_engine", "requestBody": {
            "required": True, "content": _json("EngineRequest")},
            "responses": {"204": {"description": "The engine was switched."}}}},
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": CONTRACT_VERSION},
        "servers": [{"url": "http://127.0.0.1"}],
        "paths": {**common, **paths},
        "components": {"schemas": definitions.get("$defs", {})},
    }


def documents() -> dict[str, dict[str, Any]]:
    """File name -> OpenAPI document, for every service that may become a process."""
    stt_doc = _document("Nova Avatar STT service", [stt.TranscribeResult], {
        "/transcribe": {"post": {
            "operationId": "transcribe",
            "parameters": [{"name": "language", "in": "query", "required": False,
                            "schema": {"type": "string"}}],
            "requestBody": {"required": True, "content": {"application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}}}},
            "responses": {"200": {"description": "The recognized text.",
                                  "content": _json("TranscribeResult")}}}},
    })
    llm_doc = _document("Nova Avatar LLM service", [
        llm.ReplyRequest, llm.SpokenTextDelta, llm.ReplyModeEvent, llm.BoardEvent,
        llm.RetrievalSourcesEvent, llm.WebSourcesEvent, llm.ReplyDone,
        llm.HandoffRequest, llm.HandoffDecision, llm.GreetingRequest, llm.GreetingResult,
    ], {
        "/reply": {"post": {
            "operationId": "stream_reply",
            "requestBody": {"required": True, "content": _json("ReplyRequest")},
            "responses": {"200": {
                "description": "Server-sent events; each data line is one reply event. "
                               "The client closes the connection to cancel.",
                "content": {"text/event-stream": {"schema": {"oneOf": [
                    _ref(name) for name in ("SpokenTextDelta", "ReplyModeEvent", "BoardEvent",
                                            "RetrievalSourcesEvent", "WebSourcesEvent", "ReplyDone")],
                    "discriminator": {"propertyName": "type"}}}}}}}},
        "/route": {"post": {
            "operationId": "route",
            "requestBody": {"required": True, "content": _json("HandoffRequest")},
            "responses": {"200": {"description": "Who answers the turn.",
                                  "content": _json("HandoffDecision")}}}},
        "/greeting": {"post": {
            "operationId": "generate_greeting",
            "requestBody": {"required": True, "content": _json("GreetingRequest")},
            "responses": {"200": {"description": "One greeting.",
                                  "content": _json("GreetingResult")}}}},
    })
    tts_doc = _document("Nova Avatar TTS service", [tts.SynthesizeRequest], {
        "/synthesize": {"post": {
            "operationId": "synthesize",
            "requestBody": {"required": True, "content": _json("SynthesizeRequest")},
            "responses": {"200": {
                "description": "PCM, 16 kHz mono int16, chunked. The client closes the "
                               "connection to cancel.",
                "content": {"application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}}}}}}},
        "/flush": {"post": {"operationId": "flush", "responses": {
            "204": {"description": "Queued text was dropped."}}}},
    })
    return {"stt.json": stt_doc, "llm.json": llm_doc, "tts.json": tts_doc}


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
