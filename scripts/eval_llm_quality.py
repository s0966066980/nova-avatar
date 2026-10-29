#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Compare local LLMs on a fixed set of 30 visitor questions (issue 04).

``run`` asks one llama-server (given by URL) every question twice through the
production code: the role routing decision, then the answer of the expected
destination role with the real system prompt, reply grammar, retrieved
knowledge or weather facts. ``report`` puts two runs side by side with the
automatic checks: reply format, Simplified characters, spoken length cap, the
short first sentence (issue 08) and routing correctness. The user decides on
the default model from that report. ``first-sentence`` summarises one run:
how often the reply opens with a complete sentence of at most 15 characters,
and how long and how late the first playable fragment was, both at the
complete semantic boundary and with the first-fragment exception.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EVAL_DIR = PROJECT_ROOT / ".scratch" / "first-audio-latency" / "e2b-eval"
QUESTIONS_PATH = EVAL_DIR / "questions.json"
CATEGORIES = {"general": "一般", "rag": "RAG", "weather": "天氣", "handoff": "需交接"}
ROLES = ("main", "weather")
ROUTES = ("answer", "specialist", "clarify")
MODES = ("SIMPLE", "BOARD")


_REPLY = re.compile(
    r"\s*\[\[MODE:(?P<mode>SIMPLE|BOARD)\]\]\n\[\[SPEECH\]\]\n(?P<speech>[^\n]+)\n"
    r"(?:\[\[BOARD_JSON\]\]\n(?P<board>\{.*\})\n)?\[\[END\]\]\s*", re.DOTALL)
_MARKER = re.compile(r"\[\[[A-Z_]+(?::[A-Z]+)?\]\]")
# Standard Traditional characters that OpenCC would still map to another
# character (里長, 皇后, 台灣, 干擾, 范姓, 游泳 ...). They are not Simplified.
_SHARED_TRADITIONAL = frozenset("里后台干范云斗丑几征采朴划余占准咸岳尸游吁沈")
_S2TW = None


def parse_reply(raw: str) -> dict:
    """Split a reply in the fixed protocol; ``error`` names what is malformed."""
    match = _REPLY.fullmatch(raw or "")
    if match is None:
        return {"mode": "", "speech": _MARKER.sub(" ", raw or "").strip(), "board": None,
                "error": "不符合 [[MODE]]/[[SPEECH]]/[[END]] 協定（可能被截斷）"}
    mode, speech, board_raw = match.group("mode"), match.group("speech").strip(), match.group("board")
    if (mode == "BOARD") != (board_raw is not None):
        return {"mode": mode, "speech": speech, "board": None, "error": f"{mode} 的看板資料不一致"}
    board = None
    if board_raw is not None:
        try:
            board = json.loads(board_raw)
        except ValueError:
            return {"mode": mode, "speech": speech, "board": None, "error": "看板 JSON 無法解析"}
        items = board.get("items") if isinstance(board, dict) else None
        if (not isinstance(board.get("title") if isinstance(board, dict) else None, str)
                or not isinstance(items, list) or not items
                or not all(isinstance(item, dict) and isinstance(item.get("title"), str)
                           and isinstance(item.get("content"), str) for item in items)):
            return {"mode": mode, "speech": speech, "board": None, "error": "看板 JSON 欄位不正確"}
    return {"mode": mode, "speech": speech, "board": board, "error": ""}


def simplified_characters(text: str) -> str:
    """Characters of ``text`` that only exist in Simplified Chinese, in order, once each."""
    global _S2TW
    if _S2TW is None:
        from opencc import OpenCC
        _S2TW = OpenCC("s2tw")
    found = []
    for char in text:
        if ("㐀" <= char <= "鿿" and char not in _SHARED_TRADITIONAL
                and char not in found and _S2TW.convert(char) != char):
            found.append(char)
    return "".join(found)


def _visible_text(reply: dict) -> str:
    board = reply["board"] or {}
    parts = [reply["speech"], board.get("title", "")]
    parts += [f"{item['title']} {item['content']}" for item in board.get("items", [])]
    return "\n".join(parts)


def first_sentence(speech: str) -> str:
    """The opening sentence the production fragmenter would cut, or ``""``.

    Only a sentence end counts: the semantic wait never expires here, so text
    without one (or only a comma clause) is not a complete first sentence.
    """
    from src.server.reply_streaming.fragmenter import SemanticFragmenter

    fragments = SemanticFragmenter(clock=lambda: 0.0, first_fragment_min_units=None).feed(speech)
    return fragments[0] if fragments else ""


