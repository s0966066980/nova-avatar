# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Public egress, deadlines, privacy and the actual server-owned turn seam."""
import asyncio
from copy import deepcopy
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.web_search import service
from src.profiles.knowledge_scope import web_access as settings
from src.server import web_evidence
from tests.llm_fakes import FakeLlm
from tests.session_fakes import FakeAvatar, FakeSegmenter
from src.config.schema import Config
from src.server.voice_session import VoiceTurnSession
from tests.speech_fakes import spoken_answer


@pytest.fixture(autouse=True)
def offline_evidence_model(monkeypatch):
    # Network inference is exercised by the live probes, never by CI fixtures.
    async def selected(config, question, result):
        source = result['sources'][0]
        return {'mode': 'context', 'items': [{'source_id': source['id'],
                'quote': source.get('text') or source.get('snippet') or ''}]}
    monkeypatch.setattr('src.web_search.synthesis.summarize', AsyncMock(side_effect=selected))


def test_policy_and_old_profile_defaults():
    assert settings() == {'enabled': False, 'allowed_domains': []}
    assert settings({'enabled': True, 'allowed_domains': ['Gov.Tw', 'gov.tw']})['allowed_domains'] == ['gov.tw']
    for raw in ({'enabled': 'yes'}, {'allowed_domains': ['https://gov.tw']}, {'allowed_domains': ['*.gov.tw']}, {'url': 'http://localhost'}):
        with pytest.raises(ValueError):
            settings(raw)


@pytest.mark.parametrize('url', ['http://localhost', 'http://127.0.0.1', 'http://127.1',
    'http://169.254.169.254/', 'http://10.1.1.1', 'http://[::1]', 'file:///etc/passwd',
    'https://example.com@localhost', 'https://a.lan', 'https://example.com:8010/',
    'https://example.com\\@127.0.0.1/', 'javascript:alert(1)', 'http://2130706433'])
def test_public_url_rejects_private_and_non_http(url):
    with pytest.raises(ValueError):
        service.public_url(url)


def test_domain_boundary_and_safe_public_url():
    assert service.public_url('https://www.gov.tw/info#top', ['gov.tw']) == 'https://www.gov.tw/info'
    for host in ('evilgov.tw', 'gov.tw.evil.com'):
        with pytest.raises(ValueError):
            service.public_url('https://' + host, ['gov.tw'])


def test_dns_rebinding_and_mixed_answers_rejected():
    async def run():
        loop = asyncio.get_running_loop()
        for addresses in (['127.0.0.1'], ['8.8.8.8', '10.0.0.1'], ['169.254.169.254']):
            infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443)) for a in addresses]
            with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=infos)):
                with pytest.raises(OSError):
                    await service.PublicResolver().resolve('example.com', 443)
        with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=[(2, 1, 6, '', ('8.8.8.8', 443))])):
            assert (await service.PublicResolver().resolve('example.com', 443))[0]['host'] == '8.8.8.8'
    asyncio.run(run())


def test_redirect_to_internal_address_never_requested():
    class Response:
        status = 302
        headers = {'Location': 'http://127.0.0.1/admin'}
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert kwargs['allow_redirects'] is False
        return Response()
    async def run():
        with pytest.raises(ValueError):
            await service.read_page(SimpleNamespace(get=get), 'https://example.com', [])
    asyncio.run(run())
    assert len(calls) == 1


def hit(n=1):
    return {'href': f'https://example.com/{n}', 'title': '活動', 'body': '最新活動資訊'}


def test_search_caps_fallback_domain_filter_and_page_failures():
    async def run():
        with patch.object(service, 'search_engine', side_effect=[[], [hit(n) for n in range(10)]]) as engines, patch.object(
                service, 'read_page', AsyncMock(side_effect=[('https://example.com/0', '官方全文'), ValueError(), ValueError()])) as read:
            result = await service.search('活動')
            assert result['status'] == 'partial'
            assert len(result['sources']) <= 5
            assert read.call_count == 3
            assert [c.args[1] for c in engines.call_args_list] == ['duckduckgo', 'brave']
        with patch.object(service, 'search_engine', return_value=[hit()]) as engines, patch.object(
                service, 'read_page', AsyncMock(side_effect=ValueError())):
            result = await service.search('活動')
            assert result['status'] == 'snippets'
            assert engines.call_count == 1
        with patch.object(service, 'search_engine', return_value=[hit()]), patch.object(service, 'read_page', AsyncMock()) as read:
            result = await service.search('活動', ['gov.tw'])
            assert result['status'] == 'empty'
            read.assert_not_called()
    asyncio.run(run())


