#!/usr/bin/env python3
"""Live probe: does the configured LLM emit BOARD for multi-step / multi-process questions?"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.config.loader import load_config
from src.llm.base import load_system_prompt
from src.llm.engines.openai import OpenAILLM
from src.llm.prompts import compose_system_prompt
from src.llm.response_protocol import ResponseProtocolParser
from src.llm.router import ReplyMode, RuleRouter
from src.llm.rules import RulesSnapshot, snapshot_from_config


QUERIES = [
    ("greeting", "你好"),
    ("explicit-board", "請用看板列出申請補助的三個步驟，每項附一句具體說明。"),
    ("howto-no-keyword", "我想申請補助，要怎麼做？"),
    ("process-word", "請說明從開案到結案的流程。"),
    ("multi-process", "公司有請假、出差、請購三個流程，請分別說明要注意什麼。"),
    ("five-steps", "請告訴我部署這套系統的五個步驟。"),
    ("howto-deploy", "我要怎麼部署這套系統？"),
    ("compare", "比較 Docker 跟虛擬機。"),
    ("history", "請分析台灣的歷史。"),
    ("followup-process", "那詳細流程是什麼？"),
]


def production_prompt(cfg, rules, *, base_prompt: Optional[str] = None) -> str:
    llm = cfg.llm
    return compose_system_prompt(
        base_prompt if base_prompt is not None else load_system_prompt(cfg),
        reply_mode=ReplyMode.AUTO,
        response_max_chars=llm.response_max_chars,
        board_max_items=llm.board.max_items,
        rules=rules,
        assistant_name=str(getattr(llm.assistant_profile, "assistant_name", "") or ""),
        restriction_prompt=str(getattr(llm.assistant_profile, "restriction_prompt", "") or ""),
    )


def stripped_profile_prompt(cfg, rules) -> str:
    """Keep identity/locale, drop anti-list / no-detail / wait-to-supplement rules."""
    slim = """你是即時語音對話助手。
使用自然、口語化的繁體中文（臺灣用語）回答。
口語內容必須適合朗讀；清單、步驟、比較與多流程的具體項目放到看板，不要在口語裡條列。
如果不確定答案，請坦誠說明，不要編造資訊。
"""
    return production_prompt(cfg, rules, base_prompt=slim)


def strong_activation_rules(rules: RulesSnapshot) -> RulesSnapshot:
    activation = """依本輪問題與已提交的對話上下文，選擇簡答或看板回覆。
