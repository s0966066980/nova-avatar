// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { composerDefaults, composerPlacement, shouldSend, validateDraft } from '../src/conversationAttachments.js'
import { placeStageCaption } from '../src/stageBoardLayout.js'

test('configured composer height is stable and scales with the stage canvas', () => {
  const settings = { ...composerDefaults, composer_height: 180 }
  const preview = composerPlacement(settings, 405, 720)
  const stage = composerPlacement(settings, 810, 1440)
  assert.equal(parseFloat(preview.height), 180)
  assert.equal(parseFloat(stage.height), 360)
  assert.equal(parseFloat(stage.top), parseFloat(preview.top) * 2)
  assert.equal(parseFloat(stage.width), parseFloat(preview.width) * 2)
})

test('reply captions avoid the configured composer on both preview and stage', () => {
  const settings = { ...composerDefaults, composer_y: 99, composer_width: 100, composer_height: 220 }
  const input = composerPlacement(settings, 405, 720)
  const composer = Object.fromEntries(['left', 'top', 'width', 'height'].map(key => [key, parseFloat(input[key])]))
  const caption = placeStageCaption({ stageW: 405, stageH: 720, x: 50, y: 82, width: 100,
    captionH: 180, composer })
  assert.ok(parseFloat(caption.top) + 180 <= composer.top - 8)
  const above = placeStageCaption({ stageW: 405, stageH: 720, x: 50, y: 10, width: 100,
    captionH: 80, composer })
  assert.equal(above.transform, 'translate(-50%, -50%)')
})

test('Chinese IME confirmation and shift-enter do not send', () => {
  assert.equal(shouldSend({ key: 'Enter', isComposing: true }), false)
  assert.equal(shouldSend({ key: 'Enter', keyCode: 229 }), false)
  assert.equal(shouldSend({ key: 'Enter', shiftKey: true }), false)
  assert.equal(shouldSend({ key: 'Enter' }), true)
})
test('new uploads and existing references share the four-file budget', () => {
  assert.throws(() => validateDraft([{ name: 'one.pdf', size: 100 }], 4), /reference_limit/)
  assert.throws(() => validateDraft([{ name: 'one.pdf', size: 20_000_001 }], 0), /file_size/)
  assert.throws(() => validateDraft([{ name: 'one.svg', size: 100 }], 0), /unsupported_file/)
})
test('composer remains inside stage after keyboard shrinks viewport', () => {
  const settings = { ...composerDefaults, composer_x: 100, composer_y: 100 }
  const box = composerPlacement(settings, 360, 640, { availableHeight: 300 })
  assert.ok(parseFloat(box.left) + parseFloat(box.width) <= 360 - 8)
  assert.ok(parseFloat(box.top) + parseFloat(box.height) <= 300 - 8)
  assert.equal(settings.composer_y, 100)
  const small = composerPlacement(settings, 360, 640, { availableHeight: 200 })
  assert.ok(parseFloat(small.top) + parseFloat(small.height) <= 200 - 8)
})
