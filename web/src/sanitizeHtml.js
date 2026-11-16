// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import { Marked } from 'marked'

const ALLOWED_TAGS = [
  'p',
  'br',
  'hr',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'strong',
  'b',
  'em',
  'i',
  'u',
  's',
  'del',
  'mark',
  'sub',
  'sup',
  'blockquote',
  'pre',
  'code',
  'span',
  'ul',
  'ol',
  'li',
  'a',
  'img',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
]

const ALLOWED_ATTR = [
  'href',
  'title',
  'target',
  'rel',
  'src',
  'alt',
  'class',
  'colspan',
  'rowspan',
]

const FORBID_TAGS = [
  'script',
  'style',
  'iframe',
  'object',
  'embed',
  'svg',
  'math',
  'form',
  'input',
  'textarea',
  'select',
  'button',
  'base',
  'link',
  'meta',
]

const FORBID_ATTR = ['style', 'srcdoc']

const ALLOWED_URI_REGEXP = /^(?:(?:https?|mailto|tel):|[^:/?#]*(?:[/?#]|$))/i

const DOMPURIFY_CONFIG = {
  ALLOWED_TAGS,
  ALLOWED_ATTR,
  FORBID_TAGS,
  FORBID_ATTR,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  ALLOWED_URI_REGEXP,
}

const markdownParser = new Marked({
  breaks: true,
  gfm: true,
  renderer: {
    code({ text, lang }) {
      const source = String(text ?? '')
      const language = typeof lang === 'string' ? lang.trim() : ''
      let highlighted
      if (language && hljs.getLanguage(language)) {
        try {
          highlighted = hljs.highlight(source, { language }).value
        } catch {
          highlighted = escapeHtml(source)
        }
      } else {
        try {
          highlighted = hljs.highlightAuto(source).value
        } catch {
          highlighted = escapeHtml(source)
        }
      }
      const classAttr = language
        ? ` class="hljs language-${escapeHtml(language)}"`
        : ' class="hljs"'
      return `<pre><code${classAttr}>${highlighted}</code></pre>\n`
    },
  },
})

export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const configuredPurifiers = new WeakSet()

function configurePurifier(purifier) {
  if (!purifier || configuredPurifiers.has(purifier)) return purifier
  if (typeof purifier.addHook === 'function') {
    purifier.addHook('uponSanitizeAttribute', (_node, data) => {
      if (data.attrName === 'src' || data.attrName === 'href' || data.attrName === 'xlink:href') {
        const normalized = String(data.attrValue || '')
          .replace(/[\u0000-\u0020]+/g, '')
          .toLowerCase()
        if (
          normalized.startsWith('data:') ||
          normalized.startsWith('javascript:') ||
          normalized.startsWith('vbscript:')
        ) {
          data.keepAttr = false
        }
      }
    })
  }
  configuredPurifiers.add(purifier)
  return purifier
}

function resolvePurifier(domWindow) {
  if (domWindow) {
    return configurePurifier(DOMPurify(domWindow))
  }
  if (DOMPurify.isSupported && typeof DOMPurify.sanitize === 'function') {
    return configurePurifier(DOMPurify)
  }
  if (typeof globalThis.window !== 'undefined') {
    return configurePurifier(DOMPurify(globalThis.window))
  }
  return null
}

/**
 * Sanitize an HTML fragment with a strict DOMPurify allowlist.
 * Fails closed to escaped text if no DOM window is available.
 */
export function sanitizeHtml(html, { domWindow } = {}) {
  if (!html) return ''
  const raw = String(html)
  const purifier = resolvePurifier(domWindow)
  if (!purifier || !purifier.isSupported || typeof purifier.sanitize !== 'function') {
    return escapeHtml(raw)
  }
  return purifier.sanitize(raw, DOMPURIFY_CONFIG)
}

/**
 * Render Markdown text to sanitized HTML safe for v-html binding.
 */
export function renderSafeMarkdown(text, { domWindow } = {}) {
  if (!text) return ''
  const source = String(text)
  try {
    const rendered = markdownParser.parse(source)
    return sanitizeHtml(rendered, { domWindow })
  } catch (error) {
    console.error('Markdown 解析錯誤:', error)
    return escapeHtml(source)
  }
}
