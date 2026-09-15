import assert from 'node:assert/strict'
import test from 'node:test'
import {
  boardReopenPresentation,
  captionStyle,
  placeStageBoard,
  previewScale,
  STAGE_LAYOUT_REF_WIDTH,
  STAGE_LAYOUT_REF_HEIGHT
} from '../src/stageBoardLayout.js'

test('展開看板按鈕靠舞台邊緣時改用朝內圖示並避免溢出', () => {
  assert.deepEqual(boardReopenPresentation(0, 20), {
    edge: 'left',
    icon: '›',
    style: { left: '0%', top: '20%', transform: 'translate(0, -50%)' }
  })
  assert.deepEqual(boardReopenPresentation(100, 20), {
    edge: 'right',
    icon: '‹',
    style: { left: '100%', top: '20%', transform: 'translate(-100%, -50%)' }
  })
  assert.equal(boardReopenPresentation(50, 20).icon, '▣')
})

test('字幕帶寬度與中心位置會限制在舞台可見範圍', () => {
  assert.deepEqual(captionStyle(0, 75, 60), {
    left: '30%',
    top: '75%',
    width: '60%',
    transform: 'translate(-50%, -50%)'
  })
  assert.equal(captionStyle(100, 90, 60).left, '70%')
})

test('右上對齊時看板貼近影像右上，不進入字幕帶', () => {
  const box = placeStageBoard({
    stageW: 405,
    stageH: 720,
    targetW: 252,
    targetH: 300,
    x: 100,
    y: 0,
    scale: 1
  })
  assert.ok(box.top < 20)
  assert.ok(box.left + box.width > 405 - 20)
  assert.ok(box.top + box.height <= 720 - box.captionH + 0.5)
})

test('控制台縮圖與參考舞台使用同一相對位置', () => {
  const full = placeStageBoard({
    stageW: STAGE_LAYOUT_REF_WIDTH,
    stageH: STAGE_LAYOUT_REF_HEIGHT,
    targetW: 252,
    targetH: 300,
    x: 0,
    y: 100,
    scale: 1
  })
  const miniW = 96
  const miniH = 170
  const scale = previewScale(miniW, miniH)
  const mini = placeStageBoard({
    stageW: miniW,
    stageH: miniH,
    targetW: 252,
    targetH: 300,
    x: 0,
    y: 100,
    scale
  })
  const fullX = full.left / STAGE_LAYOUT_REF_WIDTH
  const miniX = mini.left / miniW
  const fullY = (full.top + full.height) / STAGE_LAYOUT_REF_HEIGHT
  const miniY = (mini.top + mini.height) / miniH
  assert.ok(Math.abs(fullX - miniX) < 0.08)
  assert.ok(Math.abs(fullY - miniY) < 0.08)
})

test('不同大小的 9:16 舞台會維持相同看板比例與安全區', () => {
  const reference = placeStageBoard({
    stageW: STAGE_LAYOUT_REF_WIDTH,
    stageH: STAGE_LAYOUT_REF_HEIGHT,
    targetW: 252,
    targetH: 300,
    x: 70,
    y: 35,
    scale: 1
  })
  const enlarged = placeStageBoard({
    stageW: STAGE_LAYOUT_REF_WIDTH * 2,
    stageH: STAGE_LAYOUT_REF_HEIGHT * 2,
    targetW: 252,
    targetH: 300,
    x: 70,
    y: 35,
    scale: previewScale(STAGE_LAYOUT_REF_WIDTH * 2, STAGE_LAYOUT_REF_HEIGHT * 2)
  })

  for (const key of ['left', 'top', 'width', 'height', 'captionH']) {
    assert.equal(enlarged[key], reference[key] * 2)
  }
})
