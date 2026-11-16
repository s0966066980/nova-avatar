// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

test('vite config reads app.ssl_cert and app.ssl_key from active config file', async () => {
  const repoRoot = path.resolve(new URL('../..', import.meta.url).pathname)
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vite-ssl-config-'))
  try {
    const certPath = path.join(tmpDir, 'server.crt')
    const keyPath = path.join(tmpDir, 'server.key')
    fs.writeFileSync(certPath, 'CUSTOM-CERT-PEM', 'utf8')
    fs.writeFileSync(keyPath, 'CUSTOM-KEY-PEM', 'utf8')

    const relCert = path.relative(repoRoot, certPath)
    const relKey = path.relative(repoRoot, keyPath)
    const configPath = path.join(tmpDir, 'custom.yaml')
    fs.writeFileSync(
      configPath,
      [
        'app:',
        '  listenport: 8010',
        '  ssl: true',
        `  ssl_cert: ${relCert}`,
        `  ssl_key: ${relKey}`,
        '  web:',
        '    port: 3000',
        '    host: 0.0.0.0'
      ].join('\n'),
      'utf8'
    )

    const { createViteConfig } = await import('../vite.config.js')
    const resolved = createViteConfig({
      command: 'serve',
      env: { CONFIG_FILE: configPath, VITE_CONFIG_QUIET: '1' }
    })

    assert.equal(resolved.server.https.cert.toString('utf8'), 'CUSTOM-CERT-PEM')
    assert.equal(resolved.server.https.key.toString('utf8'), 'CUSTOM-KEY-PEM')
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
})

test('vite config build command does not require ssl files on disk', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vite-ssl-build-'))
  try {
    const configPath = path.join(tmpDir, 'missing-certs.yaml')
    fs.writeFileSync(
      configPath,
      [
        'app:',
        '  ssl: true',
        `  ssl_cert: ${path.join(tmpDir, 'missing.crt')}`,
        `  ssl_key: ${path.join(tmpDir, 'missing.key')}`
      ].join('\n'),
      'utf8'
    )

    const { createViteConfig } = await import('../vite.config.js')
    const resolved = createViteConfig({
      command: 'build',
      env: { CONFIG_FILE: configPath, VITE_CONFIG_QUIET: '1' }
    })

    assert.equal(resolved.server.https, undefined)
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
})

test('vite config omits server.https when app.ssl is false', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vite-ssl-off-'))
  try {
    const configPath = path.join(tmpDir, 'http.yaml')
    fs.writeFileSync(
      configPath,
      [
        'app:',
        '  ssl: false',
        '  ssl_cert: ssl_certs/server.crt',
        '  ssl_key: ssl_certs/server.key'
      ].join('\n'),
      'utf8'
    )

    const { createViteConfig } = await import('../vite.config.js')
    const resolved = createViteConfig({
      command: 'serve',
      env: { CONFIG_FILE: configPath, VITE_CONFIG_QUIET: '1' }
    })

    assert.equal(resolved.server.https, undefined)
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
})
