// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { File } from 'node:buffer'
import { webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setImmediate } from 'node:timers/promises'
import test from 'node:test'
import vm from 'node:vm'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import * as attachments from '../src/conversationAttachments.js'

test('console editing preserves enabled capture while the avatar is answering', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const handler = source.match(/const onComposerEditing = \(editing\) => \{[\s\S]*?\n\}/)[0]
  let requested = true
  const calls = []
  const edit = vm.runInNewContext(`let composerCaptureBefore = null; ${handler}; onComposerEditing`, {
    isConnected: { value: true }, isRecordingVoice: { value: false },
    getCaptureRequested: () => requested,
    setCaptureEnabled: value => { requested = value; calls.push(value) }
  })
  edit(true); edit(false)
  assert.deepEqual(calls, [false, true])
})

const source = readFileSync(new URL('../src/components/ConversationComposer.vue', import.meta.url), 'utf8')
const setup = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
const stageSource = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
const snapshot = (files = [], selection = []) => ({ files, selection, bytes: 100, vision_ready: true })
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function settle() { await nextTick(); await setImmediate(); await nextTick() }

// Execute the component's actual setup with Vue reactivity. Only HTTP, browser
// facilities and lifecycle registration are replaced; no server or DOM is used.
function composer(t, handler = async () => snapshot(), values = {}) {
  const props = reactive({ sessionId: 1, connected: true, enabled: true, stage: false,
    locale: 'en-US', settings: { ...attachments.composerDefaults }, modelValue: '', ...values })
  const calls = [], events = [], timers = new Map(), cleanup = []
  let clock = 0, timerId = 0
  const scope = effectScope()
  const window = { matchMedia: () => ({ matches: true }), visualViewport: null }
  const context = {
    ...attachments, computed, nextTick, ref, watch,
    defineProps: () => props,
    defineEmits: () => (name, value) => events.push({ name, value }),
    defineExpose() {}, onMounted() {}, onBeforeUnmount: fn => cleanup.push(fn),
    crypto: webcrypto, FormData, AbortController, window,
    document: { activeElement: null },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, at: clock + delay }); return id },
    clearTimeout: id => timers.delete(id), clearInterval() {},
    async attachmentRequest(url, options = {}) {
      const call = { url, options, body: typeof options.body === 'string' ? JSON.parse(options.body) : undefined }
      calls.push(call)
      if (url.endsWith('/interaction')) return {}
      return handler(call)
    }
  }
  const run = vm.runInNewContext(`(function () { ${setup}; return {
    text, root, draft, selected, files, ready, active, sending, status, error,
    placement, add, send, cancel, receive, refresh, toggle, pages, layout, keydown
  } })`, context)
  const state = scope.run(run)
  state.ready.value = true
  t.after(() => { cleanup.forEach(fn => fn()); scope.stop() })
  return { ...state, props, calls, events, timers, window,
    async advance(ms) {
      clock += ms
      for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.fn() }
      await settle()
    }
  }
}

test('failed acceptance preserves local files and retries without uploading twice', async t => {
  let uploads = 0, attempts = 0
  const h = composer(t, async call => {
    if (call.url.endsWith('/attachments') && call.options.method === 'POST') {
      uploads++
      return [{ id: 'pdf-1', name: 'long.pdf', kind: 'pdf', pages: 41 }]
    }
    if (call.url === '/human') {
      if (++attempts === 1) throw new Error('page_limit')
      return { turn_id: 'accepted' }
    }
    return snapshot()
  })
  const file = new File(['pdf'], 'long.pdf', { type: 'application/pdf' })
  h.text.value = 'Summarize these pages'
  h.add([file])
  await h.send(); await settle()
  assert.equal(h.draft.value[0].file, file)
  assert.deepEqual(plain(h.selected.value), [{ id: 'pdf-1', pages: '' }])
  assert.equal(h.text.value, 'Summarize these pages')
  assert.match(h.error.value, /40 pages/)
  await h.pages('pdf-1', '1-2')
  await h.send(); await settle()
  assert.equal(uploads, 1)
  assert.deepEqual(h.calls.filter(call => call.url === '/human').at(-1).body.attachments, [{ id: 'pdf-1', pages: '1-2' }])
  assert.equal(h.draft.value.length, 0)
  assert.equal(h.text.value, '')
})