def test_shared_deadline_retains_snippets_and_cancels_page_work():
    async def slow(*args):
        await asyncio.sleep(1)
    async def run():
        with patch.object(service, 'BUDGET', .02), patch.object(service, 'search_engine', return_value=[hit()]), patch.object(service, 'read_page', slow):
            result = await service.search('活動')
            assert result['status'] == 'snippets'
    asyncio.run(run())


def test_cache_ttl_role_policy_and_reset_isolation():
    c = web_evidence.EvidenceCache()
    policy = settings({'enabled': True})
    with patch.object(web_evidence.time, 'monotonic', return_value=10):
        c.put('role1', policy, {'query': '台北活動', 'sources': [hit()]})
    with patch.object(web_evidence.time, 'monotonic', return_value=309):
        assert c.previous('role1', policy)
        assert c.previous('role2', policy) is None
        assert web_evidence.EvidenceCache().previous('role1', policy) is None
        assert c.previous('role1', {**policy, 'allowed_domains': ['gov.tw']}) is None
    with patch.object(web_evidence.time, 'monotonic', return_value=310):
        assert c.previous('role1', policy) is None
    c.clear()
    assert not c.entries


def session():
    import json
    config = Config()
    config.conversation_snapshot = True
    config.profile_rag = {'enabled': False, 'dataset_ids': []}
    avatar, events = FakeAvatar(), []
    voice = VoiceTurnSession(7, config, avatar, llm=FakeLlm('活動資料'))
    voice._segmenter = FakeSegmenter()
    voice.attach_event_sink(lambda raw: events.append(json.loads(raw)))
    voice.config.profile_web_search = settings({'enabled': True})
    voice.config.profile_id = 'role1'
    return voice, avatar, events


RESULT = {'status': 'available', 'query': '台北活動', 'sources': [
    {'id': '1', 'url': 'https://example.com/', 'title': '活動', 'snippet': '片段', 'text': '全文', 'kind': 'page'}]}


def test_real_turn_uses_raw_question_not_attachment_or_rag_and_cancels_stale_result():
    async def run():
        from src.server.voice_session import AnswerInputs
        voice, _, events = session()
        try:
            planner = AsyncMock(return_value={'search': True, 'query': '台北活動', 'reuse': False})
            with patch('src.web_search.planner.plan', planner), patch('src.web_search.service.search', AsyncMock(return_value=deepcopy(RESULT))), patch.object(
                    voice, '_answer_inputs', AsyncMock(return_value=AnswerInputs('PRIVATE ATTACHMENT', {'status': 'matched', 'sources': []}))):
                await voice.start_text_turn('台北有什麼活動')
                await voice._turn_task
                assert planner.call_args.args[1] == '台北有什麼活動'
                assert planner.call_args.args[2] == []
                assert 'PRIVATE ATTACHMENT' not in str(planner.call_args)
                request = voice._llm.request
                assert request.web.result.sources[0].text == '全文'
                assert not request.retrieval and '全文' not in request.role_context
                assert all('text' not in s for e in events if e['type'] == 'web_search_result' for s in e['sources'])
            gate, started = asyncio.Event(), asyncio.Event()
            async def pending(*args):
                started.set()
                await gate.wait()
                return deepcopy(RESULT)
            with patch('src.web_search.planner.plan', planner), patch('src.web_search.service.search', pending):
                await voice.start_text_turn('重新查台北最新活動', interrupt=True)
                await started.wait()
                before = len([e for e in events if e['type'] == 'web_search_result'])
                await voice.interrupt()
                gate.set()
                await asyncio.sleep(.01)
                assert len([e for e in events if e['type'] == 'web_search_result']) == before
                assert voice._llm.calls == 1  # only the first turn was answered
        finally:
            await voice.close()
    asyncio.run(run())


