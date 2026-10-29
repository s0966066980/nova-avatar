# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Attachment isolation, atomic validation and request-only vision context."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image
import pypdfium2 as pdfium

from src.config.schema import Config
from src.llm.context_usage import measure_request
from src.llm.engines.openai import OpenAILLM
from src.server.attachments import AttachmentError, AttachmentStore, page_numbers


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (64, 32), 'white').save(output, 'PNG')
    return output.getvalue()


@pytest.fixture
def store():
    value = AttachmentStore()
    yield value
    value.close()


def test_batch_is_atomic_and_identifiers_are_session_owned(store):
    with pytest.raises(AttachmentError):
        store.add_batch([('ok.png', image_bytes()), ('bad.pdf', b'not a pdf')], store.generation)
    assert store.snapshot()['files'] == []
    item = store.add_batch([('../../sample.png', image_bytes())], store.generation)[0]
    assert item['name'] == 'sample.png'
    with AttachmentStoreContext() as other:
        with pytest.raises(AttachmentError, match='missing_attachment'):
            other.validate_selection([{'id': item['id']}])


class AttachmentStoreContext:
    def __enter__(self):
        self.store = AttachmentStore()
        return self.store

    def __exit__(self, *_):
        self.store.close()


def test_reset_invalidates_pending_upload_and_deletes_raw_files(store):
    generation = store.generation
    item = store.add_batch([('one.png', image_bytes())], generation)[0]
    path = store._files[item['id']].path
    store.clear()
    assert not path.exists()
    with pytest.raises(AttachmentError, match='session_reset'):
        store.add_batch([('late.png', image_bytes())], generation)


def test_disabling_input_only_removes_unsent_files(store):
    first, second = store.add_batch([('sent.png', image_bytes()), ('draft.png', image_bytes())], store.generation)
    store.select([{'id': first['id']}], submitted=True)
    store.clear(drafts_only=True)
    assert [item['id'] for item in store.snapshot()['files']] == [first['id']]
    assert store.selection == [{'id': first['id']}]
    store.select([])
    assert store.validate_selection([]) == []


def test_selection_and_session_quotas(store):
    with patch('src.server.attachments.MAX_FILES', 1):
        store.add_batch([('one.png', image_bytes())], store.generation)
        with pytest.raises(AttachmentError, match='session_quota'):
            store.add_batch([('two.png', image_bytes())], store.generation)
    with pytest.raises(AttachmentError, match='reference_limit'):
        store.validate_selection([{'id': 'missing'}] * 5)


def test_page_ranges_have_bounds_and_no_silent_truncation():
    assert page_numbers('1-3,5,2', 10) == [1, 2, 3, 5]
    with pytest.raises(AttachmentError, match='page_limit'):
        page_numbers('', 41)
    for invalid in ['0', '3-1', '1-11', '1-a', '1,']:
        with pytest.raises(AttachmentError):
            page_numbers(invalid, 10)


def test_real_pdf_pages_are_validated_rendered_and_released(store):
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        for _ in range(3):
            document.new_page(300, 400).close()
        document.save(output)
    item = store.add_batch([('pages.pdf', output.getvalue())], store.generation)[0]
    assert item['pages'] == 3
    units = list(store._units(store.validate_selection([{'id': item['id'], 'pages': '2-3'}])))
    assert [unit[0] for unit in units] == ['pages.pdf — page 2', 'pages.pdf — page 3']
    for _, text, image in units:
        assert text == ''
        assert max(image.size) <= 1024
        image.close()


def test_pdf_with_empty_open_password_but_encryption_is_rejected(store):
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        document.new_page(100, 100).close()
        document.save(output)
    with patch('src.server.attachments.pdfium.raw.FPDF_GetSecurityHandlerRevision', return_value=4):
        with pytest.raises(AttachmentError, match='encrypted_pdf'):
            store.add_batch([('encrypted.pdf', output.getvalue())], store.generation)
    assert store.snapshot()['files'] == []


def test_current_request_has_image_but_retained_history_does_not(store):
    config = Config()
    config.llm.assistant_profile.output_locale = 'en-US'
    item = store.add_batch([('test.png', image_bytes())], store.generation)[0]
    resolved = store.select([{'id': item['id']}], submitted=True)
    progress = Mock()
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='''{"relevant":true,"observations":"A number"}'''))])]))
    with patch('openai.OpenAI') as reader:
        reader.return_value.chat.completions.create.return_value = stream
        question = store.prepare_question('Read this number', resolved, config, progress, lambda: True)
    assert question.parts[1]['type'] == 'image_url'
    engine = OpenAILLM(config=config, api_key='local')
    engine.observe_context = False
    engine._client = Mock()
    engine._client.chat.completions.create.return_value = []
    transaction = engine.begin_history_turn(question, turn_id='image')
    list(engine.chat_stream(question, 'Role and restrictions', history_transaction=transaction))
    content = engine._client.chat.completions.create.call_args.kwargs['messages'][-1]['content']
    assert any(part['type'] == 'image_url' for part in content)
    assert content[-1]['text'].endswith('[Session language: English. Answer in English.]')
    engine.commit_history_turn(transaction, assistant_text='A number', terminal_reason='completed')
    history = engine.conversation_history
    assert 'test.png' in history[0]['content']
    assert type(history[0]['content']) is str
    assert 'base64' not in str(history)