def first_sentence_check(speech: str) -> dict:
    """Issue 08 rule: a complete first sentence of at most 15 content characters."""
    from src.llm.reply_contract import FIRST_SENTENCE_MAX_CHARS
    from src.server.reply_streaming.fragmenter import content_length

    first = first_sentence(speech)
    return {"passed": bool(first) and content_length(first) <= FIRST_SENTENCE_MAX_CHARS,
            "value": first}


def first_fragment(chunks, *, semantic_wait_seconds: float = 0.5,
                   exception: bool = True) -> dict | None:
    """When the first playable fragment would leave the fragmenter.

    ``chunks`` are ``(seconds, text)`` as the model streamed them. They are
    replayed through the production protocol parser and fragmenter; between
    chunks the semantic-wait timer may release a clause, as it does live.
    ``exception=False`` replays the complete semantic boundary without the
    first-fragment exception.
    """
    from src.llm.response_protocol import ResponseProtocolParser
    from src.llm.router import ReplyMode
    from src.server.reply_streaming.fragmenter import (
        FIRST_FRAGMENT_MIN_UNITS, SemanticFragmenter, content_length)

    now = 0.0
    fragmenter = SemanticFragmenter(
        semantic_wait_seconds=semantic_wait_seconds, clock=lambda: now,
        first_fragment_min_units=FIRST_FRAGMENT_MIN_UNITS if exception else None)
    parser = ResponseProtocolParser(mode=ReplyMode.AUTO, guard_board_speech=True)

    def found(fragments, at):
        if not fragments:
            return None
        return {"text": fragments[0], "chars": content_length(fragments[0]),
                "seconds": round(at, 3)}

    at = 0.0
    for at, chunk in chunks:
        remaining = fragmenter.semantic_wait_remaining()
        if remaining is not None and now + remaining <= at:
            released_at, now = now + remaining, at
            if result := found(fragmenter.feed(""), released_at):
                return result
        now = at
        for delta in parser.feed(chunk):
            if result := found(fragmenter.feed(delta), at):
                return result
        if parser.speech_complete and (result := found(fragmenter.flush(), at)):
            return result
    for delta in parser.flush()[0]:
        if result := found(fragmenter.feed(delta), at):
            return result
    return found(fragmenter.flush(), at)


def opening_fragment(speech: str) -> str:
    """The first fragment of ``speech``, with the exception, fed one character at a time.

    The semantic wait never expires here, as in a fast stream.
    """
    from src.server.reply_streaming.fragmenter import SemanticFragmenter

    fragmenter = SemanticFragmenter(clock=lambda: 0.0)
    for character in speech:
        if fragments := fragmenter.feed(character):
            return fragments[0]
    return next(iter(fragmenter.flush()), "")


def compare_first_fragment(answer: dict, *, semantic_wait_seconds: float = 0.5) -> dict:
    """The first fragment at the complete semantic boundary and with the exception.

    Runs that kept their chunks are replayed exactly. Older runs kept only the
    first fragment at the complete boundary: the exception's fragment is a
    prefix of it, so its time is interpolated linearly, by content characters,
    between the first spoken character and that fragment (``estimated``).
    """
    from src.server.reply_streaming.fragmenter import content_length

    if answer.get("chunks"):
        chunks = [(at, text) for at, text in answer["chunks"]]
        return {"before": first_fragment(chunks, semantic_wait_seconds=semantic_wait_seconds,
                                          exception=False),
                "after": first_fragment(chunks, semantic_wait_seconds=semantic_wait_seconds),
                "estimated": False}
    before = answer.get("first_fragment")
    after = None
    text = opening_fragment(parse_reply(answer["raw"])["speech"])
    if before and text == before["text"]:
        after = dict(before)
    elif before and text and before["text"].startswith(text) and before["chars"]:
        spoken_at = answer.get("first_speech_seconds")
        chars = content_length(text)
        if spoken_at is not None:
            seconds = spoken_at + (before["seconds"] - spoken_at) * chars / before["chars"]
            after = {"text": text, "chars": chars, "seconds": round(seconds, 3)}
    return {"before": before, "after": after, "estimated": True}