def test_legacy_web_turn_bounds_speech_at_fragments_without_playing_it():
    async def run():
        from nova_contracts.llm import (AssistantProfile, FragmentReviewContext, ModelChunk, ReplyDone,
                                        ReplyStarted, SpeechEnd, SpokenDelta)
        from src.server.voice_session import AnswerInputs

        def answer(request):
            # The service tells the core to bound web speech at 12 spoken characters.
            yield ReplyStarted(turn_id=request.turn_id, bounded=True, review=FragmentReviewContext(
                profile=AssistantProfile(), web_max_chars=12))
            yield ModelChunk(llm_sequence=0)
            yield SpokenDelta(text='台北有市集。台北', llm_sequence=0)
            yield ModelChunk(llm_sequence=1)
            yield SpokenDelta(text='有展覽。', llm_sequence=1)
            yield SpokenDelta(text='這句超出口語預算。', llm_sequence=1)
            yield SpeechEnd()
            yield ReplyDone(spoken='', visible='')

        voice, avatar, events = session()
        voice._llm.script = answer
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': True, 'query': '台北活動', 'reuse': False})), patch(
                    'src.web_search.service.search', AsyncMock(return_value=deepcopy(RESULT))), patch.object(
                    voice, '_answer_inputs', AsyncMock(return_value=AnswerInputs('台北有什麼活動', None))):
                await voice.start_text_turn('台北有什麼活動')
                await voice._turn_task
            assert voice._pipeline_mode == 'legacy'
            # The core still cuts the web answer so the service can bound it: the
            # over-budget fragment is dropped and only the whole answer is played.
            assert [text for text, _ in avatar.messages] == ['臺北有市集。臺北有展覽。']
            assert [e['text'] for e in events if e['type'] == 'assistant_response'] == ['臺北有市集。臺北有展覽。']
        finally:
            await voice.close()
    asyncio.run(run())


def test_disabled_weather_and_no_search_never_call_external_service():
    async def run():
        from src.server.voice_session import AnswerInputs
        voice, _, _ = session()
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': False, 'query': '', 'reuse': False})) as planner, patch('src.web_search.service.search', AsyncMock()) as external:
                voice.config.profile_web_search['enabled'] = False
                await voice._web_inputs(AnswerInputs('hello', None), 'hello', 'unused', 0, None)
                planner.assert_not_called()
                voice.config.profile_web_search['enabled'] = True
                await voice._web_inputs(AnswerInputs('weather', None), 'weather', 'unused', 0, {'weather': {}})
                planner.assert_not_called()
                with patch.object(voice, '_is_current', return_value=True):
                    await voice._web_inputs(AnswerInputs('hello', None), 'hello', 'unused', 0, None)
                external.assert_not_called()
        finally:
            await voice.close()
    asyncio.run(run())


def test_followup_reuses_evidence_but_explicit_refresh_fetches_again_and_reset_clears():
    async def run():
        from src.server.voice_session import AnswerInputs
        voice, _, _ = session()
        policy = voice.config.profile_web_search
        voice._web_cache.put('role1', policy, deepcopy(RESULT))
        try:
            with patch.object(voice, '_is_current', return_value=True), patch('src.web_search.planner.plan', AsyncMock(
                    return_value={'search': True, 'query': '台北活動', 'reuse': True})), patch(
                    'src.web_search.service.search', AsyncMock(return_value=deepcopy(RESULT))) as external:
                followup = await voice._web_inputs(AnswerInputs('地點？', None), '活動地點在哪裡？', 'turn', 0, None)
                assert followup.web_result['reused']
                external.assert_not_called()
                refresh = await voice._web_inputs(AnswerInputs('最新', None), '請重新查最新活動', 'turn', 0, None)
                assert not refresh.web_result.get('reused')
                assert external.call_count == 1
            voice.reset_conversation()
            assert voice._web_cache.previous('role1', policy) is None
        finally:
            await voice.close()
    asyncio.run(run())


