# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Issue 04 quality evaluation: fixed question set, automatic checks and report."""
from __future__ import annotations

from collections import Counter
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from scripts.eval_llm_quality import (
    QUESTIONS_PATH, build_report, check_answer, load_questions, main, run_eval,
)
from src.config.schema import Config
from src.profiles.store import ProfileStore

SIMPLE = "[[MODE:SIMPLE]]\n[[SPEECH]]\n馬拉斯客灣位於 M87 星雲。\n[[END]]"
BOARD = ('[[MODE:BOARD]]\n[[SPEECH]]\n安裝分成三個步驟，細節已整理在看板。\n[[BOARD_JSON]]\n'
         '{"title":"安裝步驟","items":[{"title":"下載","content":"從官方網站下載安裝檔。"},'
         '{"title":"執行","content":"執行安裝程式並依指示操作。"}]}\n[[END]]')


def test_a_complete_reply_passes_every_check():
    checks = check_answer(SIMPLE, max_chars=200, expected_mode="SIMPLE", expected_terms=["m87"])
    assert {name: check["passed"] for name, check in checks.items()} == {
        "format": True, "simplified": True, "length": True, "mode": True, "terms": True}


def test_board_reply_is_parsed_and_board_text_is_checked_for_simplified_characters():
    checks = check_answer(BOARD.replace("依指示操作", "依指示操作这里"), max_chars=200,
                          expected_mode="BOARD")
    assert checks["format"]["passed"] and checks["mode"]["passed"]
    assert checks["simplified"] == {"passed": False, "value": "这"}


def test_truncated_or_malformed_replies_fail_the_format_check():
    for raw in (SIMPLE.removesuffix("\n[[END]]"),
                BOARD.replace('"items":[', '"items":'),
                "[[MODE:SIMPLE]]\n[[SPEECH]]\n好。\n[[BOARD_JSON]]\n{}\n[[END]]",
                "好的，馬拉斯客灣在 M87 星雲。"):
        assert check_answer(raw, max_chars=200)["format"]["passed"] is False


def test_spoken_length_counts_visible_characters_against_the_cap():
    speech = "這是一句很長的回答。" * 3  # 30 characters
    raw = f"[[MODE:SIMPLE]]\n[[SPEECH]]\n{speech}\n[[END]]"
    assert check_answer(raw, max_chars=30)["length"] == {"passed": True, "value": 30}
    assert check_answer(raw, max_chars=29)["length"]["passed"] is False


def test_traditional_text_with_shared_characters_is_not_flagged_as_simplified():
    raw = "[[MODE:SIMPLE]]\n[[SPEECH]]\n台灣的里長說皇后和范先生一起去游泳，這裡著名的為什麼。\n[[END]]"
    assert check_answer(raw, max_chars=200)["simplified"] == {"passed": True, "value": ""}
    flagged = "[[MODE:SIMPLE]]\n[[SPEECH]]\n这里着实为什么发生了历史。\n[[END]]"
    assert check_answer(flagged, max_chars=200)["simplified"]["value"] == "这着实为么发历"


