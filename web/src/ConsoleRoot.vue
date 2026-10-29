<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <App v-if="adminSession.status === 'authenticated'" />
  <AdminLogin v-else />
</template>

<script setup>
import { onMounted } from 'vue'
import App from './App.vue'
import AdminLogin from './components/AdminLogin.vue'
import { adminSession, refreshSession } from './adminSession.js'

onMounted(refreshSession)
</script>
