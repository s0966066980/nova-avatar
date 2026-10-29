// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import html from 'eslint-plugin-html'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'srs.sdk.js'] },
  js.configs.recommended,
  ...vue.configs['flat/essential'],
  {
    // Adopt correctness checks first; unused-code cleanup and error-cause
    // conventions can be migrated independently of this initial gate.
    rules: {
      'no-unused-vars': 'off',
      'no-useless-assignment': 'off',
      'preserve-caught-error': 'off',
    },
  },
  {
    files: ['src/**/*.{js,vue}'],
    languageOptions: { globals: globals.browser },
    // Raw HTML sinks must go through src/markdown.js and carry a reviewed
    // single-line disable comment.
    rules: { 'vue/no-v-html': 'error' },
  },
  {
    // 公開舞台的 inline module script 也要納入 lint；其他 .html 為原型頁，不在守門範圍。
    files: ['stage.html'],
    plugins: { html },
    languageOptions: { globals: globals.browser, sourceType: 'module' },
  },
  {
    files: ['tests/**/*.js', '*.config.js'],
    languageOptions: { globals: globals.node },
  },
]
