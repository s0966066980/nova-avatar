// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

const DEFAULT_EXIT_DURATION_MS = 220

export class StageCaptionView {
  constructor({
    container,
    exitLayer,
    captionWindow,
    createNode,
    createExitNode = (node) => node.cloneNode(true),
    scheduleRemoval = (callback) => setTimeout(callback, DEFAULT_EXIT_DURATION_MS)
  }) {
    if (!container || !captionWindow) {
      throw new TypeError('StageCaptionView requires a container and caption window')
    }
    this.container = container
    this.exitLayer = exitLayer
    this.captionWindow = captionWindow
    this.createNode = createNode ?? ((fragment) => this.#createNode(fragment))
    this.createExitNode = createExitNode
    this.scheduleRemoval = scheduleRemoval
    this.resizeObserver = null

    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.fitHeight())
      this.resizeObserver.observe(this.container)
    }
  }

  append(text, turnId) {
    const result = this.captionWindow.append(text, turnId)
    if (result.newTurn) {
      this.#clearElement(this.container)
      this.#clearElement(this.exitLayer)
    }

    result.removed.forEach((fragment) => this.removeFragment(fragment))
    if (result.added) {
      const node = this.createNode(result.added)
      node.classList?.add('reply-fragment')
      node.dataset.fragmentId = String(result.added.id)
      this.container.append(node)
    }
    this.fitHeight()
    return result
  }

  fitHeight() {
    if (!Number.isFinite(this.container.clientHeight)) return
    while (
      this.container.scrollHeight > this.container.clientHeight
      && this.captionWindow.fragments.length > 1
    ) {
      const fragment = this.captionWindow.evictOldest()
      if (fragment) this.removeFragment(fragment)
    }
  }

  removeFragment(fragment) {
    const node = this.#findNode(fragment.id)
    if (!node) return

    const exitNode = this.createExitNode(node)
    exitNode.classList?.add('reply-fragment', 'reply-fragment-exit')
    if (this.exitLayer) {
      if (exitNode.style) {
        exitNode.style.top = `${Number(node.offsetTop) || 0}px`
      }
      this.exitLayer.append(exitNode)
      const startExit = () => exitNode.classList?.add('is-exiting')
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(startExit)
      else startExit()
    }

    // The kept-content layout must shrink synchronously. Only the clone animates.
    node.remove()
    if (this.exitLayer) {
      this.scheduleRemoval(() => exitNode.remove())
    }
  }

  clear() {
    this.captionWindow.clear()
    this.#clearElement(this.container)
    this.#clearElement(this.exitLayer)
  }

  destroy() {
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
  }

  #createNode(fragment) {
    const node = this.container.ownerDocument.createElement('span')
    node.textContent = fragment.text
    return node
  }

  #findNode(fragmentId) {
    const selector = `[data-fragment-id="${fragmentId}"]`
    const queried = this.container.querySelector?.(selector)
    if (queried) return queried
    return Array.from(this.container.children ?? [])
      .find((node) => node.dataset?.fragmentId === String(fragmentId))
  }

  #clearElement(element) {
    if (!element) return
    if (typeof element.replaceChildren === 'function') {
      element.replaceChildren()
      return
    }
    Array.from(element.children ?? []).forEach((child) => child.remove())
  }
}
