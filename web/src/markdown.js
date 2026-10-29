// Derived from Kedreamix/Linly-Talker-Stream (web/src/App.vue).
// Copyright [Linly-talker-stream@kedreamix].
// Licensed under the Apache License, Version 2.0.
//
// Modified by HongXian0903, 2026.
// See LICENSE and NOTICE for details.

import { Marked } from 'marked'
import DOMPurify from 'dompurify'

// LLM output can be steered by RAG documents and attachment OCR, so the
// console treats every chat message as untrusted before it reaches v-html.

// 過濾協定標記與 JSON 格式，避免 [speech 等符號洩漏到介面
export function stripProtocolMarkers(text) {
  if (!text) return ''
  let clean = String(text)
  // Strip tool-call tags and reasoning
  clean = clean.replace(/<\|tool_call_start\|>[\s\S]*?<\|tool_call_end\|>/g, '')
  clean = clean.replace(/<\|tool_call_start\|>[\s\S]*/g, '')
  clean = clean.replace(/<\|tool_call_end\|>/g, '')
  clean = clean.replace(/\[(?:BOARD|think|thought|speech)\([\s\S]*?\)?\]/g, '')

  // Strip mode markers
  clean = clean.replace(/\[{1,2}\s*MODE:\s*(?:SIMPLE|BOARD)\s*\]{1,2}/gi, '')
  clean = clean.replace(/模式\s*[:：]\s*(?:簡答|看板)/g, '')

  // Strip speech markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*(?:SPEECH|speech)(?::\s*)?\]{1,2}/gi, '')
  clean = clean.replace(/\[{1,2}\s*(?:SPEECH|speech)\s*:\s*/gi, '')
  clean = clean.replace(/(?:^|[\r\n]+)\s*SPEECH\s*:\s*/gi, '\n')
  clean = clean.replace(/(?:^|[\r\n]+)\s*口語\s*[:：]\s*/g, '\n')

  // Strip board markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*BOARD(?:_JSON)?(?::\s*)?\]{1,2}/gi, '')
  clean = clean.replace(/\[{1,2}\s*BOARD(?:_JSON)?\s*:\s*/gi, '')
  clean = clean.replace(/(?:^|[\r\n]+)\s*BOARD(?:_JSON)?\s*:\s*/gi, '\n')
  clean = clean.replace(/看板(?:資料)?\s*[:：]/g, '')
  clean = clean.replace(/資料\s*[:：]/g, '')

  // Strip end markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*END\s*\]{1,2}/gi, '')

  // Cut off before raw JSON or markdown JSON fence
  const jsonMatch = clean.match(/(?:```(?:json)?\s*)?[\r\n]+\s*\{(?:\s*"title"|\s*"items"|\s*"summary")/i)
  if (jsonMatch && jsonMatch.index !== undefined) {
    clean = clean.slice(0, jsonMatch.index)
  }

  // Strip trailing unclosed bracket if [speech: was stripped
  if (clean.endsWith(']') && clean.split(']').length > clean.split('[').length) {
    clean = clean.slice(0, -1)
  }

  return clean.trim()
}

const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, ch => HTML_ESCAPES[ch])
}

// Build a renderer around a DOMPurify instance. The browser uses the default
// window-bound instance; tests pass one bound to a jsdom window.
export function createMarkdownRenderer(purifier) {
  const marked = new Marked({
    breaks: true,
    gfm: true,
    // Drop raw HTML blocks and inline tags; only Markdown syntax produces markup.
    renderer: { html: () => '' },
  })
  return (text) => {
    const clean = stripProtocolMarkers(text)
    if (!clean) return ''
    // Fail closed: without a working sanitizer, show escaped plain text only.
    if (!purifier?.isSupported) return escapeHtml(clean)
    try {
      return purifier.sanitize(marked.parse(clean))
    } catch (error) {
      console.error('Markdown 解析錯誤:', error)
      return escapeHtml(clean)
    }
  }
}

export const renderMarkdown = createMarkdownRenderer(DOMPurify)
