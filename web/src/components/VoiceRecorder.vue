<!-- Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
     Modified by HongXian0903, 2026. See LICENSE and NOTICE. -->
<template>
  <div>
    <div 
      class="voice-record-btn" 
      :class="{ 'recording-pulse': isRecording }"
      @mousedown="startRecording"
      @mouseup="stopRecording"
      @mouseleave="stopRecording"
      @touchstart.prevent="startRecording"
      @touchend="stopRecording"
    >
      <i class="bi bi-mic-fill"></i>
    </div>
    <div class="voice-record-label">{{ t('chat.voiceButton') }}，{{ t('chat.voiceButtonRecording') }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useSpeechRecognition } from '../composables/useSpeechRecognition'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const props = defineProps({
  inputText: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['message-recorded', 'update:inputText', 'notification'])

const isRecording = ref(false)
const { startRecognition, stopRecognition, isSupported } = useSpeechRecognition({
  onResult: (text) => {
    emit('update:inputText', text)
  },
  onFinalResult: (text) => {
    emit('message-recorded', text)
  }
})

let mediaRecorder = null
let audioChunks = []

const startRecording = async () => {
  if (isRecording.value) return
  
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    
    audioChunks = []
    mediaRecorder = new MediaRecorder(stream)
    
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        audioChunks.push(e.data)
      }
    }
    
    mediaRecorder.start()
    isRecording.value = true
    
    if (isSupported) {
      startRecognition()
    }
  } catch (error) {
    console.error('無法訪問麥克風:', error)
    emit('notification', '無法訪問麥克風，請檢查瀏覽器許可權設定', 'error')
  }
}

const stopRecording = () => {
  if (!isRecording.value || !mediaRecorder) return
  
  mediaRecorder.stop()
  isRecording.value = false
  
  // 停止所有音軌
  mediaRecorder.stream.getTracks().forEach(track => track.stop())
  
  if (isSupported) {
    stopRecognition()
  }
}
</script>

<style scoped>
.voice-record-btn {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background-color: var(--primary-color);
  color: white;
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 5px rgba(0,0,0,0.2);
  margin: 0 auto;
  user-select: none;
}

.voice-record-btn:hover {
  background-color: var(--secondary-color);
  transform: scale(1.05);
}

.voice-record-btn:active {
  background-color: #dc3545;
  transform: scale(0.95);
}

.voice-record-btn i {
  font-size: 24px;
}

.voice-record-label {
  text-align: center;
  margin-top: 10px;
  font-size: 14px;
  color: #6c757d;
}

.recording-pulse {
  animation: pulse 1.5s infinite;
  background-color: #dc3545 !important;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(220, 53, 69, 0.7);
  }
  70% {
    box-shadow: 0 0 0 15px rgba(220, 53, 69, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(220, 53, 69, 0);
  }
}
</style>
