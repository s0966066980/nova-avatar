# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reply mode router: determines whether a user query requires SIMPLE or BOARD response mode.

Uses a Rule-First -> LLM-Fallback design to guarantee sub-millisecond routing
for clear cases while providing model-based precision for ambiguous queries.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


class ReplyMode(str, Enum):
    """Response mode for assistant replies."""

    SIMPLE = "simple"
    BOARD = "board"
    AMBIGUOUS = "ambiguous"  # Internal router state only; never sent to frontend
    AUTO = "auto"  # The single answer generation chooses the mode.


class ReplyModePreference(str, Enum):
    """User/API preference for reply mode routing."""

    AUTO = "auto"
    SIMPLE = "simple"
    BOARD = "board"


@dataclass(frozen=True)
class ReplyRoute:
    """Routing outcome for a single conversation turn."""

    mode: ReplyMode
    source: str  # "rule" | "llm" | "fallback" | "forced"
    score: float
    reason: str
    latency_ms: float = 0.0


# ----------------------------------------------------------------------
# Rule Router Intent Dictionaries & Patterns
# ----------------------------------------------------------------------

# BOARD positive intents
BOARD_LIST_INTENTS = (
    "列出",
    "幫我列",
    "幫列",
    "整理",
    "清單",
    "checklist",
    "roadmap",
    "幾種",
    "幾個",
    "分成",
    "條列",
    "有哪些",
    "有哪幾種",
    "有哪幾項",
    "有甚麼項目",
    "有什麼項目",
    "哪些",
    "有幾點",
    "有哪幾點",
)

BOARD_COMPARE_INTENTS = (
    "比較",
    "差異",
    "優缺點",
    "優劣",
    "差在哪",
    "差別",
    "有何不同",
    "vs",
    "a/b",
    "matrix",
    "表格",
    "對比",
)

BOARD_PROCESS_INTENTS = (
    "步驟",
    "流程",
    "規劃",
    "路線",
    "roadmap",
    "階段",
    "sop",
    "開發流程",
    "建置流程",
    "部署流程",
)

BOARD_RECOMMEND_CHOICE_INTENTS = (
    "建議幾個",
    "推薦幾個",
    "建議",
    "推薦",
    "有哪些方法",
    "方法",
    "方案",
    "選項",
    "策略",
    "如何選擇",
    "怎麼選",
    "選哪個",
    "我該怎麼選",
)

BOARD_STRUCTURE_INTENTS = (
    "架構",
    "結構",
    "規格",
    "功能清單",
    "功能列表",
    "項目",
    "模組",
    "skill",
    "技能",
)

# SIMPLE positive intents
SIMPLE_GREETINGS = (
    "你好",
    "您好",
    "早安",
    "午安",
    "晚安",
    "哈囉",
    "嗨",
    "hello",
    "hi",
    "hey",
    "在嗎",
    "謝謝",
    "感謝",
    "再見",
    "掰掰",
    "拜拜",
)

SIMPLE_FACT_OR_DEF = (
    "是什麼",
    "何謂",
    "意思是",
    "代表什麼",
    "定義",
    "含義",
    "幾點了",
    "現在幾點",
    "今天幾號",
    "天氣",
)

SIMPLE_CONFIRMATION_OR_YESNO = (
    "可以嗎",
    "對嗎",
    "是不是",
    "要錢嗎",
    "免費嗎",
    "好不好",
    "行嗎",
    "行不行",
    "成嗎",
    "會不會",
)

SIMPLE_SHORT_QUERIES = (
    "為什麼",
    "怎麼了",
    "甚麼意思",
    "什麼意思",
    "為啥",
    "怎麼會這樣",
)


