# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's entry point: ``LlmService`` served in-process (ADR 0027).

The core reaches the answer model, handoff decisions, AI greetings, the
weather tool, RAGFlow, public web search and the owned llama-server only
through this module and ``config_section``; everything else under
``nova_llm``, ``nova_llm.ragflow`` and ``nova_llm.web_search`` is internal
(import-linter contract ``llm-internals-private``).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from openai import OpenAI

from nova_contracts import CONTRACT_VERSION
from nova_contracts.common import ServiceError, ServiceHealth
from nova_contracts.llm import (
    ChatMessage,
    ContextCapacity,
    ContextCapacityExceeded,
    ContextCapacityQuery,
    DocumentsQuery,
    FragmentReviewRequest,
    FragmentVerdict,
    GpuOffload,
    Greeting,
    GreetingReceipt,
    GreetingRequest,
    HandoffDecision,
    HandoffRequest,
    HistoryLimit,
    BoardReceipt,
    LlmEngineSettings,
    LlmService,
    LlmSession,
    LlmSettings,
    LocalModel,
    LocalModels,
    LocalModelsQuery,
    LocalServer,
    LocalServerQuery,
    LocalServerSettings,
    LocalServerStatus,
    MemoryQuery,
    Outcome,
    PrewarmRequest,
    PrewarmResult,
    RagFlowDatasets,
    RagFlowDocuments,
    RagFlowStatus,
    ReplyEvent,
    ReplyRequest,
    ReplyRules,
    Retrieval,
    RetrievalRequest,
    SessionHistory,
    SessionMemory,
    SessionProfile,
    SessionRecords,
    SessionRef,
    SpokenTurn,
    TurnCommit,
    TurnRef,
    WeatherQuery,
    WeatherReport,
    WeatherTool,
    WebSearchPlan,
    WebSearchPlanRequest,
    WebSearchRequest,
    WebSearchResult,
    WebSummary,
    WebSummaryRequest,
)
from nova_llm import greeting as greetings
from nova_llm import llamacpp
from nova_llm.context_usage import ContextCapacityError, deployed_capacity
from nova_llm.handoff import HandoffContext, RoleCandidate, RoutingClients, RoutingError, route
from nova_llm.prewarm import prewarm_local_llm
from nova_llm.reply_events import review_fragment
from nova_llm.request_context import RequestQuestion
from nova_llm.service import EngineFactory, LlmSessions
from nova_llm.engines import DEFAULT_ENGINE, ENGINES
from nova_llm.tools.weather import CwaWeather, WeatherQuery as CwaQuery, weather_prompt
from nova_llm.ragflow.client import MANAGEMENT_URL, RagFlowClient, RagFlowError, close_shared_session, retrieval_prompt
from nova_core.utils.logging import logger
from nova_llm.web_search import planner, synthesis
from nova_llm.web_search import service as web