def test_enabled_role_waits_for_routing_before_planning_or_answering():
    async def run():
        voice, _, _ = session()
        from unittest.mock import Mock
        began, release = asyncio.Event(), asyncio.Event()
        async def route(*args):
            began.set()
            await release.wait()
            return {'context': 'chosen role'}
        roles = Mock(enabled=True)
        roles.continues.return_value = False
        roles.before_generate = route
        voice._role_coordinator = roles
        try:
            with patch.object(voice, '_is_current', return_value=True), patch.object(voice, '_answer_turn', AsyncMock()) as answer, patch.object(
                    voice, '_route_concurrently', AsyncMock()) as speculate:
                task = asyncio.create_task(voice._generate_turn('最新資訊', 'turn', 0, input_source='text'))
                await began.wait()
                answer.assert_not_called()
                speculate.assert_not_called()
                release.set()
                await task
                assert answer.call_count == 1
        finally:
            voice._role_coordinator = None
            await voice.close()
    asyncio.run(run())


def test_planning_failure_supplies_unverified_context_instead_of_claiming_success():
    async def run():
        from src.server.voice_session import AnswerInputs
        voice, _, events = session()
        try:
            with patch.object(voice, '_is_current', return_value=True), patch('src.web_search.planner.plan', AsyncMock(side_effect=ValueError())), patch(
                    'src.web_search.service.search', AsyncMock()) as external:
                value = await voice._web_inputs(AnswerInputs('最新消息', None), '最新消息', 'turn', 0, None)
                assert value.web_result['status'] == 'planning_failed'
                assert '未能查證' in service.reference_prompt(value.web_result)
                external.assert_not_called()
                assert events[-1]['status'] == 'planning_failed'
        finally:
            await voice.close()
    asyncio.run(run())


def test_search_failure_never_asks_answer_model_to_invent_current_information():
    async def run():
        voice, _, events = session()
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': True, 'query': '台北最新活動', 'reuse': False})), patch(
                    'src.web_search.service.search', AsyncMock(return_value={'status': 'unavailable', 'sources': [], 'query': '台北最新活動'})):
                await voice.start_text_turn('台北最新活動')
                await voice._turn_task
                assert voice._llm.calls == 0
                assert any(e['type'] == 'assistant_response' and '尚未查證' in e['text'] for e in events)
        finally:
            await voice.close()
    asyncio.run(run())


def test_page_bytes_are_bounded_before_html_parsing():
    class Body:
        async def iter_chunked(self, _):
            yield b'a' * 10
            yield b'b' * 10
    class Response:
        status, headers, charset, content = 200, {'Content-Type': 'text/html'}, 'utf-8', Body()
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def raise_for_status(self): pass
    async def run():
        with patch.object(service, 'MAX_BYTES', 15):
            with pytest.raises(ValueError, match='too large'):
                await service.read_page(SimpleNamespace(get=lambda *a, **k: Response()), 'https://example.com', [])
    asyncio.run(run())


SEARCH_PAGE = '''<html><body><div class="body">
<h2>Python downloads</h2>
<a href="https://www.python.org/downloads/">Official Python downloads.</a>
</div></body></html>'''


def test_ddgs_actual_request_uses_instance_header_and_parses_real_engine(monkeypatch):
    """The former UA gets a challenge; replay through real DDGS, not final hit mocks."""
    import httpx
    from ddgs.engines.duckduckgo import Duckduckgo
    from ddgs.http_client2 import HttpClient2
    before = {'User-Agent': 'nova-regression-incompatible'}
    monkeypatch.setattr(Duckduckgo, 'headers', before)
    seen = []
    def request(client, *args, **kwargs):
        agent = client.client.headers.get('User-Agent')
        seen.append(agent)
        assert kwargs['data'] == {'q': 'Python official downloads'}
        return httpx.Response(200, text=SEARCH_PAGE) if agent == 'Mozilla/5.0' else httpx.Response(202, text='challenge')
    monkeypatch.setattr(HttpClient2, 'request', request)
    hits = service.search_engine('Python official downloads', 'duckduckgo', 2)
    assert seen == ['Mozilla/5.0']
    assert hits[0]['href'] == 'https://www.python.org/downloads/'
    assert Duckduckgo.headers == before


