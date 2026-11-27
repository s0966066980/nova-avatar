# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Answer-model (LLM) layer contract.

Loopback shape (spec decision 7): ``POST /reply`` streams server-sent events,
one tagged ``ReplyEvent`` per message. The LLM emits spoken-text deltas in
model order and does not cut playable fragments: the core cuts complete
semantic boundaries, applies the semantic wait and owns back pressure, then
asks ``POST /fragments/review`` whether each fragment may be played. Every
per-turn input travels with the request: the rules, the assistant profile, the
retrieved knowledge, the handoff context, the weather facts and the web
evidence (ADR 0027). The core cancels a reply by closing its connection.

Conversation memory is still kept by the layer for now (``/sessions/...``),
keyed by the core's session id; the core decides when a turn is committed,
discarded or forgotten.

Endpoint URLs, keys and model directories in these DTOs always come from the
configuration file's allowlist, resolved by the core (CODING_STANDARDS rule 1);
the service only ever listens on loopback.
"""
from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal, Optional, Protocol, Union, runtime_checkable

from pydantic import Field

from nova_contracts.common import ContractModel, ServiceError, ServiceHealth
from nova_contracts.http import (
    EventStream,
    HttpApi,
    HttpOperation,
    JsonBody,
    engine_operation,
    health_operation,
)

Provider = Literal["llamacpp", "ollama", "openai"]
ReplyMode = Literal["simple", "board", "auto"]


class ContextCapacityExceeded(ServiceError):
    """The conversation no longer fits the deployed context; the turn is not retried.

    The pending history of the turn is dropped; the core tells the visitor.
    """


# ---------------------------------------------------------------- settings


class AssistantProfile(ContractModel):
    """The console's assistant identity and output preferences."""

    assistant_name: str = ""
    system_prompt: str = ""
    restriction_prompt: str = ""
    output_locale: str = "zh-TW"
    enforce_output_locale: bool = True
    forbidden_self_names: tuple[str, ...] = ()


class ReplyRules(ContractModel):
    """One published version of the editable reply rules; the core validated it."""

    revision: int = 1
    activation: str
    speech: str
    board: str


class LocalServerSettings(ContractModel):
    """An owned llama-server: a GGUF name from the model list, served on loopback."""

    model: str
    # The configuration file's extra GGUF folder (``llm.llamacpp_dir``).
    models_dir: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    ctx: int = 8192
    threads: int = 0
    allow_partial_offload: bool = False


class LlmSettings(ContractModel):
    """The answer model one request uses: an allowlisted endpoint and its options."""

    provider: Provider
    base_url: str
    api_key: str = ""
    model: str
    extra_body: dict[str, Any] = Field(default_factory=dict)
    response_max_chars: int = 120
    board_max_items: int = 8
    # The effective prompt: the profile's, or the legacy ``llm.system_prompt``.
    system_prompt: str = ""
    assistant_profile: AssistantProfile = Field(default_factory=AssistantProfile)
    # Set for ``llamacpp``: the server is started when it is not running.
    local_server: Optional[LocalServerSettings] = None


class LlmSession(ContractModel):
    """One conversation as its requests name it; memory is keyed by these ids."""

    session_id: int
    profile_id: str = ""
    settings: LlmSettings
    history_max_messages: int = 20
    # A conversation fixed to a role or avatar profile; console model
    # switches (``PUT /engine``) leave it alone.
    snapshot: bool = False


class LlmEngineSettings(ContractModel):
    """``PUT /engine``: the console switched the published model or persona.

    Live conversations that are not snapshots follow it; unset fields keep
    their values.
    """

    model: str
    base_url: str = ""
    api_key: str = ""
    extra_body: Optional[dict[str, Any]] = None
    max_tokens: Optional[int] = None
    response_max_chars: Optional[int] = None
    system_prompt: Optional[str] = None
    reset_history: bool = False


# ---------------------------------------------------------------- reply inputs


class Question(ContractModel):
    """The visitor's question; ``parts`` are this request's OpenAI content parts.

    Attachments are sent only with the current request (images as data URLs);
    history keeps ``text``.
    """

    text: str
    parts: tuple[dict[str, Any], ...] = ()


