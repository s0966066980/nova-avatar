// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, h, reactive, ref } from 'vue'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'
import {
  DEVELOPMENT_VOICE_NOTICE, referenceAudioProblem, referenceVoices, switchTtsEngine, voiceLabel
} from '../src/voiceSelection.js'

const devVoice = { id: 'aaaaaaaaaaaaaaaa', name: 'BreezyVoice 測試音檔（僅開發用）', seconds: 5.2, transcript: '在密碼學中。', development: true }
const ownVoice = { id: 'bbbbbbbbbbbbbbbb', name: '自錄', seconds: 3, transcript: '您好。', development: false }
const silentVoice = { id: 'cccccccccccccccc', name: '沒有逐字稿', seconds: 4, transcript: '', development: false }

test('從 Edge 切到 BreezyVoice 清掉 Edge 聲線且不自動帶入音檔，切回 Edge 清掉音訊庫選擇', () => {
  const tts = { type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' }
  switchTtsEngine(tts, 'breezyvoice')
  assert.equal(tts.type, 'breezyvoice')
  assert.equal(tts.ref_file, '')
  Object.assign(tts, { ref_file: ownVoice.id, ref_text: '舊逐字稿', tts_server: 'http://127.0.0.1:50001', model: 'BreezyVoice' })
  switchTtsEngine(tts, 'edgetts')
  assert.deepEqual(tts, { type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' })
  switchTtsEngine(tts, 'edgetts')
  assert.equal(tts.ref_file, 'zh-TW-HsiaoChenNeural')
})

test('BreezyVoice 只列有逐字稿的參考音檔，未選或選了不可用的音檔不能儲存', () => {
  const voices = [devVoice, ownVoice, silentVoice]
  assert.deepEqual(referenceVoices(voices), [devVoice, ownVoice])
  assert.match(referenceAudioProblem({ type: 'breezyvoice', ref_file: '' }, voices), /請選擇有逐字稿的參考音檔/)
  assert.match(referenceAudioProblem({ type: 'breezyvoice', ref_file: 'zh-TW-HsiaoChenNeural' }, voices), /不在音訊庫/)
  assert.match(referenceAudioProblem({ type: 'breezyvoice', ref_file: silentVoice.id }, voices), /沒有逐字稿/)
  assert.equal(referenceAudioProblem({ type: 'breezyvoice', ref_file: ownVoice.id }, voices), '')
  assert.equal(referenceAudioProblem({ type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural' }, []), '')
})

test('開發用音檔標示未取得說話者授權', () => {
  assert.equal(DEVELOPMENT_VOICE_NOTICE, '開發用，未取得說話者授權')
  assert.match(voiceLabel(devVoice), /開發用，未取得說話者授權/)
  assert.doesNotMatch(voiceLabel(ownVoice), /開發用/)
})

function runtimeStub(voices) {
  const calls = []
  const speech = reactive({ tts: { engines: [], voices, edge_voices: [] } })
  const stub = {
    speech,
    ttsVoiceOptions: computed(() => speech.tts.voices),
    voiceLibraryBusy: ref(false),
    async refreshTtsVoices() { calls.push(['refresh']); return speech.tts.voices },
    async uploadTtsVoice(file, name, transcript) {
      calls.push(['upload', file.name, name, transcript])
      const voice = { id: 'dddddddddddddddd', name: name || file.name, seconds: 2, transcript, development: false }
      speech.tts.voices = [...speech.tts.voices, voice]
      return voice
    },
    async deleteTtsVoice(id) { calls.push(['delete', id]); speech.tts.voices = speech.tts.voices.filter(v => v.id !== id) }
  }
  return { calls, stub }
}

async function loadManager(stub) {
  return loadComponent(new URL('../src/components/VoiceLibraryManager.vue', import.meta.url), {
    '../composables/useRuntimeSettings.js': { useRuntimeSettings: () => stub }
  })
}

test('音訊庫管理：上傳必須附逐字稿、可試聽、刪除需再次確認、標示開發用', async t => {
  const { calls, stub } = runtimeStub([devVoice, silentVoice])
  const Manager = await loadManager(stub)
  const uploaded = [], deleted = []
  const view = mount(Manager, { selected: '', onUploaded: voice => uploaded.push(voice), onDeleted: id => deleted.push(id) })
  t.after(() => view.unmount())
  await settle()
  assert.deepEqual(calls[0], ['refresh'])
  const text = textContent(view.root)
  assert.match(text, /開發用，未取得說話者授權/)
  assert.match(text, /沒有逐字稿/)

  button(view.root, '試聽').props.onClick()
  await settle()
  const audio = all(view.root, n => n.type === 'audio')
  assert.equal(audio.length, 1)
  assert.equal(audio[0].props.src, `/api/speech/voices/${devVoice.id}/audio`)

  const upload = button(view.root, '上傳到音訊庫')
  assert.equal(upload.props.disabled, true)
  all(view.root, n => n.type === 'input' && n.props.type === 'file')[0].props.onChange({ target: { files: [{ name: 'mine.wav' }], value: 'mine.wav' } })
  await settle()
  assert.equal(button(view.root, '上傳到音訊庫').props.disabled, true, '沒有逐字稿不能上傳')
  all(view.root, n => n.type === 'textarea')[0].props['onUpdate:modelValue']('您好，歡迎光臨。')
  await settle()
  button(view.root, '上傳到音訊庫').props.onClick()
  await settle()
  assert.deepEqual(calls.at(-1), ['upload', 'mine.wav', '', '您好，歡迎光臨。'])
  assert.equal(uploaded[0].id, 'dddddddddddddddd')

  button(view.root, '刪除').props.onClick()
  await settle()
  assert.equal(calls.filter(c => c[0] === 'delete').length, 0, '第一次只要求確認')
  button(view.root, '確認刪除').props.onClick()
  await settle()
  assert.deepEqual(calls.at(-1), ['delete', devVoice.id])
  assert.deepEqual(deleted, [devVoice.id])
})

test('音訊庫沒有可用音檔時提示先上傳', async t => {
  const { stub } = runtimeStub([silentVoice])
  const Manager = await loadManager(stub)
  const view = mount(Manager, { selected: '' })
  t.after(() => view.unmount())
  await settle()
  assert.match(textContent(view.root), /還沒有附逐字稿的參考音檔/)
})

test('設定檔編輯器：BreezyVoice 選單只列有逐字稿的音檔，切換引擎清掉另一種聲線並提供音訊庫', async t => {
  const { stub } = runtimeStub([devVoice, ownVoice, silentVoice])
  const Manager = await loadManager(stub)
  const Editor = await loadComponent(new URL('../src/components/AvatarProfileEditor.vue', import.meta.url), {
    '../composables/useRuntimeSettings': { useRuntimeSettings: () => stub },
    './RagFlowSettings.vue': { default: { setup: () => () => h('div') } },
    './VoiceLibraryManager.vue': { default: Manager }
  })
  const profile = reactive({ id: 'main', name: '接待員', engine: 'musetalk', avatar_id: 'a',
    assistant_profile: { assistant_name: '', system_prompt: '', restriction_prompt: '', forbidden_self_names: [], output_locale: 'zh-TW', enforce_output_locale: true }, llm: { endpoint: '', model: '' },
    reply_rules: {}, rag: {}, tools: { weather: false },
    tts: { type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' } })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const engine = () => all(view.root, n => n.type === 'label' && textContent(n).startsWith('語音引擎'))[0]
  all(engine(), n => n.type === 'select')[0].props.onChange({ target: { value: 'breezyvoice' } })
  await settle()
  assert.equal(profile.tts.type, 'breezyvoice')
  assert.equal(profile.tts.ref_file, '', 'Edge 聲線不可殘留，也不自動帶入音檔')
  const voiceSelect = all(all(view.root, n => n.type === 'label' && textContent(n).startsWith('參考音檔'))[0], n => n.type === 'select')[0]
  const values = voiceSelect.children.filter(n => n.type === 'option').map(n => n.props.value)
  assert.deepEqual(values, ['', devVoice.id, ownVoice.id])
  assert.match(textContent(voiceSelect), /開發用，未取得說話者授權/)
  assert.match(textContent(view.root), /請選擇有逐字稿的參考音檔/)
  assert.ok(button(view.root, '上傳到音訊庫'), '編輯器內可直接上傳參考音檔')
})

async function loadEditor(stub) {
  const Manager = await loadManager(stub)
  return loadComponent(new URL('../src/components/AvatarProfileEditor.vue', import.meta.url), {
    '../composables/useRuntimeSettings': { useRuntimeSettings: () => stub },
    './RagFlowSettings.vue': { default: { setup: () => () => h('div') } },
    './VoiceLibraryManager.vue': { default: Manager }
  })
}

function editorProfile(tts) {
  return reactive({ id: 'main', name: '接待員', engine: 'musetalk', avatar_id: 'a',
    assistant_profile: { assistant_name: '', system_prompt: '', restriction_prompt: '', forbidden_self_names: [], output_locale: 'zh-TW', enforce_output_locale: true }, llm: { endpoint: '', model: '' },
    reply_rules: {}, rag: {}, tools: { weather: false },
    tts: { ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '', ...tts } })
}

function previewStub(voices, { ready = true } = {}) {
  const { calls, stub } = runtimeStub(voices)
  const pending = []
  stub.breezyVoiceServerReady = async tts => { calls.push(['status', { ...tts }]); return ready }
  stub.previewProfileVoice = tts => {
    calls.push(['preview', { ...tts }])
    return new Promise((resolve, reject) => pending.push({ resolve, reject }))
  }
  return { calls, stub, pending }
}

test('設定檔編輯器試聽：以目前未儲存的 BreezyVoice 設定合成，伺服器未就緒時顯示啟動中', async t => {
  const { calls, stub, pending } = previewStub([devVoice, ownVoice], { ready: false })
  const Editor = await loadEditor(stub)
  const profile = editorProfile({ type: 'breezyvoice', ref_file: '' })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const preview = () => button(view.root, '試聽此設定檔的聲音')
  assert.equal(preview().props.disabled, true, '未選參考音檔不能試聽')
  profile.tts.ref_file = ownVoice.id
  profile.tts.model = 'BreezyVoice'
  await settle()
  assert.equal(preview().props.disabled, false)
  preview().props.onClick()
  await settle()
  assert.deepEqual(calls.find(c => c[0] === 'status')[1], { ...profile.tts })
  assert.match(textContent(view.root), /BreezyVoice 伺服器啟動中/)
  assert.equal(preview().props.disabled, true, '試聽進行中不可重複送出')
  const sent = calls.find(c => c[0] === 'preview')[1]
  assert.equal(sent.type, 'breezyvoice')
  assert.equal(sent.ref_file, ownVoice.id)
  assert.equal(sent.model, 'BreezyVoice')
  pending[0].resolve('data:audio/wav;base64,AAAA')
  await settle()
  const audio = all(view.root, n => n.type === 'audio')
  assert.equal(audio.length, 1)
  assert.equal(audio[0].props.src, 'data:audio/wav;base64,AAAA')
  assert.ok(audio[0].props.autoplay !== undefined && audio[0].props.autoplay !== false, '合成完成後自動播放')
  assert.doesNotMatch(textContent(view.root), /啟動中/)

  // A different voice makes the old sample stale.
  profile.tts.ref_file = devVoice.id
  await settle()
  assert.equal(all(view.root, n => n.type === 'audio').length, 0)
})

test('設定檔編輯器試聽：Edge 聲線不查 BreezyVoice，失敗時顯示伺服器原因', async t => {
  const { calls, stub, pending } = previewStub([])
  const Editor = await loadEditor(stub)
  const profile = editorProfile({ type: 'edgetts', ref_file: 'zh-TW-YunJheNeural' })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  button(view.root, '試聽此設定檔的聲音').props.onClick()
  await settle()
  assert.equal(calls.some(c => c[0] === 'status'), false)
  assert.match(textContent(view.root), /合成試聽句中/)
  assert.equal(calls.find(c => c[0] === 'preview')[1].ref_file, 'zh-TW-YunJheNeural')
  pending[0].reject(new Error('TTS 連線或試聽失敗: offline'))
  await settle()
  const alert = all(view.root, n => n.props.role === 'alert' && textContent(n).includes('offline'))
  assert.equal(alert.length, 1)
  assert.equal(button(view.root, '試聽此設定檔的聲音').props.disabled, false)
})