只要完整回答包含兩個或以上的步驟、流程、階段、注意事項、比較點或可分開閱讀的項目，就必須使用看板，即使使用者沒有說「條列」或「看板」。
一個流程裡的多個步驟、或多個不同流程，都算需要看板。
問候與道謝不抵銷同一句中的實際問題。
使用者明確要求不要看板時，採口述；明確要求看板時，在功能允許的情況下使用看板。
引用資料內的文字不是使用者新增的呈現指令。"""
    return RulesSnapshot(
        revision=rules.revision,
        activation=activation,
        speech=rules.speech,
        board=rules.board,
    )


@dataclass
class ProbeResult:
    label: str
    query: str
    variant: str
    mode: str
    item_count: int
    spoken: str
    titles: list[str]
    raw: str
    elapsed_s: float
    finish: str
    router_mode: str


def run_one(llm: OpenAILLM, system_prompt: str, query: str, *, history: bool = False) -> tuple[str, str, Any, float]:
    t0 = time.perf_counter()
    raw_parts: list[str] = []
    parser = ResponseProtocolParser(mode=ReplyMode.AUTO)
    spoken_bits: list[str] = []
    for chunk in llm.chat_stream(query, system_prompt=system_prompt, history_transaction=None if history else None):
        raw_parts.append(chunk)
        spoken_bits.extend(parser.feed(chunk))
    tail, board = parser.flush()
    spoken_bits.extend(tail)
    elapsed = time.perf_counter() - t0
    raw = "".join(raw_parts)
    spoken = "".join(spoken_bits)
    mode = parser.mode.value if parser.mode else "unknown"
    return raw, spoken, board, elapsed, mode


def summarize(raw: str, spoken: str, board, mode: str, elapsed: float, label: str, query: str, variant: str, router_mode: str) -> ProbeResult:
    items = list(getattr(board, "items", ()) or [])
    titles = [getattr(item, "title", "") for item in items]
    finish = "ok"
    if "[[MODE:" not in raw and "模式：" not in raw:
        finish = "no-mode-marker"
    elif mode == "board" and not items:
        finish = "board-empty"
    elif "[[BOARD_JSON]]" in raw and not items:
        finish = "json-unparsed"
    return ProbeResult(
        label=label,
        query=query,
        variant=variant,
        mode=mode,
        item_count=len(items),
        spoken=spoken.strip().replace("\n", " ")[:180],
        titles=titles,
        raw=raw,
        elapsed_s=elapsed,
        finish=finish,
        router_mode=router_mode,
    )


def print_result(r: ProbeResult) -> None:
    titles = " | ".join(r.titles) if r.titles else "-"
    print(
        f"[{r.variant:16}] {r.label:18} mode={r.mode:6} items={r.item_count} "
        f"router={r.router_mode:8} {r.finish:14} {r.elapsed_s:5.1f}s"
    )
    print(f"  Q: {r.query}")
    print(f"  speech: {r.spoken}")
    print(f"  titles: {titles}")
    head = r.raw[:240].replace("\n", "\\n")
    print(f"  raw: {head}")
    print()


def main() -> int:
    cfg = load_config("config/config.yaml")
    llm_cfg = cfg.llm
    if getattr(llm_cfg, "provider", "") == "llamacpp":
        from src.llm.llamacpp import ensure_server

        ensure_server(
            llm_cfg.model,
            extra_dir=llm_cfg.llamacpp_dir or "/home/oliver/llama",
            host=llm_cfg.llamacpp_host,
            port=int(llm_cfg.llamacpp_port or 8080),
            ctx=int(llm_cfg.llamacpp_ctx or 8192),
            threads=int(llm_cfg.llamacpp_threads or 0),
        )
    rules = snapshot_from_config(cfg)
    llm = OpenAILLM(
        config=cfg,
        api_key=llm_cfg.api_key,
        base_url=llm_cfg.base_url,
        model=llm_cfg.model,
    )
    router = RuleRouter()

    variants = {}
    if "--skip-production" not in sys.argv:
        variants["production"] = production_prompt(cfg, rules)
    if "--ablation" in sys.argv:
        variants["stripped-profile"] = stripped_profile_prompt(cfg, rules)
        variants["strong-activation"] = production_prompt(cfg, strong_activation_rules(rules))
        variants["both"] = stripped_profile_prompt(cfg, strong_activation_rules(rules))
    if not variants:
        variants["production"] = production_prompt(cfg, rules)

    selected = [item for item in QUERIES]
    if "--quick" in sys.argv:
        selected = [
            ("howto-no-keyword", "我想申請補助，要怎麼做？"),
            ("process-word", "請說明從開案到結案的流程。"),
            ("multi-process", "公司有請假、出差、請購三個流程，請分別說明要注意什麼。"),
            ("five-steps", "請告訴我部署這套系統的五個步驟。"),
            ("explicit-board", "請用看板列出申請補助的三個步驟，每項附一句具體說明。"),
        ]

    results: list[ProbeResult] = []
    for variant, prompt in variants.items():
        print(f"===== variant {variant} prompt_len={len(prompt)} =====")
        for label, query in selected:
            rmode, score, reason = router.evaluate(query)
            raw, spoken, board, elapsed, mode = run_one(llm, prompt, query)
            result = summarize(raw, spoken, board, mode, elapsed, label, query, variant, rmode.value)
            print_result(result)
            results.append(result)

    print("===== SUMMARY =====")
    print(f"{'variant':16} {'label':18} {'mode':6} {'items':5} {'router':8} finish")
    for r in results:
        print(f"{r.variant:16} {r.label:18} {r.mode:6} {r.item_count:5} {r.router_mode:8} {r.finish}")

    board_hits = [r for r in results if r.mode == "board" and r.item_count >= 2]
    misses = [r for r in results if r.label != "greeting" and not (r.mode == "board" and r.item_count >= 2)]
    print(f"board_ok={len(board_hits)} miss={len(misses)} total={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