class InProcessLlmService:
    """The answer model and its tools, with every conversation's memory in this process."""

    def __init__(
        self,
        *,
        create_engine: Optional[EngineFactory] = None,
        routing_client_factory: Callable[..., Any] = OpenAI,
        weather: Optional[CwaWeather] = None,
        generate_greeting: Optional[Callable] = None,
    ) -> None:
        # By default each conversation's engine is the one its settings select.
        self._sessions = LlmSessions(create_engine or _create_selected_engine)
        # Every turn routes through the same pooled clients; worker threads
        # may route concurrently.
        self._routing_clients = RoutingClients(routing_client_factory)
        self._weather = weather or CwaWeather()
        # Replaces the greeting's model call (``generate(config, messages)``).
        self._generate_greeting = generate_greeting

    def health(self) -> ServiceHealth:
        return ServiceHealth(contract_version=CONTRACT_VERSION, engine="openai-compatible",
                             ready=True)

    def apply_engine(self, settings: LlmEngineSettings) -> LlmEngineSettings:
        self._sessions.switch_endpoint(
            model=settings.model,
            base_url=settings.base_url or None,
            extra_body=settings.extra_body,
            api_key=settings.api_key or None,
            max_tokens=settings.max_tokens,
            response_max_chars=settings.response_max_chars,
            system_prompt=settings.system_prompt,
            reset_history=settings.reset_history,
        )
        return settings

    # ------------------------------------------------------------ replies

    def reply(self, request: ReplyRequest) -> Iterator[ReplyEvent]:
        session = request.session
        config = _config_view(session, request.rules)
        if config.llm.engine == DEFAULT_ENGINE:
            _ensure_local_server(config)
        llm, greeting = self._sessions.prepare_reply(session.session_id, config)
        rag_context = _reply_context(request)
        if greeting:
            rag_context += "\n最近一次實際播出的招呼（只供理解訪客追問）：\n" + greeting
        message = _message(request)
        turn_id = request.turn_id or uuid4().hex
        transaction = llm.begin_history_turn(message, turn_id=turn_id)
        try:
            yield from llm.reply_events(
                message,
                turn_id=turn_id,
                rules_snapshot=request.rules,
                history_transaction=transaction,
                reply_mode=request.reply_mode,
                report_mode=request.report_mode,
                report_board=request.report_board,
                incremental_board=request.incremental_board,
                stream_speech=request.stream_speech,
                rag_context=rag_context,
            )
        except ContextCapacityError as exc:
            raise ContextCapacityExceeded(str(exc)) from exc
        except Exception as exc:
            logger.error("LLM service failed: %s", type(exc).__name__)
            raise

    def review_fragment(self, request: FragmentReviewRequest) -> FragmentVerdict:
        return review_fragment(request.context, request.state, request.fragment)

    # ------------------------------------------------------------ memory

    def begin_turn(self, request: SpokenTurn) -> None:
        self._sessions.begin_turn(request.session.session_id, _config_view(request.session),
                                  request.question, request.turn_id)

    def commit_turn(self, request: TurnCommit) -> Outcome:
        return Outcome(done=self._sessions.commit_turn(
            request.session_id, request.turn_id, assistant_text=request.assistant_text,
            terminal_reason=request.terminal_reason))

    def discard_turn(self, request: TurnRef) -> Outcome:
        return Outcome(done=self._sessions.discard_turn(request.session_id, request.turn_id))

    def remember_greeting(self, request: GreetingReceipt) -> None:
        self._sessions.remember_greeting(request.session_id, request.text,
                                         profile_id=request.profile_id)

    def acknowledge_board_item(self, request: BoardReceipt) -> Outcome:
        return Outcome(done=self._sessions.acknowledge_board_item(
            request.session_id, turn_id=request.turn_id, board_id=request.board_id,
            item_index=request.item_index))

    def clear_history(self, request: SessionRef) -> None:
        self._sessions.clear(request.session_id, request.profile_id)

    def remove_session(self, request: SessionRef) -> None:
        self._sessions.remove(request.session_id)

    def select_profile(self, request: SessionProfile) -> None:
        self._sessions.select_profile(request.session_id, request.profile_id)

    def session_history(self, request: SessionRef) -> SessionHistory:
        return SessionHistory(messages=tuple(
            ChatMessage(role=message["role"], content=message["content"])
            for message in self._sessions.history(request.session_id, request.profile_id)))

    def session_memory(self, request: MemoryQuery) -> SessionMemory:
        return SessionMemory(**self._sessions.memory(request.session_id, request.limit,
                                                     request.profile_id))

    def set_history_limit(self, request: HistoryLimit) -> None:
        self._sessions.set_history_limit(request.session_id, request.limit)

    def has_session_records(self, request: SessionRef) -> SessionRecords:
        return SessionRecords(present=self._sessions.has_records(request.session_id))

    # ------------------------------------------------------------ handoff, greeting, weather

    def route_handoff(self, request: HandoffRequest) -> HandoffDecision:
        config = _settings_view(request.settings, locale=request.locale)
        members = [RoleCandidate(id=c.id, name=c.name, main=c.main, description=c.description,
                                 rules=c.rules, weather_site=c.weather_site)
                   for c in request.candidates]
        context = HandoffContext(
            current_role=request.current_role,
            history=[message.model_dump() for message in request.history],
            confirmed=dict(request.confirmed))
        try:
            decision = route(config, request.question, members, context,
                             clients=self._routing_clients, explain=request.explain)
        except RoutingError as exc:
            raise ServiceError(str(exc)) from exc
        return HandoffDecision(**decision)

    async def generate_greeting(self, request: GreetingRequest) -> Greeting:
        try:
            text = await greetings.generate_greeting(
                _settings_view(request.settings), request.prompt,
                min_chars=request.min_chars, max_chars=request.max_chars,
                generate=self._generate_greeting, timeout=request.timeout_seconds)
        except greetings.GreetingGenerationError as exc:
            raise ServiceError(str(exc)) from exc
        return Greeting(text=text)

    def weather_tool(self) -> WeatherTool:
        return WeatherTool(configured=bool(self._weather.configured))

    async def query_weather(self, query: WeatherQuery) -> WeatherReport:
        facts = await self._weather.query(CwaQuery(
            query.county, query.town, query.kind, query.start_date, query.end_date, query.as_of))
        return WeatherReport(facts=facts)

    # ------------------------------------------------------------ RAGFlow

    def ragflow_status(self) -> RagFlowStatus:
        return RagFlowStatus(configured=RagFlowClient().connection.configured,
                             management_url=MANAGEMENT_URL)

    async def list_ragflow_datasets(self) -> RagFlowDatasets:
        try:
            return RagFlowDatasets(datasets=tuple(await RagFlowClient().list_datasets()))
        except RagFlowError as exc:
            raise ServiceError(str(exc)) from exc

    async def list_ragflow_documents(self, query: DocumentsQuery) -> RagFlowDocuments:
        try:
            return RagFlowDocuments(page=await RagFlowClient().list_documents(
                query.dataset_id, page=query.page))
        except RagFlowError as exc:
            raise ServiceError(str(exc)) from exc

    async def retrieve(self, request: RetrievalRequest) -> Retrieval:
        try:
            result = await RagFlowClient().retrieve(
                request.question, list(request.dataset_ids),
                **({"document_ids": list(request.document_ids)} if request.document_ids else {}))
        except RagFlowError as exc:
            raise ServiceError(str(exc)) from exc
        return Retrieval.model_validate(result)

    # ------------------------------------------------------------ web search

    async def plan_web_search(self, request: WebSearchPlanRequest) -> WebSearchPlan:
        decision = await planner.plan(_settings_view(request.settings), request.question,
                                      list(request.previous_queries))
        return WebSearchPlan(**decision)

    async def search_web(self, request: WebSearchRequest) -> WebSearchResult:
        return WebSearchResult.model_validate(
            await web.search(request.query, list(request.allowed_domains)))

    async def summarize_web(self, request: WebSummaryRequest) -> WebSummary:
        selection = await synthesis.summarize(_settings_view(request.settings), request.question,
                                              request.result.model_dump())
        return WebSummary(selection=selection,
                          quote=synthesis.direct_quote(selection, request.locale))

    # ------------------------------------------------------------ owned llama-server

    def start_local_server(self, settings: LocalServerSettings) -> LocalServer:
        try:
            base_url = llamacpp.ensure_server(
                settings.model, extra_dir=settings.models_dir, host=settings.host,
                port=settings.port, ctx=settings.ctx, threads=settings.threads,
                allow_partial_offload=settings.allow_partial_offload)
        except Exception as exc:
            raise ServiceError(str(exc)) from exc
        return LocalServer(base_url=base_url)

    def stop_local_server(self) -> None:
        llamacpp.shutdown_llama_server()

    def local_server_status(self, query: LocalServerQuery) -> LocalServerStatus:
        return LocalServerStatus(**llamacpp.server_status(query.host, query.port))

    def local_server_offload(self) -> GpuOffload:
        offload = llamacpp.gpu_offload_status()
        return GpuOffload(known=False) if offload is None else GpuOffload(known=True, **offload)

    def list_local_models(self, query: LocalModelsQuery) -> LocalModels:
        binary = llamacpp.find_llama_server()
        return LocalModels(models=tuple(LocalModel(**item) for item in
                                        llamacpp.list_gguf_models(query.models_dir)),
                           binary=str(binary) if binary else "")

    def prewarm(self, request: PrewarmRequest) -> PrewarmResult:
        if request.settings.engine != DEFAULT_ENGINE:
            return PrewarmResult(ready=True)  # nothing to warm: no model server
        config = _settings_view(request.settings, rules=request.rules)
        return PrewarmResult(ready=prewarm_local_llm(config, timeout_seconds=request.timeout_seconds))

    def context_capacity(self, query: ContextCapacityQuery) -> ContextCapacity:
        return ContextCapacity(capacity=deployed_capacity(query.base_url))

    async def close_connections(self) -> None:
        # Turns have ended; release the connections retrieval reused across them.
        await close_shared_session()
        self._routing_clients.close()