@pytest.mark.parametrize('status,reason', [(202, 'challenge'), (429, 'rate_limited'), (500, 'request_failed')])
def test_ddgs_http_restrictions_remain_unavailable_not_empty(monkeypatch, status, reason):
    import httpx
    from ddgs.http_client2 import HttpClient2
    from src.web_search.ddgs_adapter import SearchUnavailable
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        return httpx.Response(status, text=SEARCH_PAGE)
    monkeypatch.setattr(HttpClient2, 'request', request)
    with pytest.raises(SearchUnavailable) as exc:
        service.search_engine('Python official downloads', 'duckduckgo', 2)
    assert exc.value.reason == reason
    assert len(calls) == 1  # No retry or attempt to solve a challenge.


def test_ddgs_valid_empty_page_is_empty_and_missing_engine_cannot_fan_out(monkeypatch):
    import httpx
    from ddgs.ddgs import DDGS
    from ddgs.engines import ENGINES
    from ddgs.http_client2 import HttpClient2
    from src.web_search.ddgs_adapter import SearchUnavailable
    monkeypatch.setattr(HttpClient2, 'request', lambda *a, **k: httpx.Response(200, text='<html><body>No results</body></html>'))
    assert service.search_engine('nonexistent synthetic query', 'duckduckgo', 2) == []
    monkeypatch.delitem(ENGINES['text'], 'duckduckgo')
    with patch.object(DDGS, 'text') as text:
        with pytest.raises(SearchUnavailable, match='engine_missing'):
            service.search_engine('Python', 'duckduckgo', 2)
        text.assert_not_called()


def test_ddgs_version_or_external_network_client_fails_closed(monkeypatch):
    from src.web_search import ddgs_adapter
    from ddgs.ddgs import DDGS
    with pytest.raises(ddgs_adapter.SearchUnavailable, match='engine_not_allowed'):
        service.search_engine('Python', 'auto', 2)
    with monkeypatch.context() as m:
        m.setattr(ddgs_adapter, 'version', lambda _: 'incompatible')
        with pytest.raises(ddgs_adapter.SearchUnavailable, match='incompatible_ddgs'):
            service.search_engine('Python', 'duckduckgo', 2)
    monkeypatch.setattr(DDGS, '_network_client', object())
    with pytest.raises(ddgs_adapter.SearchUnavailable, match='unexpected_network_client'):
        service.search_engine('Python', 'duckduckgo', 2)


def test_web_evidence_reminder_is_request_only_and_not_committed_as_user_text():
    from src.llm.engines.openai import OpenAILLM
    class Question(str):
        request_instructions = '本輪已有公開資料，請重新核對舊拒答。'
    config = Config()
    llm = OpenAILLM(config=config, api_key='test', base_url='http://localhost:9/v1')
    llm.observe_context = False
    question = Question('周杰倫現在幾歲')
    transaction = llm.begin_history_turn(question, turn_id='evidence')
    try:
        with patch.object(llm.client.chat.completions, 'create', return_value=[]) as create:
            list(llm.chat_stream(question, system_prompt='遵守非公開個資限制', history_transaction=transaction))
        sent = create.call_args.kwargs['messages'][-1]['content']
        assert question.request_instructions in sent
        assert str(question) == '周杰倫現在幾歲'
        llm.commit_history_turn(transaction, assistant_text='公開年齡回答', terminal_reason='completed')
        assert llm.conversation_history[0]['content'] == '周杰倫現在幾歲'
        assert all('本輪已有公開資料' not in m['content'] for m in llm.conversation_history)
    finally:
        llm.client.close()


def test_web_request_context_keeps_attachment_parts_and_does_not_mutate_them():
    from src.llm.request_context import RequestQuestion
    from src.llm.engines.openai import OpenAILLM
    class AttachmentQuestion(str):
        parts = [{'type': 'text', 'text': '附件觀察'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}}]
    original = AttachmentQuestion('附件追問')
    wrapped = RequestQuestion(original, '已有公開來源，仍須保護非公開個資。')
    config = Config()
    llm = OpenAILLM(config=config, api_key='test', base_url='http://localhost:9/v1')
    llm.observe_context = False
    try:
        with patch.object(llm.client.chat.completions, 'create', return_value=[]) as create:
            list(llm.chat_stream(wrapped, system_prompt='角色限制'))
        parts = create.call_args.kwargs['messages'][-1]['content']
        assert parts[:2] == original.parts
        assert parts[-1]['text'] == wrapped.request_instructions
        assert len(original.parts) == 2
        assert str(wrapped) == '附件追問'
    finally:
        llm.client.close()