test('new sessions reupload retained local drafts instead of reusing old attachment IDs', async t => {
  let uploads = 0
  const h = composer(t, async call => {
    if (call.url.endsWith('/attachments') && call.options.method === 'POST') return [{ id: `pdf-${++uploads}`, name: 'one.pdf', kind: 'pdf', pages: 1 }]
    if (call.url === '/human') {
      if (call.body.sessionid === 1) throw new Error('analysis_capacity')
      return { turn_id: 'new-session-turn' }
    }
    return snapshot()
  })
  const file = new File(['pdf'], 'one.pdf', { type: 'application/pdf' })
  h.text.value = 'Question'
  h.add([file]); await h.send(); await settle()
  h.props.sessionId = 2; await settle()
  assert.equal(h.draft.value[0].file, file)
  assert.equal(h.draft.value[0].uploadedId, undefined)
  assert.equal(h.selected.value.length, 0)
  await h.send(); await settle()
  assert.equal(uploads, 2)
  assert.deepEqual(h.calls.filter(call => call.url === '/human').at(-1).body.attachments, [{ id: 'pdf-2', pages: '' }])
})

for (const newSession of [true, false]) {
  test(`late cancellation cannot overwrite a new accepted turn (${newSession ? 'new session' : 'same session'})`, async t => {
    const interruption = deferred()
    let turn = 0
    const h = composer(t, async call => {
      if (call.url === '/interrupt_talk') return interruption.promise
      if (call.url === '/human') return { turn_id: `turn-${++turn}` }
      return snapshot()
    })
    h.text.value = 'Old question'; await h.send(); await settle()
    const cancellation = h.cancel()
    if (newSession) { h.props.sessionId = 2; await settle() }
    h.text.value = 'New accepted question'; await h.send(); await settle()
    interruption.resolve({}); await cancellation; await settle()
    assert.equal(h.active.value, true)
    assert.equal(h.text.value, '')
    assert.doesNotMatch(h.status.value, /Cancelled/)
  })
}

for (const staleFailure of [false, true]) {
  test(`a new question supersedes pending HTTP without waiting for cancellation (old ${staleFailure ? 'failure' : 'success'})`, async t => {
    const first = deferred(), second = deferred(), cancellation = deferred()
    let attempts = 0
    const h = composer(t, async call => {
      if (call.url === '/human') return ++attempts === 1 ? first.promise : second.promise
      if (call.url === '/interrupt_talk') return cancellation.promise
      return snapshot()
    })
    h.text.value = 'First question'
    const oldSubmission = h.send(); await settle()
    const oldRequest = h.calls.find(call => call.url === '/human')
    h.text.value = 'New question'
    const newSubmission = h.send(); await settle()
    try {
      const requests = h.calls.filter(call => call.url === '/human')
      assert.equal(requests.length, 2)
      assert.equal(requests[1].body.text, 'New question')
      assert.equal(requests[1].body.interrupt, true)
      assert.notEqual(requests[1].body.request_id, oldRequest.body.request_id)
      assert.equal(oldRequest.options.signal.aborted, true)
      assert.equal(h.calls.find(call => call.url === '/interrupt_talk').body.request_id, oldRequest.body.request_id)
      if (staleFailure) first.reject(new Error('stale error'))
      else first.resolve({ turn_id: 'stale-turn' })
      await oldSubmission; await settle()
      assert.equal(h.sending.value, true, 'old completion cannot release the new request')
      assert.equal(h.text.value, 'New question')
      assert.equal(h.error.value, '')
      second.resolve({ turn_id: 'new-turn' }); await newSubmission; await settle()
      assert.equal(h.text.value, '')
      assert.deepEqual(h.events.filter(event => event.name === 'accepted').map(event => event.value.text), ['New question'])
      h.receive({ type: 'turn_committed', turn_id: 'stale-turn', reason: 'completed' })
      assert.equal(h.active.value, true)
    } finally {
      first.resolve({}); second.resolve({}); cancellation.resolve({})
      await Promise.all([oldSubmission, newSubmission]); await settle()
    }
  })
}

test('acceptance keeps text edited while the previous question was sending', async t => {
  const response = deferred()
  const h = composer(t, async call => call.url === '/human' ? response.promise : snapshot())
  h.text.value = 'Sent question'
  const submission = h.send(); await settle()
  h.text.value = 'Next draft'
  response.resolve({ turn_id: 'accepted' }); await submission; await settle()
  assert.equal(h.text.value, 'Next draft')
  assert.equal(h.events.find(event => event.name === 'accepted').value.text, 'Sent question')
})

