<!-- Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
     Modified by HongXian0903, 2026. See LICENSE and NOTICE. -->
<template>
  <div v-if="showDebug" class="debug-panel">
    <div class="debug-header" @click="toggleCollapse">
      <i class="bi" :class="collapsed ? 'bi-chevron-down' : 'bi-chevron-up'"></i>
      除錯資訊
    </div>
    <div v-show="!collapsed" class="debug-content">
      <div class="debug-item">
        <strong>後端協議:</strong>
        <span class="text-success">即時影音</span>
      </div>
      <div class="debug-item">
        <strong>連線狀態:</strong> {{ connectionStatus }}
      </div>
      <div class="debug-item">
        <strong>會話ID:</strong> {{ sessionId }}
      </div>
      <div class="debug-item">
        <strong>後端API:</strong> localhost:8010
      </div>
      <div class="debug-item">
        <strong>Video元素:</strong> 
        <span :class="videoExists ? 'text-success' : 'text-danger'">
          {{ videoExists ? '✅ 存在' : '❌ 不存在' }}
        </span>
      </div>
      <div class="debug-item">
        <strong>瀏覽器:</strong> {{ userAgent }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const props = defineProps({
  connectionStatus: String,
  sessionId: Number
})

const showDebug = ref(true)
const collapsed = ref(false)
const videoExists = ref(false)
const userAgent = ref('')

const toggleCollapse = () => {
  collapsed.value = !collapsed.value
}

onMounted(() => {
  userAgent.value = navigator.userAgent.split(' ').slice(-2).join(' ')
  
  setInterval(() => {
    videoExists.value = document.getElementById('video') !== null
  }, 1000)
})
</script>

<style scoped>
.debug-panel {
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: rgba(0, 0, 0, 0.9);
  color: white;
  border-radius: 8px;
  padding: 0;
  min-width: 300px;
  font-size: 12px;
  z-index: 9999;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.debug-header {
  padding: 10px 15px;
  background: #333;
  border-radius: 8px 8px 0 0;
  cursor: pointer;
  font-weight: bold;
  display: flex;
  align-items: center;
  gap: 8px;
}

.debug-header:hover {
  background: #444;
}

.debug-content {
  padding: 15px;
}

.debug-item {
  margin-bottom: 8px;
  line-height: 1.6;
}

.text-success {
  color: #4ade80;
}

.text-danger {
  color: #f87171;
}
</style>