def check_answer(raw: str, *, max_chars: int, expected_mode: str | None = None,
                 expected_terms=()) -> dict:
    """Automatic checks of one raw reply; each is ``{"passed", "value"}``.

    Length counts the visible (non-whitespace) characters of the spoken part,
    the part the response length setting limits; board text is not counted.
    """
    reply = parse_reply(raw)
    simplified = simplified_characters(_visible_text(reply))
    spoken = len(re.sub(r"\s", "", reply["speech"]))
    checks = {
        "format": {"passed": not reply["error"], "value": reply["error"]},
        "simplified": {"passed": not simplified, "value": simplified},
        "length": {"passed": spoken <= max_chars, "value": spoken},
        "first_sentence": first_sentence_check(reply["speech"]),
    }
    if expected_mode:
        checks["mode"] = {"passed": reply["mode"] == expected_mode, "value": reply["mode"]}
    if expected_terms:
        visible = _visible_text(reply).casefold()
        missing = [term for term in expected_terms if term.casefold() not in visible]
        checks["terms"] = {"passed": not missing, "value": "、".join(missing)}
    return checks


def served_model(base_url: str) -> str:
    """GGUF name the llama-server at ``base_url`` has loaded, without ``.gguf``."""
    from openai import OpenAI

    with OpenAI(api_key="nova-avatar-eval", base_url=base_url, timeout=5., max_retries=0) as client:
        loaded = next(iter(client.models.list()))
    return Path(str(loaded.id)).name.removesuffix(".gguf")


def _role_config(config, library, role: str, *, base_url: str, model: str):
    from src.profiles.store import profile_config

    role_id = library["pair"]["main" if role == "main" else "specialist"]
    profile = next(item for item in library["profiles"] if item["id"] == role_id)
    result = profile_config(config, profile)
    # The saved role, rules and prompts stay; only the server under test changes.
    result.llm.provider = "llamacpp"
    result.llm.base_url = base_url
    result.llm.model = model
    result.llm.api_key = result.llm.api_key or "nova-avatar-eval"
    result.conversation.locale = "zh-TW"
    return result, profile


def _timed_engine(config):
    from src.llm.engines.openai import OpenAILLM

    class TimedLLM(OpenAILLM):
        """Keeps the raw protocol text, each chunk's arrival and the first speech."""

        def chat_stream(self, message, system_prompt=None, **kwargs):
            started = time.perf_counter()
            self.raw, self.first_token, self.first_speech, self.chunks = "", None, None, []
            for chunk in super().chat_stream(message, system_prompt, **kwargs):
                elapsed = time.perf_counter() - started
                self.raw += chunk
                self.chunks.append((elapsed, chunk))
                if self.first_token is None:
                    self.first_token = elapsed
                if self.first_speech is None and re.search(r"\[\[SPEECH\]\]\n\s*\S", self.raw):
                    self.first_speech = elapsed
                yield chunk

    llm = config.llm
    engine = TimedLLM(config=config, api_key=llm.api_key, base_url=llm.base_url, model=llm.model)
    engine.raw, engine.first_token, engine.first_speech, engine.chunks = "", None, None, []
    return engine


def _answer(question: dict, data: dict, config, profile) -> dict:
    from src.llm.router import ReplyMode
    from src.profiles.weather import weather_prompt
    from src.ragflow.client import retrieval_prompt

    engine = _timed_engine(config)
    for message in data.get("histories", {}).get(question.get("history") or "", []):
        engine.add_to_history(message["role"], message["content"])
    # Same order as a live turn: retrieved knowledge, then this role's tool facts.
    # The knowledge-base snapshot stands in for a retrieval hit, so both models
    # read identical sources whether or not RAGFlow is reachable.
    context = ""
    if question.get("rag"):
        context = retrieval_prompt(data["knowledge_base"]["sources"])
    if profile["tools"]["weather"]:
        context += "\n" + weather_prompt(data["weather_fixture"])
    started = time.perf_counter()
    error = ""
    try:
        engine.generate_response(question["text"], stream_to_avatar=False,
                                 reply_mode=ReplyMode.AUTO, rag_context=context)
    except Exception as exc:  # one failed question must not end the run
        error = f"{type(exc).__name__}: {exc}"[:300]
    total = time.perf_counter() - started
    reply = parse_reply(engine.raw)
    return {
        "role": profile["id"], "raw": engine.raw, "mode": reply["mode"], "speech": reply["speech"],
        "board": reply["board"], "error": error,
        "checks": check_answer(engine.raw, max_chars=config.llm.response_max_chars,
                               expected_mode=question.get("expected_mode"),
                               expected_terms=question.get("expected_terms", ())),
        "max_chars": config.llm.response_max_chars,
        "first_token_seconds": _rounded(engine.first_token),
        "first_speech_seconds": _rounded(engine.first_speech),
        "first_fragment": first_fragment(
            engine.chunks, semantic_wait_seconds=config.reply_streaming.semantic_wait_seconds),
        "chunks": [[_rounded(at), chunk] for at, chunk in engine.chunks],
        "total_seconds": _rounded(total),
    }