@pytest.mark.parametrize('stream_to_avatar', [True, False])
@pytest.mark.parametrize('question,sentences', [
    ('請查生日', ['生日是公開資料。', '依來源確認日期。']),
    ('公司成立年份', ['這家公司成立於一九八七年。', '依公開公司資料核對。']),
    ('博物館在哪裡', ['博物館位於臺南市安南區。', '地址請參考官方網站。']),
    ('山有多高', ['海拔三千九百五十二公尺。', '已參考官方資料。']),
    ('最新版本', ['完整版本是三點一五點二。', '此為已發布的穩定版本。']),
    ('簡短比較兩種接頭', ['甲接頭只能單向插入。', '乙接頭則可以正反插入。']),
])
def test_web_answer_stops_repetition_before_preview_playback_or_return(stream_to_avatar, question, sentences):
    from src.llm.base import BaseLLM
    from src.llm.request_context import RequestQuestion
    from types import SimpleNamespace
    class RepeatingModel(BaseLLM):
        def chat_stream(self, message, system_prompt=None):
            for sentence in sentences * 20:
                yield sentence
    fragments, preview = [], []
    avatar = SimpleNamespace(put_msg_txt=lambda text, data: fragments.append(text),
                             notify_llm_chunk=lambda text, data: preview.append(text))
    question = RequestQuestion(question, '整理來源')
    question.web_evidence = True
    answer = spoken_answer(RepeatingModel(Config()), question, avatar,
        stream=stream_to_avatar, datainfo={'turn_id': 'web-repeat', 'generation': 1})
    assert answer == ''.join(sentences)
    assert ''.join(fragments) == (answer if stream_to_avatar else '')
    assert ''.join(preview) == (answer if stream_to_avatar else '')


def test_web_speech_budget_keeps_complete_dates_and_closes_degenerate_generator():
    from src.llm.base import BaseLLM
    from src.llm.request_context import RequestQuestion
    from types import SimpleNamespace
    consumed, closed, spoken = [], [], []
    class LongModel(BaseLLM):
        def chat_stream(self, message, system_prompt=None):
            try:
                for sentence in ['公開出生日期是一九七九年一月十八日。', '這段是超出本輪口語預算的額外背景補充資料。', '不得繼續取用。']:
                    consumed.append(sentence)
                    yield sentence
            finally:
                closed.append(True)
    model = LongModel(Config())
    model.response_max_chars = 22
    question = RequestQuestion('生日？', '只答生日')
    question.web_evidence = True
    avatar = SimpleNamespace(put_msg_txt=lambda text, data: spoken.append(text), notify_llm_chunk=lambda *args: None)
    result = spoken_answer(model, question, avatar, datainfo={'turn_id': 'budget', 'generation': 1})
    assert result == '公開出生日期是一九七九年一月十八日。'
    assert spoken == [result]
    assert len(consumed) == 2
    assert closed == [True]


def test_source_selection_rejects_invented_values_and_merges_only_identical_facts():
    from src.web_search.synthesis import validate_selection
    result = {'sources': [{'id': '1', 'snippet': '甲公司成立於1987年。', 'text': ''},
                          {'id': '2', 'snippet': '甲公司成立於1987年。乙公司成立於1990年。', 'text': ''}]}
    selected = validate_selection({'mode': 'extractive', 'items': [
        {'source_id': '1', 'quote': '1987年'}, {'source_id': '2', 'quote': '1987年'}]}, result)
    assert len(selected['items']) == 1
    with pytest.raises(ValueError, match='not in source'):
        validate_selection({'mode': 'extractive', 'items': [{'source_id': '1', 'quote': '1988年'}]}, result)
    with pytest.raises(ValueError):
        validate_selection({'mode': 'extractive', 'items': [{'source_id': '99', 'quote': '1987年'}]}, result)
    compared = validate_selection({'mode': 'context', 'items': [
        {'source_id': '1', 'quote': '1987年'}, {'source_id': '2', 'quote': '1990年'}]}, result)
    assert len(compared['items']) == 2  # Different facts must not be silently merged.