def test_image_context_is_not_falsely_measured_by_text_tokenizer():
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'hello'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + 'X' * 200000}}]}]
    with patch('src.llm.context_usage.requests.post') as post:
        result = measure_request(messages, 500, capacity=8192, model='local')
    post.assert_not_called()
    assert result['estimated'] is True
    assert result['source'] == 'text estimate; visual tokens pending provider usage'
    assert result['visual_tokens_unknown'] is True
    assert result['input_tokens'] < 100


def test_cancelled_analysis_does_not_submit_to_model(store):
    item = store.add_batch([('test.png', image_bytes())], store.generation)[0]
    with pytest.raises(AttachmentError, match='cancelled'):
        store.prepare_question('read', store.validate_selection([{'id': item['id']}]), Config(), Mock(), lambda: False)


def test_field_question_preserves_exact_source_and_excludes_unrelated_codes(store):
    import json
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        for _ in range(3):
            document.new_page(300, 400).close()
        document.save(output)
    item = store.add_batch([('records.pdf', output.getvalue())], store.generation)[0]

    class Stream(list):
        def close(self):
            pass

    def observation(text):
        # Simulate the small model incorrectly considering every page relevant.
        payload = json.dumps({'relevant': True, 'requested_field': None,
                              'field_quote': None, 'observations': text})
        return Stream([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=payload))])])

    classified = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({'field_aliases': ['Order number', '訂單編號']})))])
    units = [(f'records.pdf — page {index + 1}', text, Image.new('RGB', (30, 40))) for index, text in enumerate(
        ['Document code: 572904', '訂單編號：836197', 'Beta: 27 units'])]
    with patch.object(store, '_units', return_value=iter(units)), patch('openai.OpenAI') as factory:
        factory.return_value.chat.completions.create.side_effect = [classified,
            observation('Document code: 572904'), observation('Order number: 836197'), observation('Beta: 27')]
        question = store.prepare_question('What is the order number?', store.validate_selection([{'id': item['id']}]),
                                          Config(), Mock(), lambda: True)
    content = question.parts[0]['text']
    assert '訂單編號：836197' in content
    assert '572904' not in content
    assert 'Beta: 27' not in content


def test_cancel_before_acceptance_rejects_late_request_without_interrupting_old_turn():
    import asyncio
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar, FakeASR, FakeSegmenter

    async def exercise():
        session = VoiceTurnSession(7, Config(), FakeAvatar())
        session._segmenter, session._asr = FakeSegmenter(), FakeASR()
        session.attach_event_sink(lambda raw: None)
        try:
            with patch('src.server.voice_session.llm_response', return_value='An existing answer'):
                await session.start_text_turn('old question', request_id='old')
                await session._turn_task
            old_turn = session._turn_id
            await session.cancel_text_request('cancelled-upload')
            assert session._turn_id == old_turn
            with pytest.raises(ValueError, match='cancelled'):
                await session.start_text_turn('late question', request_id='cancelled-upload')
            assert session._turn_id == old_turn
        finally:
            await session.close()

    asyncio.run(exercise())


def test_cancelled_attachment_validation_cannot_interrupt_a_new_text_turn():
    import asyncio
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar, FakeASR, FakeSegmenter

    async def exercise():
        session = VoiceTurnSession(7, Config(), FakeAvatar())
        session._segmenter, session._asr = FakeSegmenter(), FakeASR()
        session.attach_event_sink(lambda raw: None)
        item = session.attachments.add_batch([('one.png', image_bytes())], session.attachments.generation)[0]
        validating, resume = asyncio.Event(), asyncio.Event()

        async def validate(*_args):
            validating.set()
            await resume.wait()
            return True

        try:
            with patch('src.server.voice_session.asyncio.to_thread', side_effect=validate):
                old = asyncio.create_task(session.start_text_turn('Old document question',
                    attachments=[{'id': item['id']}], request_id='old'))
                await validating.wait()
                await session.cancel_text_request('old')
                with patch('src.server.voice_session.llm_response', return_value='New answer'):
                    current = await session.start_text_turn('New question', attachments=[], request_id='new')
                    await session._turn_task
                resume.set()
                with pytest.raises(ValueError, match='cancelled'):
                    await old
            assert session._turn_id == current['turn_id'], 'late old validation must not cancel the new answer'
        finally:
            resume.set()
            await session.close()

    asyncio.run(exercise())


def test_pending_text_cancellation_and_replacement_do_not_overlap_interrupts():
    import asyncio
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar, FakeASR, FakeSegmenter

    async def exercise():
        session = VoiceTurnSession(7, Config(), FakeAvatar())
        session._segmenter, session._asr = FakeSegmenter(), FakeASR()
        session.attach_event_sink(lambda raw: None)
        interrupting, release = asyncio.Event(), asyncio.Event()
        real_interrupt = session._interrupt_locked
        overlapping = []

        async def delayed_interrupt():
            overlapping.append(interrupting.is_set())
            interrupting.set()
            await release.wait()
            await real_interrupt()

        try:
            with patch('src.server.voice_session.llm_response', return_value='Answer'):
                await session.start_text_turn('Old question', request_id='old')
                await session._turn_task
                with patch.object(session, '_interrupt_locked', side_effect=delayed_interrupt):
                    cancellation = asyncio.create_task(session.cancel_text_request('old'))
                    await interrupting.wait()
                    replacement = asyncio.create_task(session.start_text_turn('New question', request_id='new'))
                    await asyncio.sleep(0)
                    release.set()
                    _, current = await asyncio.gather(cancellation, replacement)
                await session._turn_task
            assert overlapping == [False], 'replacement must wait for the existing cancellation to finish'
            assert session._turn_id == current['turn_id']
        finally:
            release.set()
            await session.close()

    asyncio.run(exercise())