test('a stale attachment poll cannot undo a successfully saved selection', async t => {
  const poll = deferred()
  const h = composer(t, async call => call.url.endsWith('/attachments') ? poll.promise : {})
  const refresh = h.refresh()
  await h.toggle({ id: 'a' }, true)
  poll.resolve(snapshot([{ id: 'a' }], [])); await refresh
  assert.deepEqual(plain(h.selected.value), [{ id: 'a', pages: '' }])
})

test('selection writes are queued and submission waits for the latest selection', async t => {
  const first = deferred(), second = deferred(), writes = []
  const h = composer(t, async call => {
    if (call.url.endsWith('/selection')) { writes.push(call); return writes.length === 1 ? first.promise : second.promise }
    if (call.url === '/human') return { turn_id: 'selected-turn' }
    return snapshot()
  })
  const a = h.toggle({ id: 'a' }, true), b = h.toggle({ id: 'b' }, true)
  await settle()
  assert.equal(writes.length, 1)
  assert.deepEqual(writes[0].body.selection, [{ id: 'a', pages: '' }])
  h.text.value = 'Compare them'
  const submission = h.send(); await settle()
  assert.equal(h.calls.some(call => call.url === '/human'), false)
  first.resolve({}); await settle()
  assert.equal(writes.length, 2)
  assert.deepEqual(writes[1].body.selection, [{ id: 'a', pages: '' }, { id: 'b', pages: '' }])
  assert.equal(h.calls.some(call => call.url === '/human'), false)
  second.resolve({}); await Promise.all([a, b, submission]); await settle()
  assert.deepEqual(h.calls.find(call => call.url === '/human').body.attachments, writes[1].body.selection)
})

test('queued selections and old write failures cannot cross a session change', async t => {
  const oldWrite = deferred(), writes = []
  const h = composer(t, async call => {
    if (call.url.endsWith('/selection')) { writes.push(call); if (call.url.includes('/1/')) return oldWrite.promise; return {} }
    return snapshot()
  })
  const a = h.toggle({ id: 'old-a' }, true), b = h.toggle({ id: 'old-b' }, true)
  await settle()
  h.props.sessionId = 2; await settle()
  await h.toggle({ id: 'new-c' }, true)
  oldWrite.reject(new Error('old-session-error')); await Promise.all([a, b]); await settle()
  assert.equal(writes.filter(call => call.url.includes('/1/')).length, 1)
  assert.deepEqual(plain(h.selected.value), [{ id: 'new-c', pages: '' }])
  assert.equal(h.error.value, '')
})

test('voice events neither expose text cancellation nor restore a completed text retry', async t => {
  const h = composer(t, async call => call.url === '/human' ? { turn_id: 'text-turn' } : snapshot())
  h.receive({ type: 'state', state: 'llm', turn_id: 'voice-turn' })
  assert.equal(h.active.value, false)
  h.receive({ type: 'state', state: 'error', turn_id: 'voice-turn', error: 'voice-error' })
  assert.equal(h.error.value, '')
  h.text.value = 'Already answered'; await h.send(); await settle()
  h.receive({ type: 'turn_committed', turn_id: 'text-turn', reason: 'completed' })
  h.receive({ type: 'state', state: 'error', turn_id: 'later-voice-turn', error: 'voice-error' })
  assert.equal(h.active.value, false)
  assert.equal(h.text.value, '')
  assert.equal(h.error.value, '')
})

test('owned analysis errors restore the question for retry', async t => {
  const h = composer(t, async call => call.url === '/human' ? { turn_id: 'owned' } : snapshot())
  h.text.value = 'Retry this question'; await h.send(); await settle()
  h.receive({ type: 'state', state: 'error', turn_id: 'owned', error: 'analysis_capacity' })
  assert.equal(h.text.value, 'Retry this question')
  assert.equal(h.active.value, false)
  assert.match(h.error.value, /capacity/)
})

for (const fullResetSeconds of [60, 90]) {
test(`disconnection preserves drafts until the configured ${fullResetSeconds}s deadline`, async t => {
  const h = composer(t, undefined, { stage: true, settings: { ...attachments.composerDefaults, idle_reset_seconds: fullResetSeconds } })
  const file = new File(['png'], 'one.png', { type: 'image/png' })
  h.text.value = 'Unsent offline question'; h.add([file])
  h.receive({ type: 'state', state: 'llm', turn_id: 'voice-turn' })
  assert.equal(h.timers.size, 0)
  h.props.connected = false; await settle()
  assert.equal(h.timers.size, 1)
  await h.advance(fullResetSeconds * 1000 - 1)
  assert.equal(h.text.value, 'Unsent offline question')
  assert.equal(h.draft.value[0].file, file)
  await h.advance(1)
  assert.equal(h.text.value, '')
  assert.equal(h.draft.value.length, 0)
})

}