@pytest.mark.parametrize('question,quote', [('甲公司哪年成立', '1987年'), ('地點在哪裡', '臺北市'),
                                         ('完整版本號', '3.15.2'), ('公開出生日期', '1979年1月18日')])
def test_single_fact_uses_validated_quote_without_a_second_model_elaboration(question, quote):
    async def run():
        voice, _, events = session()
        result = deepcopy(RESULT)
        result['sources'][0]['text'] = quote
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': True, 'query': question, 'reuse': False})), patch(
                    'src.web_search.service.search', AsyncMock(return_value=result)), patch(
                    'src.web_search.synthesis.summarize', AsyncMock(return_value={'mode': 'extractive', 'items': [{'source_id': '1', 'quote': quote}]})):
                await voice.start_text_turn(question)
                await voice._turn_task
                assert voice._llm.calls == 0
                assert [e['text'] for e in events if e['type'] == 'assistant_response'] == [quote]
        finally:
            await voice.close()
    asyncio.run(run())


def test_failed_organization_does_not_fall_back_to_reading_raw_search_pages():
    async def run():
        voice, _, events = session()
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': True, 'query': '公開資料', 'reuse': False})), patch(
                    'src.web_search.service.search', AsyncMock(return_value=deepcopy(RESULT))), patch(
                    'src.web_search.synthesis.summarize', AsyncMock(side_effect=ValueError())):
                await voice.start_text_turn('公開資料')
                await voice._turn_task
                assert voice._llm.calls == 0
                assert any('未能整理' in e.get('text', '') for e in events)
        finally:
            await voice.close()
    asyncio.run(run())


def test_context_keeps_valid_quotes_when_another_quote_was_spliced():
    from src.web_search.synthesis import validate_selection
    result = {'sources': [{'id': '1', 'snippet': 'USB-A接頭有方向性。USB-C接頭可正反插。'}]}
    selection = validate_selection({'mode': 'context', 'items': [
        {'source_id': '1', 'quote': 'USB-A接頭可正反插。'},
        {'source_id': '1', 'quote': 'USB-C接頭可正反插。'}]}, result)
    assert selection['items'] == [{'source_id': '1', 'quote': 'USB-C接頭可正反插。'}]
    with pytest.raises(ValueError):
        validate_selection({'mode': 'context', 'items': [{'source_id': '1', 'quote': 'USB-C不支援資料傳輸'}]}, result)


@pytest.mark.parametrize('source,quote', [('-1.5%', '1.5%'), ('3.15.2', '3.15'), ('1492年', '492年')])
def test_selected_numbers_cannot_be_substrings_of_another_value(source, quote):
    from src.web_search.synthesis import validate_selection
    with pytest.raises(ValueError):
        validate_selection({'mode': 'extractive', 'items': [{'source_id': '1', 'quote': quote}]},
                           {'sources': [{'id': '1', 'snippet': source}]})


def test_evidence_windows_find_the_asked_field_after_site_navigation():
    from src.web_search.synthesis import evidence_window
    text = '選單導覽 ' * 300 + '甲公司總部位於新竹科學園區。' + '服務介紹 ' * 200
    window = evidence_window(text, '甲公司總部在哪裡', '甲公司總部地點')
    assert '總部位於新竹科學園區' in window
    assert len(window) <= 641


def test_interrupt_while_organizing_never_speaks_or_commits_stale_quotes():
    async def run():
        voice, avatar, events = session()
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            started.set()
            await release.wait()
            return {'mode': 'extractive', 'items': [{'source_id': '1', 'quote': '過期資料'}]}
        try:
            with patch('src.web_search.planner.plan', AsyncMock(return_value={'search': True, 'query': '公開資料', 'reuse': False})), patch(
                    'src.web_search.service.search', AsyncMock(return_value=deepcopy(RESULT))), patch(
                    'src.web_search.synthesis.summarize', delayed):
                await voice.start_text_turn('公開資料')
                await asyncio.wait_for(started.wait(), 1)
                assert any(e.get('state') == 'summarizing' for e in events)
                await voice.interrupt()
                release.set()
                await asyncio.sleep(.01)
                assert voice._llm.calls == 0
                assert not avatar.messages
                assert not any(e['type'] in ('assistant_response', 'assistant_response_delta') for e in events)
        finally:
            await voice.close()
    asyncio.run(run())