def _rounded(value):
    return None if value is None else round(value, 3)


def run_eval(base_url: str, *, label: str, config, library: dict, data: dict,
             model: str = "") -> dict:
    """Route and answer every question against one llama-server, sequentially."""
    from src.profiles.routing import RoutingClients, route_question

    model = model or served_model(base_url)
    clients = RoutingClients()
    items = []
    try:
        for question in data["questions"]:
            history = data.get("histories", {}).get(question.get("history") or "", [])
            current, profile = _role_config(config, library, question["role"],
                                            base_url=base_url, model=model)
            started = time.perf_counter()
            route, route_error = "", ""
            try:
                route = route_question(current, library, profile["id"], question["text"],
                                       history, dict(data.get("confirmed_context", {})),
                                       clients=clients)["route"]
            except Exception as exc:
                route_error = f"{type(exc).__name__}: {exc}"[:300]
            item = {key: question.get(key) for key in
                    ("id", "category", "source", "role", "text", "expected_route", "expected_mode")}
            item.update(route=route, route_error=route_error,
                        route_correct=route == question["expected_route"],
                        route_seconds=_rounded(time.perf_counter() - started), answer=None)
            if question["expected_route"] != "clarify":
                destination = "main" if question["expected_route"] == "answer" else "weather"
                answer_config, answer_profile = _role_config(config, library, destination,
                                                             base_url=base_url, model=model)
                item["answer"] = _answer(question, data, answer_config, answer_profile)
            items.append(item)
            print(f"{label} {question['id']} route={route or route_error} "
                  f"correct={item['route_correct']}", flush=True)
    finally:
        clients.close()
    return {"label": label, "model": model, "base_url": base_url,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items}


# Routing is "clearly lower" (spec Q18) when the candidate misses at least this
# many more of the 30 questions than the baseline.
ROUTING_GAP = 2
_CHECK_LABELS = (("format", "格式正確"), ("simplified", "無簡體字"),
                 ("length", "口語字數未超過上限"), ("first_sentence", "首句 15 字內且完整"),
                 ("mode", "模式符合預期"), ("terms", "關鍵事實命中"))
_ROLE_LABELS = {"main": "主角色", "weather": "天氣角色"}


def _cell(text) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def _median(values) -> str:
    values = sorted(value for value in values if value is not None)
    if not values:
        return "—"
    middle = len(values) // 2
    value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return f"{value:.2f} s"


