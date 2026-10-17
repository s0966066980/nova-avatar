// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeRagSelection, toggleDataset, selectionError } from '../src/ragScope.js'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'

const dataset = 'a'.repeat(32), document = 'c'.repeat(32)
const Component = await loadComponent(new URL('../src/components/RagFlowSettings.vue', import.meta.url))
const response = data => ({ ok: true, json: async () => ({ code: 0, data }) })

test('移除知識庫後保持指定文本模式，空選擇不會變成全庫檢索', () => {
  const main = { enabled: true, dataset_ids: [dataset], document_scope: 'selected', document_ids: [document] }
  const specialist = normalizeRagSelection(main)
  specialist.document_ids.push('d'.repeat(32))
  assert.deepEqual(main.document_ids, [document])
  const next = toggleDataset(main, dataset, false)
  assert.equal(next.document_scope, 'selected')
  assert.deepEqual(next.document_ids, [])
  const reselected = toggleDataset(next, dataset, true)
  assert.match(selectionError(reselected), /至少一份文本/)
})

test('RAG 編輯器列出文件名稱，測試使用當前角色與草稿，舊測試不能覆蓋新範圍', async t => {
  const previousFetch = globalThis.fetch
  let resolveTest
  const requests = []
  globalThis.fetch = async (url, options) => {
    if (url === '/api/ragflow/status') return response({ configured: true })
    if (url === '/api/ragflow/datasets') return response({ datasets: [{ id: dataset, name: '場域服務知識', document_count: 1 }] })
    if (url.includes('/documents?')) return response({ documents: [{ id: document, name: '接待流程.txt', run: 'DONE', chunk_count: 3 }], has_more: false })
    if (url === '/api/ragflow/test') {
      requests.push(JSON.parse(options.body))
      return new Promise(resolve => { resolveTest = resolve })
    }
    throw Error(`Unexpected endpoint: ${url}`)
  }
  const view = mount(Component, {
    profileId: 'main', profileName: '接待員',
    modelValue: { enabled: true, dataset_ids: [dataset], document_scope: 'selected', document_ids: [document] }
  })
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
  await settle()
  assert.ok(textContent(view.root).includes('接待流程.txt'))
  assert.ok(textContent(view.root).includes('解析完成'))
  const input = all(view.root, n => n.type === 'textarea')[0]
  input.props['onUpdate:modelValue']('服務時間？')
  await settle()
  const action = button(view.root, '測試目前草稿')
  assert.equal(action.props.disabled, false)
  const pending = action.props.onClick()
  await settle()
  assert.deepEqual(requests[0], {
    profile_id: 'main', question: '服務時間？',
    selection: { enabled: true, dataset_ids: [dataset], document_scope: 'selected', document_ids: [document] }
  })
  view.props.modelValue = { ...view.props.modelValue, document_ids: ['d'.repeat(32)] }
  await settle()
  resolveTest(response({ sources: [{ document_name: '舊文件', content: '不應顯示的舊結果' }] }))
  await pending; await settle()
  assert.ok(!textContent(view.root).includes('不應顯示的舊結果'))
})