class RuleRouter:
    """Score-based rule router for response mode routing.

    Scores >= board_threshold -> BOARD
    Scores <= simple_threshold -> SIMPLE
    Otherwise -> AMBIGUOUS
    """

    def __init__(
        self,
        *,
        board_threshold: float = 3.0,
        simple_threshold: float = 0.0,
    ) -> None:
        self.board_threshold = float(board_threshold)
        self.simple_threshold = float(simple_threshold)

    def evaluate(self, message: str) -> tuple[ReplyMode, float, str]:
        text = (message or "").strip().lower()
        if not text:
            return ReplyMode.SIMPLE, 0.0, "empty query"

        # Pure greeting check
        cleaned_greeting = re.sub(r"[!?,.。？！~\s]", "", text)
        if cleaned_greeting in SIMPLE_GREETINGS or text in SIMPLE_GREETINGS:
            return ReplyMode.SIMPLE, -10.0, "pure greeting"

        score = 0.0
        reasons: list[str] = []

        # 1. BOARD intents
        matched_list = [w for w in BOARD_LIST_INTENTS if w in text]
        if matched_list:
            score += 3.0
            reasons.append(f"list_intent({','.join(matched_list)})")

        matched_compare = [w for w in BOARD_COMPARE_INTENTS if w in text]
        if matched_compare:
            score += 3.0
            reasons.append(f"compare_intent({','.join(matched_compare)})")

        matched_process = [w for w in BOARD_PROCESS_INTENTS if w in text]
        if matched_process:
            score += 3.0
            reasons.append(f"process_intent({','.join(matched_process)})")

        matched_choice = [w for w in BOARD_RECOMMEND_CHOICE_INTENTS if w in text]
        if matched_choice:
            score += 2.0
            reasons.append(f"choice_intent({','.join(matched_choice)})")

        matched_structure = [w for w in BOARD_STRUCTURE_INTENTS if w in text]
        if matched_structure:
            score += 2.0
            reasons.append(f"structure_intent({','.join(matched_structure)})")

        # Numbered items request (e.g. "三個", "五個", "3種")
        if re.search(r"[一二兩三四五六七八九十\d]+(個|種|項|點|步)", text):
            score += 2.0
            reasons.append("item_count_request")

        # 2. SIMPLE intents
        matched_greetings = [w for w in SIMPLE_GREETINGS if w in text]
        if matched_greetings:
            score -= 5.0
            reasons.append(f"greeting({','.join(matched_greetings)})")

        matched_fact = [w for w in SIMPLE_FACT_OR_DEF if w in text]
        if matched_fact:
            score -= 2.0
            reasons.append(f"fact_or_def({','.join(matched_fact)})")

        matched_yesno = [w for w in SIMPLE_CONFIRMATION_OR_YESNO if w in text]
        if matched_yesno:
            score -= 3.0
            reasons.append(f"yesno_or_confirm({','.join(matched_yesno)})")

        matched_short = [w for w in SIMPLE_SHORT_QUERIES if w in text]
        if matched_short:
            score -= 3.0
            reasons.append(f"short_query({','.join(matched_short)})")

        reason_str = "; ".join(reasons) if reasons else "default score"

        if score >= self.board_threshold:
            return ReplyMode.BOARD, score, reason_str
        if score <= self.simple_threshold:
            return ReplyMode.SIMPLE, score, reason_str
        return ReplyMode.AMBIGUOUS, score, reason_str


CLASSIFIER_SYSTEM_PROMPT = """You are a response-mode classifier.

Determine whether the user's request should be answered as:

SIMPLE:
A normal conversational answer without a structured board.

BOARD:
The answer naturally contains multiple list items, steps, options, comparisons,
recommendations, categories, features, requirements, or structured information
that should be separately shown in a visual board.

Return exactly one token:
SIMPLE
or
BOARD"""


