// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'

const repoRoot = path.resolve(new URL('../..', import.meta.url).pathname)
const startServerPath = path.join(repoRoot, 'scripts/start-server.sh')
const serverConfigLibPath = path.join(repoRoot, 'scripts/lib/server-config.sh')
const jetsonServicePath = path.join(repoRoot, 'scripts/jetson-service.sh')
const startJetsonPath = path.join(repoRoot, 'scripts/start-jetson.sh')
const startAllPath = path.join(repoRoot, 'scripts/start-all.sh')

test('start-server.sh provides single-origin :8010 startup without Vite dev server', () => {
  assert.equal(existsSync(startServerPath), true, 'scripts/start-server.sh must exist')
  assert.equal(existsSync(serverConfigLibPath), true, 'scripts/lib/server-config.sh must exist')
  execFileSync('bash', ['-n', serverConfigLibPath])
  execFileSync('bash', ['-n', startServerPath])

  const content = readFileSync(startServerPath, 'utf8')
  const serviceContent = readFileSync(jetsonServicePath, 'utf8')
  assert.match(content, /dist\/index\.html/)
  assert.match(content, /dist\/stage\.html/)
  assert.match(content, /-newer/)
  assert.match(content, /src\/server\/app\.py/)
  assert.match(content, /scripts\/lib\/server-config\.sh/)
  assert.match(serviceContent, /scripts\/lib\/server-config\.sh/)
  assert.doesNotMatch(content, /^read_protocol\(\)/m)
  assert.doesNotMatch(serviceContent, /^read_protocol\(\)/m)
  assert.doesNotMatch(content, /npm .*run dev|clear_port 3000/)
})

test('start-server.sh refuses to auto-build missing web/dist without --build and explains how to proceed', () => {
  const scratch = mkdtempSync(path.join(tmpdir(), 'nova-start-server-'))
  try {
    mkdirSync(path.join(scratch, 'scripts/lib'), { recursive: true })
    mkdirSync(path.join(scratch, 'config'), { recursive: true })
    mkdirSync(path.join(scratch, 'web/node_modules'), { recursive: true })
    mkdirSync(path.join(scratch, '.venv'), { recursive: true })
    writeFileSync(path.join(scratch, 'config/config.yaml'), 'app:\n  listenport: 8010\n')
    const copiedScript = path.join(scratch, 'scripts/start-server.sh')
    writeFileSync(copiedScript, readFileSync(startServerPath, 'utf8'))
    if (existsSync(serverConfigLibPath)) {
      writeFileSync(path.join(scratch, 'scripts/lib/server-config.sh'), readFileSync(serverConfigLibPath, 'utf8'))
    }

    const fakeBin = path.join(scratch, 'bin')
    mkdirSync(fakeBin)
    writeFileSync(path.join(fakeBin, 'uv'), '#!/bin/sh\necho "uv 0.0"\n', { mode: 0o755 })
    writeFileSync(path.join(fakeBin, 'npm'), '#!/bin/sh\necho "npm should not run without --build" >&2\nexit 99\n', { mode: 0o755 })

    const res = spawnSync('bash', [copiedScript, path.join(scratch, 'config/config.yaml')], {
      cwd: scratch,
      env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}` },
      encoding: 'utf8'
    })
    assert.notEqual(res.status, 0)
    const output = res.stdout + res.stderr
    assert.match(output, /web\/dist/)
    assert.match(output, /cd web && npm run build/)
    assert.match(output, /--build/)
    assert.doesNotMatch(output, /npm should not run without --build/)
  } finally {
    rmSync(scratch, { recursive: true, force: true })
  }
})

test('start-jetson.sh and start-all.sh support --prod single-origin mode cleanly', () => {
  execFileSync('bash', ['-n', startJetsonPath])
  execFileSync('bash', ['-n', startAllPath])

  const jetsonHelp = execFileSync('bash', [startJetsonPath, '--help'], { encoding: 'utf8' })
  assert.match(jetsonHelp, /--prod/)

  const jetsonContent = readFileSync(startJetsonPath, 'utf8')
  assert.match(jetsonContent, /scripts\/start-server\.sh/)

  const allContent = readFileSync(startAllPath, 'utf8')
  assert.match(allContent, /--prod/)
  assert.match(allContent, /scripts\/start-server\.sh/)
})
