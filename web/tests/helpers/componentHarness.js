// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

// Compile the real Vue component and render it in memory. No browser or extra
// test dependencies are needed to exercise event handlers and async state.
export async function loadComponent(url, stubs = {}, { inlineTemplate = true } = {}) {
  const { descriptor } = parse(readFileSync(url, 'utf8'), { filename: url.pathname })
  const script = compileScript(descriptor, { id: url.pathname, inlineTemplate, templateOptions: { compilerOptions: { hoistStatic: false } } })
  let source = script.content
  if (!inlineTemplate) {
    const template = compileTemplate({ id: url.pathname, source: descriptor.template.content,
      compilerOptions: { bindingMetadata: script.bindings, hoistStatic: false } })
    if (template.errors.length) throw new Error(template.errors.join('\n'))
    source = source.replace('export default', 'const component =') + '\n' +
      template.code.replace('export function render', 'function render') + '\ncomponent.render = render; return component;'
  }
  const imports = []
  const declarations = []
  for (const match of source.matchAll(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/g)) {
    const [statement, binding, specifier] = match
    const mod = stubs[specifier] || await import(specifier.startsWith('.') ? new URL(specifier, url).href : specifier)
    const index = imports.push(mod) - 1
    if (binding.startsWith('{')) {
      declarations.push(`const ${binding.replace(/\bas\b/g, ':')} = imports[${index}];`)
    } else declarations.push(`const ${binding} = imports[${index}].default;`)
    source = source.replace(statement, '')
  }
  source = source.replace('export default', 'return')
  return new Function('imports', declarations.join('\n') + '\n' + source)(imports)
}

// v-model compares the root node with these DOM classes; Node has neither.
globalThis.Document ??= class Document {}
globalThis.ShadowRoot ??= class ShadowRoot {}

function node(type, text = '') {
  return {
    type, text, children: [], props: {}, style: {}, parent: null, listeners: {},
    tagName: type.toUpperCase(),
    addEventListener(name, listener) { this.listeners[name] = listener },
    removeEventListener(name) { delete this.listeners[name] },
    setAttribute(name, value) { this.props[name] = value },
    removeAttribute(name) { delete this.props[name] },
    // Newer Vue 3.5 releases check v-model focus through the root node.
    getRootNode() { return globalThis.document },
    get options() { return this.children.filter(x => x.type === 'option') }
  }
}
const renderer = createRenderer({
  createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
  parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
  patchProp: (n, key, _previous, value) => { n.props[key] = value },
  insert(n, parent, anchor = null) {
    if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1)
    n.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(n); else parent.children.splice(index, 0, n)
  },
  remove(n) { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1) }
})
export function mount(Component, initialProps) {
  const previousDocument = globalThis.document
  globalThis.document ??= { activeElement: null }
  const props = reactive(initialProps)
  const root = node('root')
  const app = renderer.createApp({ render: () => h(Component, props) })
  app.mount(root)
  return { root, props, unmount: () => { app.unmount(); globalThis.document = previousDocument } }
}
export function all(root, predicate) {
  return [...(predicate(root) ? [root] : []), ...root.children.flatMap(child => all(child, predicate))]
}
export const textContent = root => root.text + root.children.map(textContent).join('')
export const button = (root, label) => all(root, n => n.type === 'button' && textContent(n).includes(label))[0]
export async function settle() { for (let i = 0; i < 12; i++) { await Promise.resolve(); await nextTick() } }
