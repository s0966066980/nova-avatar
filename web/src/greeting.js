// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
export function visibleLength(text) {
  return [...segmenter.segment(String(text || ''))].filter(({ segment }) => !/^\p{White_Space}+$/u.test(segment)).length
}
export function greetingError(settings) {
  if (!Number.isInteger(settings.min_chars) || !Number.isInteger(settings.max_chars) || settings.min_chars <= 0 || settings.max_chars < settings.min_chars) return '請填寫有效的正整數字數範圍，最少字數不可大於最多字數。'
  if (settings.mode === 'ai' && !visibleLength(settings.prompt)) return '請填寫招呼 Prompt。'
  if (settings.mode === 'scripts' && !settings.scripts.some(text => visibleLength(text))) return '請填寫至少一篇預寫文案。'
  return ''
}