class RetrievedChunk(ContractModel):
    content: str
    document_name: str = ""
    document_id: str = ""
    dataset_id: str = ""


class WebSource(ContractModel):
    id: str
    url: str
    title: str = ""
    snippet: str = ""
    text: str = ""
    kind: str = "snippet"
    engine: str = ""


class WebSearchResult(ContractModel):
    status: str
    query: str = ""
    sources: tuple[WebSource, ...] = ()
    fetched_at: str = ""
    reused: bool = False


class WebQuote(ContractModel):
    source_id: str
    quote: str


class WebEvidenceSelection(ContractModel):
    """The verified quotes chosen from a search; ``unavailable`` when none could be."""

    mode: str
    items: tuple[WebQuote, ...] = ()


class WebEvidence(ContractModel):
    """Public web references this answer must rely on."""

    result: WebSearchResult
    selection: Optional[WebEvidenceSelection] = None


class WeatherReport(ContractModel):
    """CWA facts for one accepted place and date range, as the console shows them."""

    facts: dict[str, Any]


class ReplyRequest(ContractModel):
    """``POST /reply``: generate one answer."""

    session: LlmSession
    question: Question
    rules: ReplyRules
    # The core's turn id; empty lets the layer name the turn (``ReplyStarted``).
    turn_id: str = ""
    reply_mode: Optional[ReplyMode] = None
    # Emit ``reply_mode``; without it an unspecified mode is a simple answer.
    report_mode: bool = False
    # Emit boards; otherwise board content is neither sent nor remembered.
    report_board: bool = False
    incremental_board: bool = False
    # Emit spoken deltas for the core to cut, review and play.
    stream_speech: bool = False
    retrieval: tuple[RetrievedChunk, ...] = ()
    # Facts the handoff decision confirmed for this role.
    role_context: str = ""
    weather: Optional[WeatherReport] = None
    web: Optional[WebEvidence] = None


# ---------------------------------------------------------------- reply events


class FragmentReviewContext(ContractModel):
    """What the layer needs to review one answer's fragments; the core echoes it back."""

    profile: AssistantProfile
    model: str = ""
    question: str = ""
    # Web speech stops once this many characters were accepted.
    web_max_chars: Optional[int] = None


class ReplyStarted(ContractModel):
    """The first event: the turn's id and how its fragments must be reviewed."""

    type: Literal["reply_started"] = "reply_started"
    turn_id: str
    review: FragmentReviewContext
    # Web speech is bounded at playable fragments even when none is played.
    bounded: bool = False
    # The live transcript shows reviewed fragments, never raw deltas.
    previews_fragments: bool = False


class ModelChunk(ContractModel):
    """The model produced chunk ``llm_sequence``; the core may cancel before it is used."""

    type: Literal["model_chunk"] = "model_chunk"
    llm_sequence: int


class SpokenDelta(ContractModel):
    """A spoken-text increment from one model chunk; not a playable fragment."""

    type: Literal["spoken_delta"] = "spoken_delta"
    text: str
    llm_sequence: int


class SpeechEnd(ContractModel):
    """The spoken section is complete: a boundary even without punctuation."""

    type: Literal["speech_end"] = "speech_end"


class ReplyModeChosen(ContractModel):
    type: Literal["reply_mode"] = "reply_mode"
    mode: ReplyMode


class BoardStart(ContractModel):
    type: Literal["board_start"] = "board_start"
    turn_id: str
    title: str


class BoardItemShown(ContractModel):
    """One incrementally parsed board item."""

    type: Literal["board_item"] = "board_item"
    turn_id: str
    index: int
    title: str
    body: str


class BoardEntry(ContractModel):
    title: str
    content: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None


class Board(ContractModel):
    """The complete board; the layer remembers it once a presenter shows an item."""

    type: Literal["board"] = "board"
    turn_id: str
    title: str
    summary: Optional[str] = None
    items: tuple[BoardEntry, ...] = ()
    # Its items were already sent one by one.
    incremental: bool = False


class ReplyDone(ContractModel):
    """The last event. The core's reviewed speech wins over ``spoken`` when there is any."""

    type: Literal["reply_done"] = "reply_done"
    # The cleaned spoken section, as the layer itself heard it.
    spoken: str
    # The cleaned visible reply; empty when structured data was suppressed.
    visible: str


