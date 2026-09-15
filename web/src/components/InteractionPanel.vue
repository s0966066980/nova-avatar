<!-- Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
     Modified by HongXian0903, 2026. See LICENSE and NOTICE. -->
<template>
  <div class="card interaction-card">
    <div class="card-header">
      <ul class="nav nav-tabs card-header-tabs" role="tablist">
        <li class="nav-item" role="presentation">
          <button 
            class="nav-link" 
            :class="{ active: activeTab === 'chat' }"
            @click="activeTab = 'chat'"
            type="button"
          >
            對話模式
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button 
            class="nav-link" 
            :class="{ active: activeTab === 'tts' }"
            @click="activeTab = 'tts'"
            type="button"
          >
            朗讀模式
          </button>
        </li>
      </ul>
    </div>
    
    <div class="card-body">
      <!-- 對話模式 -->
      <div v-if="activeTab === 'chat'" class="chat-panel">
        <div class="asr-container mb-3" ref="chatMessagesRef">
          <div 
            v-for="(msg, index) in chatMessages" 
            :key="index"
            class="asr-text"
            :class="msg.type === 'user' ? 'user-message' : 'system-message'"
          >
            {{ msg.type === 'user' ? '您' : '數字人' }}: {{ msg.text }}
          </div>
        </div>
        
        <form @submit.prevent="sendChatMessage" class="chat-form">
          <div class="mb-3">
            <textarea 
              class="form-control" 
              v-model="chatInput"
              rows="3" 
              placeholder="輸入您想對數字人說的話..."
            ></textarea>
          </div>
          <button class="btn btn-primary w-100 mb-3" type="submit">
            <i class="bi bi-send"></i> 傳送訊息
          </button>
        </form>
        
        <VoiceRecorder 
          @message-recorded="handleVoiceMessage"
          v-model:input-text="chatInput"
          @notification="(message, type) => emit('notification', message, type)"
        />
      </div>
      
      <!-- 朗讀模式 -->
      <div v-if="activeTab === 'tts'" class="tts-panel">
        <form @submit.prevent="sendTTSMessage">
          <div class="mb-3">
            <label for="tts-message" class="form-label">輸入要朗讀的文本</label>
            <textarea 
              class="form-control" 
              id="tts-message"
              v-model="ttsInput"
              rows="8" 
              placeholder="輸入您想讓數字人朗讀的文字..."
            ></textarea>
          </div>
          <button type="submit" class="btn btn-primary w-100">
            <i class="bi bi-volume-up"></i> 朗讀文本
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import VoiceRecorder from './VoiceRecorder.vue'

const props = defineProps({
  sessionId: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['send-message', 'notification'])

const activeTab = ref('chat')
const chatInput = ref('')
const ttsInput = ref('')
const chatMessages = ref([
  { type: 'system', text: '歡迎使用 Nova Avatar，請點選「開始連線」按鈕開始對話。' }
])
const chatMessagesRef = ref(null)

const addChatMessage = (text, type = 'user') => {
  chatMessages.value.push({ text, type })
  nextTick(() => {
    if (chatMessagesRef.value) {
      chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight
    }
  })
}

const sendChatMessage = () => {
  if (!chatInput.value.trim()) return
  
  const message = chatInput.value
  addChatMessage(message, 'user')
  
  emit('send-message', {
    text: message,
    type: 'chat'
  })
  
  chatInput.value = ''
}

const sendTTSMessage = () => {
  if (!ttsInput.value.trim()) return
  
  const message = ttsInput.value
  
  emit('send-message', {
    text: message,
    type: 'echo'
  })
  
  addChatMessage(`已傳送朗讀請求: "${message}"`, 'system')
  ttsInput.value = ''
}

const handleVoiceMessage = (text) => {
  if (!text.trim()) return
  
  addChatMessage(text, 'user')
  
  emit('send-message', {
    text: text,
    type: 'chat'
  })
}
</script>

<style scoped>
.interaction-card {
  background-color: var(--card-bg);
  border-radius: var(--border-radius);
  box-shadow: var(--box-shadow);
  border: none;
  margin-bottom: 20px;
  overflow: hidden;
}

.card-header {
  background-color: var(--primary-color);
  color: white;
  font-weight: 600;
  padding: 0;
  border-bottom: none;
}

.card-body {
  padding: 20px;
  min-height: 500px;
}

.nav-tabs {
  border-bottom: none;
  margin-bottom: 0;
}

.nav-tabs .nav-link {
  color: white;
  border: none;
  padding: 15px 20px;
  border-radius: 0;
  opacity: 0.7;
  background-color: transparent;
}

.nav-tabs .nav-link.active {
  color: var(--primary-color);
  background-color: var(--card-bg);
  border-bottom: none;
  font-weight: 600;
  opacity: 1;
}

.chat-panel,
.tts-panel {
  display: block;
  width: 100%;
}

.asr-container {
  height: 300px;
  overflow-y: auto;
  padding: 15px;
  background-color: #f8f9fa;
  border-radius: var(--border-radius);
  border: 1px solid #ced4da;
}

.asr-text {
  margin-bottom: 10px;
  padding: 10px;
  background-color: white;
  border-radius: var(--border-radius);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.user-message {
  background-color: #e3f2fd;
  border-left: 4px solid var(--primary-color);
}

.system-message {
  background-color: #f1f8e9;
  border-left: 4px solid #8bc34a;
}

.form-control {
  border-radius: var(--border-radius);
  padding: 10px 15px;
  border: 1px solid #ced4da;
  width: 100%;
  resize: vertical;
}

.form-control:focus {
  border-color: var(--accent-color);
  box-shadow: 0 0 0 0.25rem rgba(67, 97, 238, 0.25);
  outline: none;
}

.btn-primary {
  background-color: var(--primary-color);
  border-color: var(--primary-color);
  padding: 10px 20px;
}

.btn-primary:hover {
  background-color: var(--secondary-color);
  border-color: var(--secondary-color);
}

.chat-form {
  margin-bottom: 20px;
}

.form-label {
  font-weight: 600;
  margin-bottom: 10px;
  display: block;
}
</style>