def create_llm_service() -> LlmService:
    """The process's LLM service; the core creates one at startup and shares it.

    The in-process service owns the llama-server child process, so SIGINT and
    SIGTERM stop it too (even during model loading).
    """
    llamacpp.install_shutdown_handlers()
    return InProcessLlmService()


# ---------------------------------------------------------------- requests -> internals


class _AttachedQuestion(str):
    """Only the current request carries images; history keeps the text."""

    def __new__(cls, text, parts):
        value = super().__new__(cls, text)
        value.parts = list(parts)
        return value


def _message(request: ReplyRequest) -> str:
    question = request.question
    message: str = question.text
    if question.parts:
        message = _AttachedQuestion(question.text, question.parts)
    web_evidence = request.web
    if web_evidence is not None and web_evidence.result.sources:
        selection = web_evidence.selection.model_dump() if web_evidence.selection else None
        message = RequestQuestion(message, web.answer_instructions(
            web_evidence.result.model_dump(), selection,
            today=datetime.now().date().isoformat()))
        message.web_evidence = True
    return message


def _reply_context(request: ReplyRequest) -> str:
    """Retrieved knowledge, then the role's confirmed facts and weather, before the rules."""
    context = retrieval_prompt([chunk.model_dump() for chunk in request.retrieval])
    facts = request.role_context
    if request.weather is not None:
        facts += "\n" + weather_prompt(request.weather.facts)
    if facts:
        context += "\n" + facts
    return context


