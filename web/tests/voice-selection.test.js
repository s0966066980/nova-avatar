// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, h, reactive, ref } from 'vue'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'
import {
  DEVELOPMENT_VOICE_NOTICE, referenceVoices, switchTtsEngine, ttsVoiceProblem, voiceLabel, voiceModelLabel
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

test('切到 Matcha 不帶入其他引擎的聲音，切回 Edge 也不留下聲線模型', () => {
  const tts = { type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' }
  switchTtsEngine(tts, 'matcha')
  assert.deepEqual(tts, { type: 'matcha', ref_file: '', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' })
  Object.assign(tts, { type: 'breezyvoice', ref_file: ownVoice.id, ref_text: '舊逐字稿', tts_server: 'http://127.0.0.1:50001', model: 'BreezyVoice' })
  switchTtsEngine(tts, 'matcha')
  assert.deepEqual(tts, { type: 'matcha', ref_file: '', ref_text: null, voice_en_us: 'en-US-JennyNeural', tts_server: '', model: '' })
  tts.ref_file = 'zh-tw-hsiaochen-edge'
  switchTtsEngine(tts, 'breezyvoice')
  assert.equal(tts.ref_file, '', '聲線模型 ID 不是音訊庫 ID')
  tts.ref_file = 'zh-tw-hsiaochen-edge'
  tts.type = 'matcha'
  switchTtsEngine(tts, 'edgetts')
  assert.equal(tts.ref_file, 'zh-TW-HsiaoChenNeural')
})

test('BreezyVoice 只列有逐字稿的參考音檔，未選或選了不可用的音檔不能儲存', () => {
  const voices = [devVoice, ownVoice, silentVoice]
  assert.deepEqual(referenceVoices(voices), [devVoice, ownVoice])
  assert.match(ttsVoiceProblem({ type: 'breezyvoice', ref_file: '' }, voices), /請選擇有逐字稿的參考音檔/)
  assert.match(ttsVoiceProblem({ type: 'breezyvoice', ref_file: 'zh-TW-HsiaoChenNeural' }, voices), /不在音訊庫/)
  assert.match(ttsVoiceProblem({ type: 'breezyvoice', ref_file: silentVoice.id }, voices), /沒有逐字稿/)
  assert.equal(ttsVoiceProblem({ type: 'breezyvoice', ref_file: ownVoice.id }, voices), '')
  assert.equal(ttsVoiceProblem({ type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural' }, []), '')
})

const hsiaochen = { id: 'zh-tw-hsiaochen-edge', name: '曉臻（Edge 蒸餾）', usage: 'Development only', languages: ['zh-TW', 'en-US'], source: 'distilled' }

test('Matcha 未選或選了未列出的聲線模型不能儲存', () => {
  const models = [hsiaochen]
  assert.match(ttsVoiceProblem({ type: 'matcha', ref_file: '' }, [], models), /請選擇聲線模型/)
  assert.match(ttsVoiceProblem({ type: 'matcha', ref_file: 'zh-TW-HsiaoChenNeural' }, [], models), /不在已安裝的聲線模型中/)
  assert.match(ttsVoiceProblem({ type: 'matcha', ref_file: 'matcha-icefall-zh-en' }, [], models), /models\/tts/)
  assert.equal(ttsVoiceProblem({ type: 'matcha', ref_file: hsiaochen.id }, [], models), '')
  assert.match(ttsVoiceProblem({ type: 'matcha', ref_file: hsiaochen.id }, []), /不在已安裝的聲線模型中/, '沒有清單時不當作可儲存')
})

test('聲線模型名稱後面標示使用限制', () => {
  assert.equal(voiceModelLabel(hsiaochen), '曉臻（Edge 蒸餾） · Development only')
  assert.equal(voiceModelLabel({ id: 'mine', name: '自訓', usage: 'Research / Non-commercial' }), '自訓 · Research / Non-commercial')
})

test('開發用音檔標示未取得說話者授權', () => {
  assert.equal(DEVELOPMENT_VOICE_NOTICE, '開發用，未取得說話者授權')
  assert.match(voiceLabel(devVoice), /開發用，未取得說話者授權/)
  assert.doesNotMatch(voiceLabel(ownVoice), /開發用/)
})

function runtimeStub(voices, voiceModels = []) {
  const calls = []
  const speech = reactive({ tts: { engines: ['edgetts', 'breezyvoice', 'matcha'].map(id => ({ id, label: id })), voices, edge_voices: [], voice_models: voiceModels } })
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
  stub.speech.tts.edge_voices = [
    { id: 'zh-TW-HsiaoChenNeural', name: 'HsiaoChen' },
    { id: 'zh-TW-YunJheNeural', name: 'YunJhe' }
  ]
  const Editor = await loadEditor(stub)
  const profile = editorProfile({ type: 'edgetts', ref_file: 'zh-CN-XiaoxiaoNeural' })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const label = all(view.root, n => n.type === 'label' && textContent(n).startsWith('聲線（台灣華語）'))[0]
  const select = all(label, n => n.type === 'select')[0]
  assert.deepEqual(all(select, n => n.type === 'option').map(n => n.props.value),
    ['', 'zh-TW-HsiaoChenNeural', 'zh-TW-YunJheNeural', 'zh-CN-XiaoxiaoNeural'])
  assert.equal(profile.tts.ref_file, 'zh-CN-XiaoxiaoNeural')
  select.props.onChange({ target: { value: 'zh-TW-YunJheNeural' } })
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

const researchModel = { id: 'my-voice', name: '自訓聲線', usage: 'Research / Non-commercial', languages: ['zh-TW', 'en-US'], source: 'fine-tuned' }

test('設定檔編輯器：英文聲音從 Edge 清單選擇，保留既有的清單外聲線', async t => {
  const { stub } = runtimeStub([])
  stub.speech.tts.edge_english_voices = [
    { id: 'en-US-JennyNeural', label: 'Jenny（美式女聲）' },
    { id: 'en-US-AriaNeural', label: 'Aria（美式女聲）' },
    { id: 'en-US-GuyNeural', label: 'Guy（美式男聲）' }
  ]
  const Editor = await loadEditor(stub)
  const profile = editorProfile({
    type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural', voice_en_us: 'en-GB-SoniaNeural'
  })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const label = all(view.root, node => node.type === 'label' && textContent(node).startsWith('英文聲音'))[0]
  const select = all(label, node => node.type === 'select')[0]
  const options = () => all(select, node => node.type === 'option').map(node => node.props.value)
  assert.deepEqual(options(), ['', 'en-US-JennyNeural', 'en-US-AriaNeural', 'en-US-GuyNeural', 'en-GB-SoniaNeural'])
  assert.equal(profile.tts.voice_en_us, 'en-GB-SoniaNeural')

  select.props['onUpdate:modelValue']('en-US-AriaNeural')
  await settle()
  assert.equal(profile.tts.voice_en_us, 'en-US-AriaNeural')
  assert.equal(profile.tts.ref_file, 'zh-TW-HsiaoChenNeural')
  assert.deepEqual(options(), ['', 'en-US-JennyNeural', 'en-US-AriaNeural', 'en-US-GuyNeural'])
})

test('設定檔編輯器：切到 Matcha 不帶入 Edge 聲線，只列出已安裝的聲線模型並標示使用限制與實測品質', async t => {
  const { calls, stub } = runtimeStub([devVoice, ownVoice], [hsiaochen, researchModel])
  stub.previewProfileVoice = async tts => { calls.push(['preview', { ...tts }]); return 'data:audio/wav;base64,AAAA' }
  const Editor = await loadEditor(stub)
  const profile = editorProfile({ type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural' })
  const view = mount(Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const labelled = text => all(view.root, n => n.type === 'label' && textContent(n).startsWith(text))[0]
  const engineOptions = all(labelled('語音引擎'), n => n.type === 'option').map(n => n.props.value)
  assert.deepEqual(engineOptions, ['edgetts', 'breezyvoice', 'matcha'])
  all(labelled('語音引擎'), n => n.type === 'select')[0].props.onChange({ target: { value: 'matcha' } })
  await settle()
  assert.equal(profile.tts.type, 'matcha')
  assert.equal(profile.tts.ref_file, '', 'Edge 聲線不可殘留，也不自動選聲線模型')
  const modelSelect = all(labelled('聲線模型'), n => n.type === 'select')[0]
  const options = modelSelect.children.filter(n => n.type === 'option')
  assert.deepEqual(options.map(n => n.props.value), ['', hsiaochen.id, researchModel.id])
  assert.deepEqual(options.slice(1).map(textContent), ['曉臻（Edge 蒸餾） · Development only', '自訓聲線 · Research / Non-commercial'])
  const alerts = () => all(view.root, n => n.props.role === 'alert').map(textContent).join('\n')
  assert.match(alerts(), /請選擇聲線模型/)
  const text = textContent(view.root)
  assert.match(text, /CPU/)
  assert.doesNotMatch(text, /英文聲音/, '同一個聲線模型負責英文')
  assert.ok(!labelled('參考音檔'), 'Matcha 不需要參考音檔')
  assert.ok(!button(view.root, '上傳到音訊庫'))
  assert.equal(button(view.root, '試聽此設定檔的聲音').props.disabled, true)

  profile.tts.ref_file = hsiaochen.id
  await settle()
  assert.equal(alerts(), '')
  assert.match(textContent(view.root), /CER 13\.2%/)
  assert.match(textContent(view.root), /WER 5\.6%/)
  button(view.root, '試聽此設定檔的聲音').props.onClick()
  await settle()
  assert.equal(calls.find(c => c[0] === 'preview')[1].ref_file, hsiaochen.id)

  profile.tts.ref_file = researchModel.id
  await settle()
  assert.doesNotMatch(textContent(view.root), /CER 13\.2%/, '實測數字只屬於 hsiaochen-edge')
})

test('設定檔編輯器：已儲存但未安裝的聲線模型仍顯示為目前選擇，並阻擋儲存', async t => {
  const { stub } = runtimeStub([devVoice], [hsiaochen])
  const Editor = await loadEditor(stub)
  const view = mount(Editor, { modelValue: editorProfile({ type: 'matcha', ref_file: 'removed-voice' }), initialSection: 'voice' })
  t.after(() => view.unmount())
  await settle()
  const modelSelect = all(view.root, n => n.type === 'label' && textContent(n).startsWith('聲線模型'))
    .flatMap(label => all(label, n => n.type === 'select'))[0]
  const missing = modelSelect.children.filter(n => n.type === 'option').find(n => n.props.value === 'removed-voice')
  assert.ok(missing, '選擇不會消失')
  assert.equal(textContent(missing), 'removed-voice（未安裝的聲線模型）')
  assert.ok('disabled' in missing.props && missing.props.disabled !== false, '不能再選回未安裝的聲線模型')
  assert.match(all(view.root, n => n.props.role === 'alert').map(textContent).join('\n'), /不在已安裝的聲線模型中/)
})