class _FakeLlamaServer:
    """OpenAI-compatible endpoint: routes everything to the main role, answers briefly."""

    REPLY = "[[MODE:SIMPLE]]\n[[SPEECH]]\n好的，馬拉斯客灣位於M87星雲。\n[[END]]"

    def __init__(self):
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, body, content_type="application/json"):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(json.dumps({"object": "list", "data": [
                    {"id": "gemma-4-E2B_q4_0-it.gguf", "object": "model"}]}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append(body)
                if not body.get("stream"):
                    decision = {"route": "answer", "clarification": "", "county": "", "town": "",
                                "kind": "", "start_date": "", "end_date": "", "context": ""}
                    self._send(json.dumps({"id": "r", "object": "chat.completion", "created": 0,
                        "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(decision)}}]}).encode())
                    return
                events = []
                for index, piece in enumerate((server.REPLY[:20], server.REPLY[20:], "")):
                    delta = {"content": piece} if piece else {}
                    events.append({"id": "c", "object": "chat.completion.chunk", "created": 0,
                                   "model": body["model"], "choices": [{"index": 0, "delta": delta,
                                   "finish_reason": None if piece else "stop"}]})
                events.append({"id": "c", "object": "chat.completion.chunk", "created": 0,
                               "model": body["model"], "choices": [],
                               "usage": {"prompt_tokens": 900, "completion_tokens": 20,
                                         "total_tokens": 920}})
                stream = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
                self._send((stream + "data: [DONE]\n\n").encode(), "text/event-stream")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_llama():
    server = _FakeLlamaServer()
    yield server
    server.close()


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr("src.profiles.store.avatar_settings",
                        lambda _: {"enabled": False, "dataset_ids": []})
    return ProfileStore(tmp_path / "profiles.yaml").initialize(Config())


def test_run_asks_every_question_through_the_production_routing_and_answer_path(
        fake_llama, library):
    data = load_questions()
    result = run_eval(fake_llama.url, label="E2B", config=Config(), library=library, data=data)

    assert result["label"] == "E2B"
    assert result["model"] == "gemma-4-E2B_q4_0-it"
    items = {item["id"]: item for item in result["items"]}
    assert len(items) == 30
    # Routing correctness against the fixed expectations.
    for question in data["questions"]:
        item = items[question["id"]]
        assert item["route"] == "answer"
        assert item["route_correct"] is (question["expected_route"] == "answer")
    # A clarification has no answer; every other question is answered once.
    assert items["h06"]["answer"] is None
    answered = [item for item in result["items"] if item["answer"] is not None]
    assert len(answered) == 29
    assert all(item["answer"]["checks"]["format"]["passed"] for item in answered)
    assert answered[0]["answer"]["raw"] == _FakeLlamaServer.REPLY
    assert answered[0]["answer"]["first_speech_seconds"] is not None

    answers = [body for body in fake_llama.requests if body.get("stream")]
    routings = [body for body in fake_llama.requests if not body.get("stream")]
    assert len(routings) == 30 and len(answers) == 29
    # Same grammar, thinking switch and prompt pipeline as a live turn.
    assert all(body["grammar"].startswith("root ::= (simple | board)") for body in answers)
    assert all(body["chat_template_kwargs"] == {"enable_thinking": False}
               for body in answers + routings)
    systems = {body["messages"][-1]["content"]: body["messages"][0]["content"] for body in answers}
    assert "位於m87星雲" in systems["馬拉斯客灣在哪裡？"]
    assert "本輪氣象工具資料" in systems["明天臺北市中正區最高溫幾度？"]
    assert "本輪氣象工具資料" not in systems["解釋量子力學"]
    # History questions carry their earlier turns.
    hiking = next(body for body in answers if body["messages"][-1]["content"] == "明天適合爬山嗎？")
    assert hiking["messages"][1]["content"] == "明天台北中正區的天氣如何？"


def test_report_puts_both_models_side_by_side_and_flags_weaker_routing(fake_llama, library):
    data = load_questions()
    baseline = run_eval(fake_llama.url, label="Qwen3.5-9B", config=Config(), library=library,
                        data=data, model="Qwen3.5-9B-UD-Q4_K_XL")
    candidate = copy.deepcopy(baseline)
    candidate.update(label="E2B", model="gemma-4-E2B_q4_0-it")
    items = {item["id"]: item for item in candidate["items"]}
    for key in ("g01", "g02", "r01"):
        items[key].update(route="clarify", route_correct=False)
    items["g03"]["answer"]["speech"] = "我们提供 A|B 两种服务。"
    items["g03"]["answer"]["checks"]["simplified"] = {"passed": False, "value": "们两种务"}

    report = build_report(baseline, candidate)

    assert "| 路由正確率 | 19/30 | 16/30 |" in report
    assert "| 無簡體字 | 29/29 | 28/29 |" in report
    assert "E2B 路由正確率比 Qwen3.5-9B 少 3 題" in report
    assert "關鍵字初篩" in report
    # Per-question rows: the question, both answers, pipes escaped for Markdown.
    assert "請只回答「語音測試正常」。不要補充其他內容。" in report
    assert "我们提供 A\\|B 两种服务。" in report
    assert "簡體：们两种务" in report
    assert report.count("### ") == 30


def test_report_does_not_flag_equal_routing(fake_llama, library):
    data = load_questions()
    baseline = run_eval(fake_llama.url, label="Qwen3.5-9B", config=Config(), library=library,
                        data=data, model="Qwen3.5-9B-UD-Q4_K_XL")
    candidate = dict(copy.deepcopy(baseline), label="E2B")
    assert "關鍵字初篩" not in build_report(baseline, candidate).split("## 逐題並排")[0]


def test_command_line_runs_a_server_and_writes_the_report(fake_llama, library, tmp_path):
    profiles = tmp_path / "profiles.yaml"
    assert profiles.is_file()  # written by the library fixture
    for label in ("9B", "E2B"):
        assert main(["run", "--base-url", fake_llama.url, "--label", label,
                     "--profiles", str(profiles), "--output", str(tmp_path / f"{label}.json")]) == 0
    assert main(["report", "--baseline", str(tmp_path / "9B.json"),
                 "--candidate", str(tmp_path / "E2B.json"),
                 "--output", str(tmp_path / "report.md")]) == 0
    report = (tmp_path / "report.md").read_text("utf-8")
    assert report.startswith("<!-- Copyright (c) 2026 HongXian0903.")
    assert "| 路由正確率 | 19/30 | 19/30 |" in report


def test_wrong_mode_and_missing_terms_are_reported():
    checks = check_answer(SIMPLE, max_chars=200, expected_mode="BOARD", expected_terms=["玉山"])
    assert checks["mode"] == {"passed": False, "value": "SIMPLE"}
    assert checks["terms"] == {"passed": False, "value": "玉山"}


def test_fixed_set_has_thirty_questions_across_the_four_categories():
    questions = load_questions(QUESTIONS_PATH)["questions"]
    assert len(questions) == 30
    assert len({item["id"] for item in questions}) == 30
    counts = Counter(item["category"] for item in questions)
    assert set(counts) == {"general", "rag", "weather", "handoff"}
    assert min(counts.values()) >= 6
    # The recorded console voice-test prompt is part of the set.
    assert any(item["source"] == "voice-test-history"
               and item["text"] == "請只回答「語音測試正常」。不要補充其他內容。" for item in questions)
    assert any(item["source"].startswith("knowledge-base:") for item in questions)
    # Handoff questions leave the current role (or ask which topic comes first).
    for item in questions:
        if item["category"] == "handoff":
            stays = {"main": "answer", "weather": "specialist"}[item["role"]]
            assert item["expected_route"] != stays