class LLMFallbackClassifier:
    """Uses the primary LLM client to classify ambiguous queries."""

    def __init__(
        self,
        llm_client_getter: Optional[Callable[[], Any]] = None,
        *,
        model: str = "qwen-plus",
        max_tokens: int = 4,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.llm_client_getter = llm_client_getter
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds

    def classify(self, message: str) -> tuple[ReplyMode, str]:
        """Classify message using the shared LLM client without conversation history."""
        start_time = time.perf_counter()
        if not self.llm_client_getter:
            return ReplyMode.SIMPLE, "no llm client getter provided"

        try:
            client = self.llm_client_getter()
            if client is None:
                return ReplyMode.SIMPLE, "llm client unavailable"

            messages = [
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": f"User:\n{message}"},
            ]

            completion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                max_tokens=self.max_tokens,
                temperature=0.0,
                timeout=self.timeout_seconds,
            )

            raw_text = ""
            if completion.choices:
                raw_text = (completion.choices[0].message.content or "").strip().upper()

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if "BOARD" in raw_text:
                return ReplyMode.BOARD, f"llm_classified_board ({elapsed_ms:.1f}ms)"
            if "SIMPLE" in raw_text:
                return ReplyMode.SIMPLE, f"llm_classified_simple ({elapsed_ms:.1f}ms)"

            logger.warning(
                "LLM classifier unrecognized output: %r, fallback=SIMPLE", raw_text
            )
            return ReplyMode.SIMPLE, f"llm_output_unrecognized({raw_text})"

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "LLM classifier failed after %.1fms: %s (%s), fallback=SIMPLE",
                elapsed_ms,
                type(exc).__name__,
                exc,
            )
            return ReplyMode.SIMPLE, f"llm_classifier_error({type(exc).__name__})"


class ReplyRouter:
    """Orchestrates response mode routing with Rule First -> LLM Fallback."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        rule_first: bool = True,
        llm_fallback: bool = True,
        board_threshold: float = 3.0,
        simple_threshold: float = 0.0,
        classifier: Optional[LLMFallbackClassifier] = None,
    ) -> None:
        self.enabled = enabled
        self.rule_first = rule_first
        self.llm_fallback = llm_fallback
        self.rule_router = RuleRouter(
            board_threshold=board_threshold,
            simple_threshold=simple_threshold,
        )
        self.classifier = classifier

    def route(
        self,
        message: str,
        *,
        preference: Optional[ReplyModePreference | str] = None,
    ) -> ReplyRoute:
        start_time = time.perf_counter()

        # Check explicit preference override
        pref_str = (
            preference.value.lower()
            if isinstance(preference, ReplyModePreference)
            else str(preference or "").lower()
        )
        if pref_str in ("simple", ReplyModePreference.SIMPLE.value):
            return ReplyRoute(
                mode=ReplyMode.SIMPLE,
                source="forced",
                score=0.0,
                reason="forced by preference",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        if pref_str in ("board", ReplyModePreference.BOARD.value):
            return ReplyRoute(
                mode=ReplyMode.BOARD,
                source="forced",
                score=10.0,
                reason="forced by preference",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # If router is globally disabled, always return SIMPLE (legacy mode)
        if not self.enabled:
            return ReplyRoute(
                mode=ReplyMode.SIMPLE,
                source="disabled",
                score=0.0,
                reason="router disabled",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        # 1. Rule Router evaluation
        mode, score, reason = self.rule_router.evaluate(message)
        rule_latency = (time.perf_counter() - start_time) * 1000.0

        if mode in (ReplyMode.BOARD, ReplyMode.SIMPLE):
            logger.info(
                "reply_mode=%s router_source=rule router_score=%.1f router_latency_ms=%.2f",
                mode.value,
                score,
                rule_latency,
            )
            return ReplyRoute(
                mode=mode,
                source="rule",
                score=score,
                reason=reason,
                latency_ms=rule_latency,
            )

        # 2. Ambiguous query -> LLM Fallback Classifier (if enabled)
        if self.llm_fallback and self.classifier is not None:
            c_mode, c_reason = self.classifier.classify(message)
            total_latency = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                "reply_mode=%s router_source=llm router_score=%.1f classifier_latency_ms=%.2f",
                c_mode.value,
                score,
                total_latency - rule_latency,
            )
            return ReplyRoute(
                mode=c_mode,
                source="llm",
                score=score,
                reason=f"{reason} -> {c_reason}",
                latency_ms=total_latency,
            )

        # Fallback to SIMPLE when ambiguous and no LLM classifier
        return ReplyRoute(
            mode=ReplyMode.SIMPLE,
            source="fallback",
            score=score,
            reason=f"{reason} -> default fallback SIMPLE",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
        )