test('keyboard viewport bounds panel height and restores the configured position', t => {
  const h = composer(t, undefined, { stage: true })
  const parent = { getBoundingClientRect: () => ({ top: 0, bottom: 720, width: 360, height: 720 }) }
  h.root.value = { parentElement: parent, closest: () => parent, offsetHeight: 320 }
  h.window.visualViewport = { offsetTop: 0, height: 720, removeEventListener() {} }
  h.layout()
  const originalTop = h.placement.value.top
  h.window.visualViewport.height = 200; h.layout()
  assert.ok(parseFloat(h.placement.value.top) + parseFloat(h.placement.value.height) <= 192)
  h.window.visualViewport.offsetTop = 150; h.layout()
  assert.ok(parseFloat(h.placement.value.top) >= 150)
  assert.ok(parseFloat(h.placement.value.top) + parseFloat(h.placement.value.height) <= 342)
  h.window.visualViewport = { offsetTop: 0, height: 720, removeEventListener() {} }; h.layout()
  assert.equal(h.placement.value.top, originalTop)
  assert.equal(h.props.settings.composer_y, attachments.composerDefaults.composer_y)
})

test('desktop Enter sends while IME, Shift+Enter and touch keyboard Enter do not', async t => {
  const h = composer(t, async call => call.url === '/human' ? { turn_id: 'keyboard-turn' } : snapshot())
  let prevented = 0
  h.text.value = 'Question'
  for (const extra of [{ isComposing: true }, { keyCode: 229 }, { shiftKey: true }]) h.keydown({ key: 'Enter', preventDefault() { prevented++ }, ...extra })
  h.window.matchMedia = () => ({ matches: false })
  h.keydown({ key: 'Enter', preventDefault() { prevented++ } }); await settle()
  assert.equal(h.calls.some(call => call.url === '/human'), false)
  assert.equal(prevented, 0)
  h.window.matchMedia = () => ({ matches: true })
  h.keydown({ key: 'Enter', preventDefault() { prevented++ } }); await settle()
  assert.equal(h.calls.filter(call => call.url === '/human').length, 1)
  assert.equal(prevented, 1)
})

for (const permissionBeforeRelease of [true, false]) {
  test(`lazy microphone enabling consumes its gesture (permission ${permissionBeforeRelease ? 'before' : 'after'} pointerup)`, async () => {
    const permission = deferred(), captures = [], handlers = new Map()
    const stream = { getAudioTracks: () => [{}], getTracks: () => [] }
    const enable = stageSource.match(/ {2}async function enableMicrophone\(\)\{([\s\S]*?)\n {2}\}\n {2}mic\.addEventListener/)[1]
    const down = stageSource.match(/ {2}mic\.addEventListener\('pointerdown', \(e\) => \{([\s\S]*?)\n {2}\}\);/)[0]
    const up = stageSource.match(/ {2}mic\.addEventListener\('pointerup', \(e\) => \{([\s\S]*?)\n {2}\}\);/)[0]
    vm.runInNewContext(`
      let micStream=null, microphoneRequest=null, enablingMicrophonePress=false;
      let autoPaused=true, autoMode=true, speaking=false, interruptedPress=false, holding=false;
      const stageLocale='en-US';
      async function enableMicrophone(){${enable}\n}
      ${down}\n${up}
    `, {
      mic: { disabled: false, addEventListener: (type, fn) => handlers.set(type, fn) },
      pc: { getTransceivers: () => [{ receiver: { track: { kind: 'audio' } }, sender: { async replaceTrack() {} } }] },
      navigator: { mediaDevices: { getUserMedia: () => permission.promise } },
      setCapture: value => captures.push(value), setMode() {}, refreshAffordance() {},
      showSaid() {}, interrupt() {}, release() {}, setVisual() {}
    })
    const event = { preventDefault() {} }
    handlers.get('pointerdown')(event)
    if (permissionBeforeRelease) { permission.resolve(stream); await settle() }
    handlers.get('pointerup')(event)
    if (!permissionBeforeRelease) { permission.resolve(stream); await settle() }
    assert.deepEqual(captures, [true])
    handlers.get('pointerdown')(event); handlers.get('pointerup')(event)
    assert.deepEqual(captures, [true, false])
  })
}
