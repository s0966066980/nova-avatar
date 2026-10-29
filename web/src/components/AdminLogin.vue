<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <main class="admin-login" data-theme="dark">
    <form class="admin-login-card" aria-labelledby="admin-login-heading" @submit.prevent="submit">
      <h1 id="admin-login-heading">Nova Avatar 控制台</h1>
      <template v-if="adminSession.status === 'unconfigured'">
        <p>尚未設定管理者密碼。請在場域主機的專案目錄執行：</p>
        <pre><code>uv run python scripts/configure-admin.py</code></pre>
        <button type="button" class="btn btn-primary" @click="refreshSession">重新檢查</button>
      </template>
      <template v-else-if="adminSession.status === 'checking'">
        <p>正在確認登入狀態…</p>
      </template>
      <template v-else>
        <label for="admin-password">管理者密碼</label>
        <input id="admin-password" v-model="password" type="password" autocomplete="current-password"
          class="form-control" :disabled="busy" required>
        <button type="submit" class="btn btn-primary" :disabled="busy || !password">{{ busy ? '登入中…' : '登入' }}</button>
      </template>
      <p v-if="adminSession.error" class="admin-login-error" role="alert">{{ adminSession.error }}</p>
    </form>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { adminSession, login, refreshSession } from '../adminSession.js'

const password = ref('')
const busy = ref(false)

async function submit() {
  if (busy.value || !password.value) return
  busy.value = true
  try {
    if (await login(password.value)) password.value = ''
  } catch {
    adminSession.error = '無法連線到後端，請稍後再試'
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.admin-login {
  min-height: 100dvh; display: grid; place-items: center; padding: 16px;
  background: var(--bg-page); color: var(--text-primary);
}
.admin-login-card {
  width: min(380px, 100%); display: grid; gap: 12px; padding: 28px;
  background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 12px;
}
.admin-login-card h1 { font-size: 20px; margin: 0 0 4px; }
.admin-login-card p { margin: 0; color: var(--text-secondary); }
.admin-login-card pre { margin: 0; padding: 10px; background: var(--bg-input); border-radius: 8px; white-space: pre-wrap; }
.admin-login-error { color: #f87171 !important; }
</style>
