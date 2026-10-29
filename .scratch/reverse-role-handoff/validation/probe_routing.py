# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Check synthetic routing cases with the saved local model on an isolated port."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.config.loader import load_config
from src.llm.llamacpp import ensure_server, shutdown_llama_server
from src.profiles.routing import route_question
from src.profiles.store import ProfileStore, profile_config


def main():
    base = load_config()
    library = ProfileStore(ROOT / 'config/avatar_profiles.yaml').load()
    profiles = {p['id']: p for p in library['profiles']}
    main_id, specialist_id = (library['pair'][key] for key in ('main', 'specialist'))
    config = profile_config(base, profiles[specialist_id])
    if config.llm.provider != 'llamacpp':
        raise RuntimeError('This probe requires the saved local llama.cpp model.')
    port = 18080
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError('The isolated probe port is already in use.')
    prior_weather = [
        {'role': 'user', 'content': '明天台北中正區的天氣如何？'},
        {'role': 'assistant', 'content': '剛剛談的是台北中正區明天的天氣。'},
    ]
    mixed = [
        {'role': 'user', 'content': '明天天氣如何？也介紹一下你們的服務。'},
        {'role': 'assistant', 'content': '您想先詢問天氣，還是服務介紹？'},
    ]
    cases = [
        ('services', specialist_id, '介紹你們的服務', [], 'answer', 'zh-TW'),
        ('outside_main_knowledge', specialist_id, '解釋量子力學', [], 'answer', 'zh-TW'),
        ('two_cities_general', specialist_id, '比較台北和高雄的公司服務', [], 'answer', 'zh-TW'),
        ('weather', specialist_id, '明天台北會下雨嗎？', [], 'specialist', 'zh-TW'),
        ('hiking', specialist_id, '明天適合爬山嗎？', prior_weather, 'specialist', 'zh-TW'),
        ('weekend_followup', specialist_id, '那週末呢？', prior_weather, 'specialist', 'zh-TW'),
        ('mixed', specialist_id, '明天天氣如何？也介紹一下你們的服務。', [], 'clarify', 'zh-TW'),
        ('mixed_choose_main', specialist_id, '先介紹服務', mixed, 'answer', 'zh-TW'),
        ('mixed_choose_weather', specialist_id, '先說明天的天氣', mixed, 'specialist', 'zh-TW'),
        ('forward_weather', main_id, '明天台北會下雨嗎？', [], 'specialist', 'zh-TW'),
        ('main_general', main_id, '介紹你們的服務', [], 'answer', 'zh-TW'),
        ('english_services', specialist_id, 'Please introduce your services.', [], 'answer', 'en-US'),
        ('english_hiking', specialist_id, 'Is tomorrow a good day for hiking?', prior_weather, 'specialist', 'en-US'),
        ('english_mixed', specialist_id, 'What is the weather tomorrow? Also introduce your services.', [], 'clarify', 'en-US'),
    ]
    results = []
    try:
        config.llm.base_url = ensure_server(config.llm.model,
            extra_dir=config.llm.llamacpp_dir, host='127.0.0.1', port=port,
            ctx=max(4096, min(config.llm.llamacpp_ctx, 8192)))
        for label, current, question, history, expected, locale in cases:
            config.conversation.locale = locale
            started = time.monotonic()
            try:
                routed = route_question(config, library, current, question, history,
                                       {'county': '臺北市', 'town': '中正區'})
                actual = routed['route']
            except Exception as exc:
                actual = type(exc).__name__
            result = dict(case=label, current_role=current, expected=expected, actual=actual,
                          passed=actual == expected, seconds=round(time.monotonic() - started, 3))
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        shutdown_llama_server()
    output = dict(at=datetime.now(timezone.utc).isoformat(), model=config.llm.model,
                  passed=sum(item['passed'] for item in results), total=len(results), cases=results)
    Path(__file__).with_name('routing-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    return 0 if all(item['passed'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
