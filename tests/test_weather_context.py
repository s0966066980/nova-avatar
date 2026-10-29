# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Keep a week of source facts and previous answers within a bounded request."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config.schema import Config
from src.llm.engines.openai import OpenAILLM
from src.llm.response_protocol import BoardItem, SessionBoardContext
from src.profiles.weather import SOURCE, SOURCE_URL, TAIPEI, weather_prompt


def forecast_facts(days=7):
    start = datetime(2026, 10, 29, tzinfo=TAIPEI)
    values = {'temperature_c': 25, 'max_temperature_c': 28, 'min_temperature_c': 22,
              'max_apparent_temperature_c': 29, 'min_apparent_temperature_c': 21,
              'precipitation_probability_12h': None, 'weather': '多雲短暫陣雨'}
    series = {name: [] for name in values}
    for index in range(days * 2):
        begin = start + timedelta(hours=index * 12)
        end = begin + timedelta(hours=12)
        for name, value in values.items():
            if name.startswith('precipitation') and index >= 6:
                continue
            series[name].append(dict(start=begin.isoformat(), end=end.isoformat(), value=value))
    return dict(status='available', source=SOURCE, source_url=SOURCE_URL, county='臺北市', town='',
        kind='forecast', fetched_at=start.isoformat(), issued_at=None, timezone='Asia/Taipei',
        start_date=start.date().isoformat(), end_date=(start + timedelta(days=days - 1)).date().isoformat(),
        series=series, probability_note='一週產品的降雨機率僅前三天提供；未提供不代表 0%。')


def points(series):
    return Counter(json.dumps([name, item['start'], item['end'], item['value']], ensure_ascii=False)
                   for name, items in series.items() for item in items)


@pytest.mark.parametrize('extra', ['none', 'conflict', 'different_interval'])
def test_forecast_transport_preserves_every_interval_value_and_source(extra):
    original = forecast_facts()
    if extra == 'conflict':
        original['series']['temperature_c'].append({**original['series']['temperature_c'][0], 'value': 26})
    if extra == 'different_interval':
        original['series']['temperature_c'][0]['end'] = None
    before = deepcopy(original)
    payload = json.loads(weather_prompt(original).split('\n')[-1])
    restored = {}
    for row in payload['forecast_periods']:
        for name, value in row.items():
            if name not in {'start', 'end'}:
                restored.setdefault(name, []).append(dict(start=row['start'], end=row['end'], value=value))
    assert points(restored) == points(original['series'])
    assert {k: v for k, v in payload.items() if k != 'forecast_periods'} == {
        k: v for k, v in original.items() if k != 'series'}
    assert original == before
    assert all('precipitation_probability_12h' not in row
               for row in payload['forecast_periods'] if row['start'][:10] >= '2026-11-01')


def test_observation_and_failure_facts_remain_unchanged():
    for result in [dict(status='available', kind='current', station='臺北', temperature_c=25,
                        observed_at='2026-10-29T12:00:00+08:00', humidity_percent=None),
                   dict(status='unavailable', source=SOURCE)]:
        assert json.loads(weather_prompt(result).split('\n')[-1]) == result


def test_today_then_week_fits_without_discarding_history_or_displayed_board(monkeypatch):
    from src.llm import context_usage
    config = Config()
    config.llm.provider = 'llamacpp'
    config.llm.assistant_profile.assistant_name = '天氣助手'
    config.llm.assistant_profile.system_prompt = '依本輪氣象資料回答，說明地點與適用時段。'
    llm = OpenAILLM(config=config, api_key='test', base_url='http://weather-context-test/v1')
    # The local estimate counts each CJK character as a token, an upper bound
    # for the deployed tokenizer; the separate live probe measures Qwen's.
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'default_generation_settings': {'n_ctx': 8192}}
    monkeypatch.setattr(context_usage.requests, 'get', lambda *_, **__: Response())
    assert context_usage.deployed_capacity(llm.base_url, refresh=True) == 8192
    llm._client = Mock()
    llm._client.chat.completions.create.side_effect = lambda **_: [SimpleNamespace(choices=[
        SimpleNamespace(delta=SimpleNamespace(content='[[MODE:SIMPLE]]\n[[SPEECH]]\n臺北市今天多雲，請留意降雨並攜帶雨具。\n[[END]]'))])]
    info = {'on_mode': lambda *_: None}
    llm.generate_response('今天台北天氣如何？', stream_to_avatar=False,
        datainfo=info, rag_context=weather_prompt(forecast_facts(1)))
    board = SessionBoardContext(turn_id='today', title='臺北市今天天氣', summary=None,
        items=[BoardItem(title='上午', content='多雲，22–28°C；降雨機率未提供。'),
               BoardItem(title='下午', content='短暫陣雨，請留意天氣變化。')])
    llm.set_last_board(board)
    history = deepcopy(llm.conversation_history)
    llm.generate_response('未來一週天氣如何？', stream_to_avatar=False,
        datainfo=info, rag_context=weather_prompt(forecast_facts()))
    assert llm.context_usage['over_capacity'] is False
    assert llm.context_usage['input_tokens'] + llm.context_usage['reserved_output_tokens'] <= 8192
    assert llm.conversation_history[:2] == history
    assert len(llm.conversation_history) == 4
    assert llm.get_last_board() is board
    assert llm._client.chat.completions.create.call_count == 2