def _percentile(values, fraction: float):
    """Nearest-rank percentile, or ``None`` without values."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def _fragment_value(answer: dict, key: str):
    return (answer.get("first_fragment") or {}).get(key)


def _answers(result: dict) -> list:
    return [item["answer"] for item in result["items"] if item["answer"] is not None]


def _check_count(result: dict, name: str) -> str:
    checks = [answer["checks"][name] for answer in _answers(result) if name in answer["checks"]]
    return f"{sum(check['passed'] for check in checks)}/{len(checks)}"


def _routing_count(items) -> str:
    items = list(items)
    return f"{sum(item['route_correct'] for item in items)}/{len(items)}"


def _check_summary(answer: dict) -> str:
    checks = answer["checks"]
    parts = []
    if answer["error"]:
        parts.append(f"錯誤：{answer['error']}")
    format_check = checks["format"]
    parts.append("格式✓" if format_check["passed"] else f"格式✗（{format_check['value']}）")
    simplified = checks["simplified"]
    parts.append("簡體✓" if simplified["passed"] else f"簡體：{simplified['value']}")
    length = checks["length"]
    parts.append(f"字數 {length['value']}/{answer['max_chars']}{'✓' if length['passed'] else '✗'}")
    if "first_sentence" in checks:
        from src.server.reply_streaming.fragmenter import content_length

        first = checks["first_sentence"]
        size = f"首句 {content_length(first['value'])} 字" if first["value"] else "首句未完整"
        parts.append(size + ("✓" if first["passed"] else "✗"))
    if "mode" in checks:
        parts.append("模式✓" if checks["mode"]["passed"] else "模式✗")
    if "terms" in checks:
        terms = checks["terms"]
        parts.append("事實✓" if terms["passed"] else f"缺：{terms['value']}")
    return "；".join(parts)


def _board_text(board) -> str:
    if not board:
        return "—"
    items = "；".join(f"{item['title']}：{item['content']}" for item in board["items"])
    return f"〔{board['title']}〕{items}"


def build_report(baseline: dict, candidate: dict) -> str:
    """Markdown report: summary, decision hints, then every question side by side."""
    a, b = baseline, candidate
    if [item["id"] for item in a["items"]] != [item["id"] for item in b["items"]]:
        raise ValueError("兩次執行的題目不同，無法並排比較")
    names = (a["label"], b["label"])
    lines = [
        "<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->",
        f"# 主要 LLM 品質比較：{names[0]} 與 {names[1]}",
        "",
        f"- {names[0]}：`{a['model']}`（{a['at']}）",
        f"- {names[1]}：`{b['model']}`（{b['at']}）",
        f"- 題目：{len(a['items'])} 題，"
        + "、".join(f"{label} {sum(item['category'] == key for item in a['items'])}"
                   for key, label in CATEGORIES.items())
        + "；來源與預期見 `questions.json`。",
        "- 回答一律以預期的目的角色產生（與實際路由結果無關），兩個模型讀到相同的提示、"
        "檢索片段與氣象資料。自動檢查只看格式與數字，語意好壞請讀逐題並排。",
        "",
        "## 總覽",
        "",
        f"| 項目 | {_cell(names[0])} | {_cell(names[1])} |",
        "|---|---|---|",
        f"| 路由正確率 | {_routing_count(a['items'])} | {_routing_count(b['items'])} |",
    ]
    for name, label in _CHECK_LABELS:
        lines.append(f"| {label} | {_check_count(a, name)} | {_check_count(b, name)} |")
    for key, label in (("route_seconds", "路由耗時 P50"),):
        lines.append(f"| {label} | {_median(i[key] for i in a['items'])} | "
                     f"{_median(i[key] for i in b['items'])} |")
    for key, label in (("first_speech_seconds", "回答首個口語 P50"),
                       ("total_seconds", "回答總耗時 P50")):
        lines.append(f"| {label} | {_median(x[key] for x in _answers(a))} | "
                     f"{_median(x[key] for x in _answers(b))} |")
    lines.append(f"| 首個片段 P50 | {_median(_fragment_value(x, 'seconds') for x in _answers(a))} | "
                 f"{_median(_fragment_value(x, 'seconds') for x in _answers(b))} |")

    lines += ["", "## 各類別路由正確率", "", f"| 類別 | {_cell(names[0])} | {_cell(names[1])} |",
              "|---|---|---|"]
    for key, label in CATEGORIES.items():
        lines.append(f"| {label} | {_routing_count(i for i in a['items'] if i['category'] == key)} | "
                     f"{_routing_count(i for i in b['items'] if i['category'] == key)} |")

    gap = sum(i["route_correct"] for i in a["items"]) - sum(i["route_correct"] for i in b["items"])
    lines += ["", "## 判讀", ""]
    if gap >= ROUTING_GAP:
        lines.append(f"- **{names[1]} 路由正確率比 {names[0]} 少 {gap} 題**（門檻：少 {ROUTING_GAP} 題以上）。"
                     f"依規格加關鍵字初篩後再用 {names[1]} 路由，不回頭用 {names[0]}。")
    else:
        lines.append(f"- 路由：{names[1]} 未明顯低於 {names[0]}（差 {gap} 題，門檻 {ROUTING_GAP} 題）。")
    for result in (a, b):
        failed = [item["id"] for item in result["items"] if item["answer"] is not None
                  and (item["answer"]["error"]
                       or not all(check["passed"] for check in item["answer"]["checks"].values()))]
        missed = [item["id"] for item in result["items"] if not item["route_correct"]]
        lines.append(f"- {result['label']}：自動檢查未過 {('、'.join(failed) or '無')}；"
                     f"路由錯誤 {('、'.join(missed) or '無')}。")
    lines.append("- 使用者決定：（待填）")

    lines += ["", "## 逐題並排", ""]
    for first, second in zip(a["items"], b["items"]):
        expected = first["expected_route"] + (f"／{first['expected_mode']}" if first["expected_mode"] else "")
        lines += [f"### {first['id']} {CATEGORIES[first['category']]} · "
                  f"{_ROLE_LABELS[first['role']]} · 預期 {expected}", "",
                  f"問：{first['text']}", "",
                  f"| | {_cell(names[0])} | {_cell(names[1])} |", "|---|---|---|"]

        def route(item):
            mark = "✓" if item["route_correct"] else "✗"
            return f"{item['route'] or item['route_error']} {mark}（{item['route_seconds']} s）"

        lines.append(f"| 路由 | {_cell(route(first))} | {_cell(route(second))} |")
        if first["answer"] is not None:
            x, y = first["answer"], second["answer"]
            lines += [
                f"| 模式 | {_cell(x['mode'])} | {_cell(y['mode'])} |",
                f"| 口語 | {_cell(x['speech'])} | {_cell(y['speech'])} |",
                f"| 看板 | {_cell(_board_text(x['board']))} | {_cell(_board_text(y['board']))} |",
                f"| 檢查 | {_cell(_check_summary(x))} | {_cell(_check_summary(y))} |",
                f"| 首個口語 | {_cell(x['first_speech_seconds'])} s | {_cell(y['first_speech_seconds'])} s |",
                f"| 首個片段 | {_cell(_fragment_cell(x.get('first_fragment')))} "
                f"| {_cell(_fragment_cell(y.get('first_fragment')))} |",
            ]
        lines.append("")
    return "\n".join(lines)


def _fragment_cell(fragment: dict | None) -> str:
    if not fragment:
        return "—"
    return f"{fragment['chars']} 字，{fragment['seconds']} s：{fragment['text']}"


def build_first_sentence_report(result: dict) -> str:
    """Markdown summary of the issue 08 first-sentence rule for one run.

    Compliance is recomputed from each raw reply, so runs recorded before the
    check existed are summarised too; fragment timing needs a newer run.
    """
    from src.llm.reply_contract import FIRST_SENTENCE_MAX_CHARS
    from src.server.reply_streaming.fragmenter import FIRST_FRAGMENT_MIN_UNITS, content_length

    answers = [(item, item["answer"]) for item in result["items"] if item["answer"] is not None]
    checked = [(item, first_sentence_check(parse_reply(answer["raw"])["speech"]))
               for item, answer in answers]
    failed = [(item, check) for item, check in checked if not check["passed"]]
    compared = [(item, compare_first_fragment(answer)) for item, answer in answers]
    estimated = any(comparison["estimated"] for _, comparison in compared)

    def spread(side: str, key: str, unit: str) -> str:
        values = [(comparison[side] or {}).get(key) for _, comparison in compared]
        p50, p95 = _percentile(values, 0.5), _percentile(values, 0.95)
        if p50 is None:
            return "—（此次執行未記錄串流時間）"
        counted = sum(value is not None for value in values)
        missing = f"（{counted}/{len(values)} 題）" if counted < len(values) else ""
        return f"P50 {p50:g}{unit}，P95 {p95:g}{unit}{missing}"

    timing = ("此次執行未保存 chunk：完整語意邊界為記錄值；首個片段例外為估計，"
              "以首個口語時間與記錄值依字數線性內插"
              if estimated else "兩者皆以記錄的 chunk 逐一重播")

    lines = [
        "<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->",
        f"# 首句規則遵循：{result['label']}",
        "",
        f"- 模型：`{result['model']}`（{result['at']}）",
        f"- 規則：口語以一句 {FIRST_SENTENCE_MAX_CHARS} 字內、以「。」「！」「？」結束的完整句開頭。"
        "字數以正式分段器的計法（字母、數字、漢字各算一字）計算。",
        f"- 遵循率：{len(checked) - len(failed)}/{len(checked)}",
        "",
        "## 首個片段",
        "",
        f"首個片段例外：每輪第一個片段在逗號、冒號、分號處、且前段已有 {FIRST_FRAGMENT_MIN_UNITS} "
        "字（英文以字詞計）以上時立即釋放；之後的片段仍守完整語意邊界。時間自送出回答請求起算，"
        f"以正式分段器與語意等待計時計算。{timing}。",
        "",
        "| | 完整語意邊界 | 首個片段例外 |",
        "|---|---|---|",
        f"| 字數 | {spread('before', 'chars', ' 字')} | {spread('after', 'chars', ' 字')} |",
        f"| 時間 | {spread('before', 'seconds', ' s')} | {spread('after', 'seconds', ' s')} |",
        "",
    ]
    changed = [(item, comparison) for item, comparison in compared
               if comparison["after"] and comparison["before"]
               and comparison["after"]["text"] != comparison["before"]["text"]]
    if changed:
        lines += [f"提早釋放 {len(changed)}/{len(compared)} 題：", "",
                  "| 題號 | 完整語意邊界 | 首個片段例外 |", "|---|---|---|"]
        lines += [f"| {item['id']} | {_cell(_fragment_cell(comparison['before']))} "
                  f"| {_cell(_fragment_cell(comparison['after']))} |"
                  for item, comparison in changed]
        lines.append("")
    lines += ["## 未遵循", ""]
    if not failed:
        lines.append("無。")
    else:
        lines += ["| 題號 | 首句 | 口語 |", "|---|---|---|"]
        for item, check in failed:
            first = (f"{content_length(check['value'])} 字：{check['value']}"
                     if check["value"] else "沒有完整句")
            speech = parse_reply(item["answer"]["raw"])["speech"]
            lines.append(f"| {item['id']} | {_cell(first)} | {_cell(speech)} |")
    return "\n".join(lines)


def load_questions(path: Path = QUESTIONS_PATH) -> dict:
    """The fixed question set, validated so both models get identical input."""
    data = json.loads(Path(path).read_text("utf-8"))
    histories = data.get("histories", {})
    for item in data["questions"]:
        if item["category"] not in CATEGORIES or item["role"] not in ROLES:
            raise ValueError(f"題目 {item['id']} 的類別或角色不正確")
        if item["expected_route"] not in ROUTES:
            raise ValueError(f"題目 {item['id']} 的預期路由不正確")
        if item.get("expected_mode") not in (None, *MODES):
            raise ValueError(f"題目 {item['id']} 的預期模式不正確")
        if item.get("history") and item["history"] not in histories:
            raise ValueError(f"題目 {item['id']} 的對話歷史 {item['history']} 不存在")
    return data


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="ask every question against one llama-server")
    run.add_argument("--base-url", required=True, help="OpenAI URL, e.g. http://127.0.0.1:18080/v1")
    run.add_argument("--label", required=True, help="name shown in the report, e.g. Qwen3.5-9B")
    run.add_argument("--model", default="", help="GGUF name; default: what the server loaded")
    run.add_argument("--config", default=None, help="config file (default config/config.yaml)")
    run.add_argument("--profiles", type=Path, default=PROJECT_ROOT / "config" / "avatar_profiles.yaml")
    run.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    run.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("report", help="write the side-by-side Markdown report")
    report.add_argument("--baseline", type=Path, required=True)
    report.add_argument("--candidate", type=Path, required=True)
    report.add_argument("--output", type=Path, default=EVAL_DIR / "report.md")
    first = commands.add_parser("first-sentence", help="summarise the first-sentence rule of one run")
    first.add_argument("--results", type=Path, required=True)
    first.add_argument("--output", type=Path, default=EVAL_DIR / "first-sentence.md")
    args = parser.parse_args(argv)

    if args.command == "run":
        from src.config.loader import load_config
        from src.llm.endpoints import normalize_base_url
        from src.profiles.store import ProfileStore

        result = run_eval(normalize_base_url(args.base_url), label=args.label,
                          config=load_config(args.config), library=ProfileStore(args.profiles).load(),
                          data=load_questions(args.questions), model=args.model)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    elif args.command == "first-sentence":
        output = build_first_sentence_report(json.loads(args.results.read_text("utf-8"))) + "\n"
    else:
        output = build_report(json.loads(args.baseline.read_text("utf-8")),
                              json.loads(args.candidate.read_text("utf-8"))) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, "utf-8")
    print(f"已寫入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
