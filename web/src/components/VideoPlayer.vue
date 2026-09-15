<!-- Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
     Modified by HongXian0903, 2026. See LICENSE and NOTICE. -->
<template>
  <div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <div>
        <span 
          class="status-indicator" 
          :class="statusClass"
        ></span>
        <span>{{ statusText }}</span>
      </div>
    </div>
    
    <div class="card-body p-0">
      <div class="video-container">
        <video id="video" autoplay playsinline></video>
        <div class="recording-indicator" :class="{ active: isRecording }">
          <div class="blink"></div>
          <span>錄製中</span>
        </div>
      </div>
      
      <div class="controls-container">
        <div class="row">
          <div class="col-md-6 mb-3">
            <button 
              v-if="!isConnected" 
              class="btn btn-primary w-100" 
              @click="$emit('start-connection')"
            >
              <i class="bi bi-play-fill"></i> 開始連線
            </button>
            <button 
              v-else 
              class="btn btn-danger w-100" 
              @click="$emit('stop-connection')"
            >
              <i class="bi bi-stop-fill"></i> 停止連線
            </button>
          </div>
          
          <div class="col-md-6 mb-3">
            <div class="d-flex">
              <button 
                class="btn btn-outline-primary flex-grow-1 me-2" 
                @click="$emit('start-record')"
                :disabled="isRecording"
              >
                <i class="bi bi-record-fill"></i> 開始錄製
              </button>
              <button 
                class="btn btn-outline-danger flex-grow-1" 
                @click="$emit('stop-record')"
                :disabled="!isRecording"
              >
                <i class="bi bi-stop-fill"></i> 停止錄製
              </button>
            </div>
          </div>
        </div>

        <div class="row">
          <div class="col-12">
            <div class="video-size-control">
              <label class="form-label">
                影片大小調節: <span>{{ videoSize }}%</span>
              </label>
              <input 
                type="range" 
                class="form-range" 
                min="50" 
                max="150" 
                v-model="videoSize"
                @input="updateVideoSize"
              >
            </div>
          </div>
        </div>
        

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  connectionStatus: {
    type: String,
    default: 'disconnected'
  },
  isRecording: {
    type: Boolean,
    default: false
  }
})

defineEmits(['start-connection', 'stop-connection', 'start-record', 'stop-record'])

const videoSize = ref(100)

const isConnected = computed(() => props.connectionStatus === 'connected')

const statusClass = computed(() => {
  return {
    'status-connected': props.connectionStatus === 'connected',
    'status-connecting': props.connectionStatus === 'connecting',
    'status-disconnected': props.connectionStatus === 'disconnected'
  }
})

const statusText = computed(() => {
  const statusMap = {
    'connected': '已連線',
    'connecting': '連線中...',
    'disconnected': '未連線'
  }
  return statusMap[props.connectionStatus] || '未連線'
})

const updateVideoSize = () => {
  const video = document.getElementById('video')
  if (video) {
    video.style.width = `${videoSize.value}%`
  }
}
</script>

<style scoped>
.card {
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
  padding: 15px 20px;
  border-bottom: none;
}

.video-container {
  position: relative;
  width: 100%;
  background-color: #000;
  border-radius: var(--border-radius);
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

video {
  max-width: 100%;
  max-height: 100%;
  display: block;
  border-radius: var(--border-radius);
}

.controls-container {
  padding: 20px;
}

.btn-primary {
  background-color: var(--primary-color);
  border-color: var(--primary-color);
}

.btn-primary:hover {
  background-color: var(--secondary-color);
  border-color: var(--secondary-color);
}

.btn-outline-primary {
  color: var(--primary-color);
  border-color: var(--primary-color);
}

.btn-outline-primary:hover {
  background-color: var(--primary-color);
  color: white;
}

.form-control {
  border-radius: var(--border-radius);
  padding: 10px 15px;
  border: 1px solid #ced4da;
}

.form-control:focus {
  border-color: var(--accent-color);
  box-shadow: 0 0 0 0.25rem rgba(67, 97, 238, 0.25);
}

.status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 5px;
}

.status-connected {
  background-color: #28a745;
}

.status-disconnected {
  background-color: #dc3545;
}

.status-connecting {
  background-color: #ffc107;
}

.recording-indicator {
  position: absolute;
  top: 15px;
  right: 15px;
  background-color: rgba(220, 53, 69, 0.8);
  color: white;
  padding: 5px 10px;
  border-radius: 20px;
  font-size: 0.8rem;
  display: none;
}

.recording-indicator.active {
  display: flex;
  align-items: center;
}

.recording-indicator .blink {
  width: 10px;
  height: 10px;
  background-color: #fff;
  border-radius: 50%;
  margin-right: 5px;
  animation: blink 1s infinite;
}

@keyframes blink {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}

.video-size-control {
  margin-top: 15px;
}

.settings-panel {
  padding: 15px;
  background-color: #f8f9fa;
  border-radius: var(--border-radius);
  margin-top: 15px;
}
</style>
