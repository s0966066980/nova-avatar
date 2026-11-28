import assert from 'node:assert/strict'
import test from 'node:test'
import { StageCaptionWindow } from '../src/stage/stageCaptionWindow.js'
import { StageCaptionView } from '../src/stage/stageCaptionView.js'

class FakeClassList {
  constructor() {
    this.values = new Set()
  }

  add(value) {
    this.values.add(value)
  }
}

class FakeNode {
  constructor(tag = 'div', text = '') {
    this.tagName = tag.toUpperCase()
    this.textContent = text
    this.dataset = {}
    this.children = []
    this.parentNode = null
    this.classList = new FakeClassList()
    this.clientHeight = 100
  }

  get scrollHeight() {
    return this.children.length * 60
  }

  append(node) {
    node.parentNode = this
    this.children.push(node)
  }

  removeChild(node) {
    this.children = this.children.filter((child) => child !== node)
    node.parentNode = null
  }

  remove() {
    this.parentNode?.removeChild(this)
  }

  cloneNode() {
    const clone = new FakeNode(this.tagName, this.textContent)
    clone.dataset = { ...this.dataset }
    return clone
  }

  querySelector(selector) {
    const match = selector.match(/data-fragment-id="([^"]+)"/)
    return this.children.find((child) => child.dataset.fragmentId === match?.[1]) ?? null
  }
}

test('淘汰片段立即離開正常排版，離場複本才負責動畫', () => {
  const container = new FakeNode('div')
  const exitLayer = new FakeNode('div')
  const captionWindow = new StageCaptionWindow(200)
  const view = new StageCaptionView({
    container,
    exitLayer,
    captionWindow,
    createNode: (fragment) => new FakeNode('span', fragment.text),
    scheduleRemoval: () => {}
  })

  view.append('第一個完整片段。', 'turn-1')
  view.append('第二個完整片段。', 'turn-1')

  assert.equal(container.children.length, 1)
  assert.equal(container.children[0].textContent, '第二個完整片段。')
  assert.equal(exitLayer.children.length, 1)
  assert.equal(container.scrollHeight <= container.clientHeight, true)
})

test('舞台呈現器不使用像素捲動來維持最新字幕', () => {
  const container = new FakeNode('div')
  const exitLayer = new FakeNode('div')
  const view = new StageCaptionView({
    container,
    exitLayer,
    captionWindow: new StageCaptionWindow(200),
    createNode: (fragment) => new FakeNode('span', fragment.text),
    scheduleRemoval: () => {}
  })

  view.append('完整片段。', 'turn-1')

  assert.equal('scrollTop' in container, false)
  assert.equal(container.children.length, 1)
})