SpeechEvent = Annotated[Union[SpokenDelta, SpeechEnd], Field(discriminator="type")]
ReplyEvent = Annotated[
    Union[ReplyStarted, ModelChunk, SpokenDelta, SpeechEnd, ReplyModeChosen,
          BoardStart, BoardItemShown, Board, ReplyDone],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- fragment review


class ReviewedFragment(ContractModel):
    """A playable fragment the LLM accepted, with its live-transcript increment."""

    text: str
    preview: str


class ReviewState(ContractModel):
    """One answer's review so far; the core keeps it and sends it with the next fragment."""

    accepted: tuple[str, ...] = ()
    # The web bound was reached: nothing more is played.
    stopped: bool = False


class FragmentReviewRequest(ContractModel):
    context: FragmentReviewContext
    state: ReviewState = Field(default_factory=ReviewState)
    fragment: str


class FragmentVerdict(ContractModel):
    # ``None``: the fragment must stay silent.
    fragment: Optional[ReviewedFragment] = None
    state: ReviewState
    # The cleaned spoken answer made of every accepted fragment.
    answer: str = ""


class FragmentReview(Protocol):
    """The review of one answer's fragments as the core's fragmenter uses it.

    In process only: the core implements it over ``LlmService.review_fragment``.
    It may be called from the core's timer thread.
    """

    @property
    def bounded(self) -> bool: ...

    @property
    def previews_fragments(self) -> bool: ...

    def review(self, fragment: str) -> Optional[ReviewedFragment]: ...


class SpeechSink(Protocol):
    """The core's consumer of one answer's speech (in process only)."""

    def open(self, review: FragmentReview) -> None: ...

    def send(self, event: SpeechEvent) -> None: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------- conversation memory


class SessionRef(ContractModel):
    """A conversation, and optionally one role's memory in it.

    ``profile_id`` ``None`` means the role currently selected (or, for
    clearing, every role); ``""`` is a conversation without roles.
    """

    session_id: int
    profile_id: Optional[str] = None


class SpokenTurn(ContractModel):
    """A fixed reply (handoff announcement, failure) enters history when played."""

    session: LlmSession
    question: str
    turn_id: str


class TurnCommit(ContractModel):
    session_id: int
    turn_id: str
    # Exactly what crossed the playback boundary.
    assistant_text: str = ""
    terminal_reason: str


class TurnRef(ContractModel):
    session_id: int
    turn_id: str


class Outcome(ContractModel):
    """Whether the operation found something to change."""

    done: bool


class GreetingReceipt(ContractModel):
    """The greeting actually played; a later question may refer to it."""

    session_id: int
    profile_id: str = ""
    text: str


class BoardReceipt(ContractModel):
    """A presenter rendered one board item; only shown items become context."""

    session_id: int
    turn_id: str
    board_id: str
    item_index: int
    presenter: str


class SessionProfile(ContractModel):
    session_id: int
    profile_id: str = ""


class ChatMessage(ContractModel):
    role: str
    content: Any


class SessionHistory(ContractModel):
    messages: tuple[ChatMessage, ...] = ()


class MemoryQuery(ContractModel):
    session_id: int
    limit: int = 20
    profile_id: Optional[str] = None


class SessionMemory(ContractModel):
    retained_messages: int = 0
    max_messages: int = 20
    pending_max_messages: Optional[int] = None
    evicted_messages: int = 0
    oldest_message: Optional[Any] = None
    oldest_message_number: Optional[int] = None
    # The last request's context usage, as the console shows it.
    context: Optional[dict[str, Any]] = None


class HistoryLimit(ContractModel):
    session_id: int
    limit: int


class SessionRecords(ContractModel):
    """Whether any role of the conversation remembers a message or a board."""

    present: bool


# ---------------------------------------------------------------- handoff, greeting, weather


class RoleCandidate(ContractModel):
    """One role that may answer a turn, as the core's role composition defines it."""

    id: str
    name: str
    main: bool
    description: str = ""
    rules: str = ""
    # The site's default place (county, town); only on the weather tool's holder.
    weather_site: Optional[dict[str, str]] = None


class HandoffRequest(ContractModel):
    """``POST /handoff``: which role answers ``question``."""

    settings: LlmSettings
    locale: str = "zh-TW"
    question: str
    candidates: tuple[RoleCandidate, ...]
    current_role: str
    # The current role's recent conversation.
    history: tuple[ChatMessage, ...] = ()
    # The place this conversation last confirmed for a weather lookup.
    confirmed: dict[str, str] = Field(default_factory=dict)
    # The console's dry run also asks for a short reason.
    explain: bool = False


class HandoffDecision(ContractModel):
    """``target`` is a candidate id, or ``None`` to ask the visitor first."""

    target: Optional[str] = None
    clarification: str = ""
    context: str = ""
    county: str = ""
    town: str = ""
    kind: str = ""
    start_date: str = ""
    end_date: str = ""
    accepted_at: str = ""
    decided_by: str = ""
    reason: Optional[str] = None


class GreetingRequest(ContractModel):
    """``POST /greeting``: one history-free AI greeting."""

    settings: LlmSettings
    prompt: str
    min_chars: int
    max_chars: int
    timeout_seconds: float = 15.0


class Greeting(ContractModel):
    text: str


class WeatherTool(ContractModel):
    configured: bool


class WeatherQuery(ContractModel):
    county: str
    town: str = ""
    kind: str = "forecast"
    start_date: str
    end_date: str
    # When the handoff decision accepted the place.
    as_of: str = ""


# ---------------------------------------------------------------- RAGFlow


class RagFlowStatus(ContractModel):
    configured: bool
    management_url: str


class RagFlowDatasets(ContractModel):
    datasets: tuple[dict[str, Any], ...] = ()


class DocumentsQuery(ContractModel):
    dataset_id: str
    page: int = 1


class RagFlowDocuments(ContractModel):
    """One page of a dataset's documents, as RAGFlow's console listing shows it."""

    page: dict[str, Any]


class RetrievalRequest(ContractModel):
    question: str
    dataset_ids: tuple[str, ...]
    # Empty: every document of the datasets.
    document_ids: tuple[str, ...] = ()


class Retrieval(ContractModel):
    status: str
    sources: tuple[RetrievedChunk, ...] = ()


# ---------------------------------------------------------------- web search


class WebSearchPlanRequest(ContractModel):
    settings: LlmSettings
    question: str
    previous_queries: tuple[str, ...] = ()


class WebSearchPlan(ContractModel):
    search: bool
    query: str = ""
    reuse: bool = False


class WebSearchRequest(ContractModel):
    query: str
    allowed_domains: tuple[str, ...] = ()


class WebSummaryRequest(ContractModel):
    settings: LlmSettings
    question: str
    result: WebSearchResult
    # The conversation language decides whether a quote can be spoken as is.
    locale: str = "zh-TW"


class WebSummary(ContractModel):
    selection: WebEvidenceSelection
    # A single verified quote that answers the question by itself.
    quote: Optional[str] = None


# ---------------------------------------------------------------- local llama-server


class LocalServer(ContractModel):
    base_url: str


class LocalServerQuery(ContractModel):
    host: str = "127.0.0.1"
    port: int = 8080


class LocalServerStatus(ContractModel):
    running: bool
    owned: bool = False
    loaded_model: Optional[str] = None
    base_url: str = ""
    binary: str = ""


class GpuOffload(ContractModel):
    """Whether the owned llama-server runs every layer on the GPU; ``known`` false before one ran."""

    known: bool
    full: bool = False
    gpu_layers: int = 0
    total_layers: int = 0
    error: str = ""


class LocalModelsQuery(ContractModel):
    models_dir: str = ""


class LocalModel(ContractModel):
    name: str
    path: str
    size: int
    size_label: str = ""
    family: str = "gguf"
    parameter_size: str = ""


class LocalModels(ContractModel):
    models: tuple[LocalModel, ...] = ()
    # The llama-server executable found, or "".
    binary: str = ""


class PrewarmRequest(ContractModel):
    settings: LlmSettings
    rules: ReplyRules
    timeout_seconds: float = 25.0


class PrewarmResult(ContractModel):
    ready: bool


class ContextCapacityQuery(ContractModel):
    base_url: str


class ContextCapacity(ContractModel):
    # The deployed n_ctx, or ``None`` when the server does not say.
    capacity: Optional[int] = None


# ---------------------------------------------------------------- the service


@runtime_checkable
class LlmService(Protocol):
    """The LLM layer as the core sees it; each method is one HTTP operation.

    Expected failures raise ``ServiceError`` (``ContextCapacityExceeded`` for
    an overflowing conversation) with a message for operators.
    """

    def health(self) -> ServiceHealth:
        """``GET /health``."""
        ...

    def apply_engine(self, settings: LlmEngineSettings) -> LlmEngineSettings:
        """``PUT /engine``: point live, non-snapshot conversations at the published model."""
        ...

    def reply(self, request: ReplyRequest) -> Iterator[ReplyEvent]:
        """``POST /reply``: stream one answer's events; closing the stream cancels it."""
        ...

    def review_fragment(self, request: FragmentReviewRequest) -> FragmentVerdict:
        """``POST /fragments/review``: may this complete fragment be played?"""
        ...

    def begin_turn(self, request: SpokenTurn) -> None:
        """``POST /sessions/turns``: a fixed reply's turn, committed once played."""
        ...

    def commit_turn(self, request: TurnCommit) -> Outcome:
        """``POST /sessions/turns/commit``: commit what was played of a pending turn."""
        ...

    def discard_turn(self, request: TurnRef) -> Outcome:
        """``POST /sessions/turns/discard``: drop an answer that was never played."""
        ...

    def remember_greeting(self, request: GreetingReceipt) -> None:
        """``PUT /sessions/greeting``: replace the conversation's last played greeting."""
        ...

    def acknowledge_board_item(self, request: BoardReceipt) -> Outcome:
        """``POST /sessions/board/receipts``: a presenter rendered one board item."""
        ...

    def clear_history(self, request: SessionRef) -> None:
        """``POST /sessions/clear``: forget messages, boards and greetings."""
        ...

    def remove_session(self, request: SessionRef) -> None:
        """``DELETE /sessions``: the conversation ended."""
        ...

    def select_profile(self, request: SessionProfile) -> None:
        """``PUT /sessions/profile``: the role now answering, without erasing any memory."""
        ...

    def session_history(self, request: SessionRef) -> SessionHistory:
        """``GET /sessions/history``: one role's committed messages."""
        ...

    def session_memory(self, request: MemoryQuery) -> SessionMemory:
        """``GET /sessions/memory``: retention and context usage for the console."""
        ...

    def set_history_limit(self, request: HistoryLimit) -> None:
        """``PUT /sessions/history-limit``: retained messages for every role."""
        ...

    def has_session_records(self, request: SessionRef) -> SessionRecords:
        """``GET /sessions/records``: anything a greeting would interrupt?"""
        ...

    def route_handoff(self, request: HandoffRequest) -> HandoffDecision:
        """``POST /handoff``: which role answers the turn."""
        ...

    async def generate_greeting(self, request: GreetingRequest) -> Greeting:
        """``POST /greeting``: one bounded AI greeting."""
        ...

    def weather_tool(self) -> WeatherTool:
        """``GET /tools/weather``: whether the CWA key is configured."""
        ...

    async def query_weather(self, query: WeatherQuery) -> WeatherReport:
        """``POST /tools/weather``: CWA facts for an accepted place."""
        ...

    def ragflow_status(self) -> RagFlowStatus:
        """``GET /ragflow``."""
        ...

    async def list_ragflow_datasets(self) -> RagFlowDatasets:
        """``GET /ragflow/datasets``."""
        ...

    async def list_ragflow_documents(self, query: DocumentsQuery) -> RagFlowDocuments:
        """``GET /ragflow/documents``."""
        ...

    async def retrieve(self, request: RetrievalRequest) -> Retrieval:
        """``POST /ragflow/retrieval``: bounded knowledge-base retrieval."""
        ...

    async def plan_web_search(self, request: WebSearchPlanRequest) -> WebSearchPlan:
        """``POST /web/plan``: does the question need a public web search?"""
        ...

    async def search_web(self, request: WebSearchRequest) -> WebSearchResult:
        """``POST /web/search``: bounded public search and page reads."""
        ...

    async def summarize_web(self, request: WebSummaryRequest) -> WebSummary:
        """``POST /web/summary``: verified quotes for the question."""
        ...

    def start_local_server(self, settings: LocalServerSettings) -> LocalServer:
        """``POST /local-server``: start (or reuse) the owned llama-server."""
        ...

    def stop_local_server(self) -> None:
        """``DELETE /local-server``: stop the owned llama-server, never an external one."""
        ...

    def local_server_status(self, query: LocalServerQuery) -> LocalServerStatus:
        """``GET /local-server``: probe a llama-server's health."""
        ...

    def local_server_offload(self) -> GpuOffload:
        """``GET /local-server/offload``: the owned server's GPU offload, without probing."""
        ...

    def list_local_models(self, query: LocalModelsQuery) -> LocalModels:
        """``GET /local-server/models``: GGUF files and the llama-server executable."""
        ...

    def prewarm(self, request: PrewarmRequest) -> PrewarmResult:
        """``POST /prewarm``: prefill the local model's prompt before the first visitor."""
        ...

    def context_capacity(self, query: ContextCapacityQuery) -> ContextCapacity:
        """``GET /context-capacity``: the deployed context size."""
        ...

    async def close_connections(self) -> None:
        """``POST /connections/close``: release pooled clients before shutdown."""
        ...


def _op(method, path, operation_id, summary, *, query=None, request=None, response=None):
    return HttpOperation(method, path, operation_id, summary, query=query,
                         request=None if request is None else JsonBody(request),
                         response=None if response is None else JsonBody(response))


HTTP_API = HttpApi(
    title="Nova Avatar LLM service",
    description=("Loopback answer model. The reply streams server-sent events; the core "
                 "cancels a reply by closing its connection."),
    service=LlmService,
    operations=(
        health_operation(),
        engine_operation(LlmEngineSettings),
        HttpOperation("POST", "/reply", "reply", "Stream one answer's events",
                      request=JsonBody(ReplyRequest),
                      response=EventStream("ReplyEvent", ReplyEvent,
                                           "One ReplyEvent per message, reply_started first "
                                           "and reply_done last")),
        _op("POST", "/fragments/review", "review_fragment", "Review one playable fragment",
            request=FragmentReviewRequest, response=FragmentVerdict),
        _op("POST", "/sessions/turns", "begin_turn", "Open a fixed reply's history turn",
            request=SpokenTurn),
        _op("POST", "/sessions/turns/commit", "commit_turn", "Commit what was played",
            request=TurnCommit, response=Outcome),
        _op("POST", "/sessions/turns/discard", "discard_turn", "Drop an unplayed answer",
            request=TurnRef, response=Outcome),
        _op("PUT", "/sessions/greeting", "remember_greeting", "Remember the played greeting",
            request=GreetingReceipt),
        _op("POST", "/sessions/board/receipts", "acknowledge_board_item",
            "Record a rendered board item", request=BoardReceipt, response=Outcome),
        _op("POST", "/sessions/clear", "clear_history", "Forget a conversation's content",
            request=SessionRef),
        _op("DELETE", "/sessions", "remove_session", "Forget a conversation", query=SessionRef),
        _op("PUT", "/sessions/profile", "select_profile", "Select the answering role",
            request=SessionProfile),
        _op("GET", "/sessions/history", "session_history", "One role's committed messages",
            query=SessionRef, response=SessionHistory),
        _op("GET", "/sessions/memory", "session_memory", "Retention and context usage",
            query=MemoryQuery, response=SessionMemory),
        _op("PUT", "/sessions/history-limit", "set_history_limit", "Retained messages",
            request=HistoryLimit),
        _op("GET", "/sessions/records", "has_session_records", "Anything remembered",
            query=SessionRef, response=SessionRecords),
        _op("POST", "/handoff", "route_handoff", "Decide which role answers",
            request=HandoffRequest, response=HandoffDecision),
        _op("POST", "/greeting", "generate_greeting", "Write one AI greeting",
            request=GreetingRequest, response=Greeting),
        _op("GET", "/tools/weather", "weather_tool", "Weather tool readiness",
            response=WeatherTool),
        _op("POST", "/tools/weather", "query_weather", "CWA facts for an accepted place",
            request=WeatherQuery, response=WeatherReport),
        _op("GET", "/ragflow", "ragflow_status", "RAGFlow configuration",
            response=RagFlowStatus),
        _op("GET", "/ragflow/datasets", "list_ragflow_datasets", "Knowledge bases",
            response=RagFlowDatasets),
        _op("GET", "/ragflow/documents", "list_ragflow_documents", "A dataset's documents",
            query=DocumentsQuery, response=RagFlowDocuments),
        _op("POST", "/ragflow/retrieval", "retrieve", "Retrieve knowledge for a question",
            request=RetrievalRequest, response=Retrieval),
        _op("POST", "/web/plan", "plan_web_search", "Decide whether to search the web",
            request=WebSearchPlanRequest, response=WebSearchPlan),
        _op("POST", "/web/search", "search_web", "Search public web pages",
            request=WebSearchRequest, response=WebSearchResult),
        _op("POST", "/web/summary", "summarize_web", "Select verified quotes",
            request=WebSummaryRequest, response=WebSummary),
        _op("POST", "/local-server", "start_local_server", "Start the owned llama-server",
            request=LocalServerSettings, response=LocalServer),
        _op("DELETE", "/local-server", "stop_local_server", "Stop the owned llama-server"),
        _op("GET", "/local-server", "local_server_status", "Probe a llama-server",
            query=LocalServerQuery, response=LocalServerStatus),
        _op("GET", "/local-server/offload", "local_server_offload", "GPU offload of the owned server",
            response=GpuOffload),
        _op("GET", "/local-server/models", "list_local_models", "GGUF models",
            query=LocalModelsQuery, response=LocalModels),
        _op("POST", "/prewarm", "prewarm", "Prefill the local prompt",
            request=PrewarmRequest, response=PrewarmResult),
        _op("GET", "/context-capacity", "context_capacity", "Deployed context size",
            query=ContextCapacityQuery, response=ContextCapacity),
        _op("POST", "/connections/close", "close_connections", "Release pooled clients"),
    ),
)


__all__ = [
    "AssistantProfile",
    "Board",
    "BoardEntry",
    "BoardItemShown",
    "BoardReceipt",
    "BoardStart",
    "ChatMessage",
    "ContextCapacity",
    "ContextCapacityExceeded",
    "ContextCapacityQuery",
    "DocumentsQuery",
    "FragmentReview",
    "FragmentReviewContext",
    "FragmentReviewRequest",
    "FragmentVerdict",
    "GpuOffload",
    "Greeting",
    "GreetingReceipt",
    "GreetingRequest",
    "HTTP_API",
    "HandoffDecision",
    "HandoffRequest",
    "HistoryLimit",
    "LlmEngineSettings",
    "LlmService",
    "LlmSession",
    "LlmSettings",
    "LocalModel",
    "LocalModels",
    "LocalModelsQuery",
    "LocalServer",
    "LocalServerQuery",
    "LocalServerSettings",
    "LocalServerStatus",
    "MemoryQuery",
    "ModelChunk",
    "Outcome",
    "PrewarmRequest",
    "PrewarmResult",
    "Provider",
    "Question",
    "RagFlowDatasets",
    "RagFlowDocuments",
    "RagFlowStatus",
    "ReplyDone",
    "ReplyEvent",
    "ReplyMode",
    "ReplyModeChosen",
    "ReplyRequest",
    "ReplyRules",
    "ReplyStarted",
    "RetrievalRequest",
    "Retrieval",
    "RetrievedChunk",
    "ReviewState",
    "ReviewedFragment",
    "RoleCandidate",
    "SessionHistory",
    "SessionMemory",
    "SessionProfile",
    "SessionRecords",
    "SessionRef",
    "SpeechEnd",
    "SpeechEvent",
    "SpeechSink",
    "SpokenDelta",
    "SpokenTurn",
    "TurnCommit",
    "TurnRef",
    "WeatherQuery",
    "WeatherReport",
    "WeatherTool",
    "WebEvidence",
    "WebEvidenceSelection",
    "WebQuote",
    "WebSearchPlan",
    "WebSearchPlanRequest",
    "WebSearchRequest",
    "WebSearchResult",
    "WebSource",
    "WebSummary",
    "WebSummaryRequest",
]
