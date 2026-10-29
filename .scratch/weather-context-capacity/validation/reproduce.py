# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Replay two synthetic questions with CWA facts and the real local tokenizer."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.config.loader import load_config
from src.llm.context_usage import ContextCapacityError
from src.llm.engines.openai import OpenAILLM
from src.llm.response_protocol import BoardItem, SessionBoardContext
from src.llm.llamacpp import ensure_server, server_status, shutdown_llama_server
from src.profiles.store import ProfileStore, profile_config
from src.profiles.weather import CwaWeather, TAIPEI, WeatherQuery, weather_prompt


async def facts():
    path = Path(__file__).with_name('weather-fixtures.json')
    if path.exists():
        return json.loads(path.read_text())
    now = datetime.now(TAIPEI).date()
    weather = CwaWeather()
    results = []
    for days in (1, 7):
        result = await weather.query(WeatherQuery('臺北市', '', 'forecast', now.isoformat(),
            (now + timedelta(days=days - 1)).isoformat()))
        if result['status'] != 'available':
            raise RuntimeError('Weather fixture unavailable: ' + result['status'])
        results.append(result)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    return results


def main():
    base = load_config()
    library = ProfileStore(ROOT / 'config/avatar_profiles.yaml').load()
    profile = next(p for p in library['profiles'] if p['id'] == library['pair']['specialist'])
    config = profile_config(base, profile)
    if config.llm.provider != 'llamacpp':
        raise RuntimeError('Use the saved local llama.cpp model for this probe.')
    fixtures = asyncio.run(facts())
    owned = False
    try:
        if not server_status()['running']:
            port = 18080
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    raise RuntimeError('Isolated probe port is already in use.')
            config.llm.base_url = ensure_server(config.llm.model, extra_dir=config.llm.llamacpp_dir,
                host='127.0.0.1', port=port, ctx=config.llm.llamacpp_ctx)
            owned = True
        else:
            config.llm.base_url = 'http://127.0.0.1:8080/v1'
        llm = OpenAILLM(config=config, api_key='local-probe',
                        base_url=config.llm.base_url, model=config.llm.model)
        # This failure happens before generation: keep only tokenization real.
        # A fixed completion lets us replay history without speaking to the UI.
        real_model = '--real-model' in sys.argv
        def reply(**_):
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content='[[MODE:SIMPLE]]\n[[SPEECH]]\n今天臺北市多雲，請留意降雨，出門記得攜帶雨具並注意氣溫變化。\n[[END]]'))])]
        if not real_model:
            llm._client = Mock()
            llm._client.chat.completions.create.side_effect = reply
        cases = list(zip(['今天台北天氣如何？', '未來一週天氣如何？'], fixtures))
        original_history = None
        if '--replay-first' in sys.argv:
            saved = json.loads(Path(__file__).with_name('before-first-turn.json').read_text())
            for message in saved['history']:
                llm.add_to_history(message['role'], message['content'])
            if saved['board']:
                board = saved['board']
                llm.set_last_board(SessionBoardContext(**{**board, 'items': [BoardItem(**item) for item in board['items']]}))
            original_history = saved['history']
            cases = cases[1:]
        results = []
        for index, (question, result) in enumerate(cases):
            try:
                answer = llm.generate_response(question, stream_to_avatar=False, rag_context=weather_prompt(result),
                    datainfo={'turn_id': f'weather-{index}', 'generation': 0,
                              'on_mode': lambda *_: None, 'on_board': lambda *_: None,
                              'incremental_board': True})
                assert answer.strip(), 'the model must deliver a readable answer'
                for board in list(llm._pending_boards.values()):
                    for position in range(len(board.items)):
                        llm.acknowledge_board_display(turn_id=board.turn_id,
                            board_id=board.turn_id, item_index=position)
                error = None
            except ContextCapacityError:
                error = 'context_capacity'
            usage = llm.context_usage or {}
            item = dict(question=question, error=error, facts_chars=len(weather_prompt(result)),
                retained_messages=len(llm.conversation_history),
                previous_board_chars=len(json.dumps(asdict(llm.get_last_board()) if llm.get_last_board() else None, ensure_ascii=False)),
                **{k: usage.get(k) for k in ['capacity', 'input_tokens', 'reserved_output_tokens', 'estimated']})
            results.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
            if real_model and original_history is None and len(results) == 1:
                Path(__file__).with_name('first-turn-replay.json').write_text(json.dumps(
                    {'history': llm.conversation_history, 'board': asdict(llm.get_last_board()) if llm.get_last_board() else None}, ensure_ascii=False, indent=2) + '\n')
        filename = 'replay-first.json' if original_history is not None else 'reproduction-real.json' if real_model else 'reproduction.json'
        Path(__file__).with_name(filename).write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        if original_history is not None:
            assert llm.conversation_history[:len(original_history)] == original_history
        assert all(item['estimated'] is False and item['capacity'] for item in results), 'real tokenizer and deployed capacity are required'
        assert all(item['error'] is None for item in results), 'the weekly followup must fit the deployed context'
    finally:
        if owned:
            shutdown_llama_server()


if __name__ == '__main__':
    main()