def _create_selected_engine(*, config, **options):
    """The model client of one conversation: the engine its settings name."""
    engine = ENGINES.get(config.llm.engine)
    if engine is None:
        raise ServiceError(f"unknown LLM engine: {config.llm.engine!r}")
    return engine(config=config, **options)


def _ensure_local_server(config) -> None:
    """Start the owned llama-server when the answer needs it and it is not running."""
    llm = config.llm
    if llm.provider != "llamacpp" or not llm.llamacpp_model:
        return
    if llamacpp.server_status(llm.llamacpp_host, llm.llamacpp_port)["running"]:
        return
    logger.warning("llama-server 未在執行，正在自動啟動...")
    llm.base_url = llamacpp.ensure_server(
        llm.llamacpp_model, extra_dir=llm.llamacpp_dir, host=llm.llamacpp_host,
        port=llm.llamacpp_port, ctx=llm.llamacpp_ctx, threads=llm.llamacpp_threads,
        allow_partial_offload=llm.llamacpp_allow_partial_offload)


def _settings_view(settings: LlmSettings, *, locale: Optional[str] = None,
                   rules: Optional[ReplyRules] = None, history_max_messages: int = 20,
                   profile_id: str = "", snapshot: bool = False):
    """The attribute-shaped configuration the layer's internals read."""
    profile = settings.assistant_profile
    server = settings.local_server
    llm = SimpleNamespace(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        provider=settings.provider,
        engine=settings.engine,
        extra_body=dict(settings.extra_body),
        response_max_chars=settings.response_max_chars,
        board=SimpleNamespace(enabled=True, max_items=settings.board_max_items),
        reply_rules=rules,
        system_prompt=settings.system_prompt,
        assistant_profile=SimpleNamespace(
            **profile.model_dump(exclude={"forbidden_self_names"}),
            forbidden_self_names=list(profile.forbidden_self_names)),
        llamacpp_model=server.model if server else "",
        llamacpp_dir=server.models_dir if server else "",
        llamacpp_host=server.host if server else "127.0.0.1",
        llamacpp_port=server.port if server else 8080,
        llamacpp_ctx=server.ctx if server else 8192,
        llamacpp_threads=server.threads if server else 0,
        llamacpp_allow_partial_offload=server.allow_partial_offload if server else False,
    )
    conversation = SimpleNamespace(locale=locale or profile.output_locale,
                                   history_max_messages=history_max_messages)
    return SimpleNamespace(llm=llm, conversation=conversation, profile_id=profile_id,
                           conversation_snapshot=snapshot)


def _config_view(session: LlmSession, rules: Optional[ReplyRules] = None):
    return _settings_view(session.settings, rules=rules,
                          history_max_messages=session.history_max_messages,
                          profile_id=session.profile_id, snapshot=session.snapshot)


__all__ = ["InProcessLlmService", "create_llm_service"]
