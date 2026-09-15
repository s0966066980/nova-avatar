// Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
// Modified by HongXian0903, 2026. See LICENSE and NOTICE.

// One peer connection carries avatar A/V, the microphone uplink and voice events.
export function useWebRTC(options = {}) {
  let pc = null
  let eventChannel = null
  let microphoneStream = null
  let sessionIdValue = 0
  let lastEventSequence = 0
  let captureRequested = true
  let reconnectTimer = null
  let shouldReconnect = false
  let lastStunServer = null
  let startPromise = null
  const boardDisplayReceipts = new Set()
  const { onNotification, onVoiceEvent, onConnectionState, onSessionId } = options

  const notifyConnection = (state) => {
    if (onConnectionState) onConnectionState(state)
  }

  const scheduleReconnect = () => {
    if (!shouldReconnect || reconnectTimer) return
    const resumeCapture = captureRequested
    setCaptureEnabled(false)
    captureRequested = resumeCapture
    notifyConnection('reconnecting')
    reconnectTimer = setTimeout(async () => {
      reconnectTimer = null
      if (!shouldReconnect) return
      try {
        await startPlay(lastStunServer, captureRequested)
      } catch (error) {
        if (onNotification) onNotification(`語音通道重連失敗：${error.message}`, 'error')
      }
    }, 500)
  }

  const openMicrophone = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('此瀏覽器不支援麥克風存取')
    }
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }
      })
    } catch (error) {
      if (error?.name === 'OverconstrainedError' || error?.name === 'TypeError') {
        return navigator.mediaDevices.getUserMedia({ audio: true })
      }
      throw error
    }
  }

  const sendControl = (message) => {
    if (!eventChannel || eventChannel.readyState !== 'open') return false
    eventChannel.send(JSON.stringify(message))
    return true
  }

  const setCaptureEnabled = (enabled, { finalize = false } = {}) => {
    captureRequested = Boolean(enabled)
    microphoneStream?.getAudioTracks().forEach((track) => {
      track.enabled = Boolean(enabled)
    })
    return sendControl({ type: 'capture', enabled: Boolean(enabled), finalize })
  }

  const interruptVoice = () => {
    microphoneStream?.getAudioTracks().forEach((track) => {
      track.enabled = true
    })
    return sendControl({ type: 'interrupt' })
  }

  const acknowledgeBoardDisplay = ({ turnId, boardId, itemIndex }) => {
    if (!turnId || boardId !== turnId || !Number.isInteger(itemIndex) || itemIndex < 0) {
      return false
    }
    const receiptKey = `${turnId}:${boardId}:${itemIndex}`
    if (boardDisplayReceipts.has(receiptKey)) return true
    const sent = sendControl({
      type: 'board_displayed',
      turn_id: turnId,
      board_id: boardId,
      item_index: itemIndex,
      presenter: 'console'
    })
    if (sent) boardDisplayReceipts.add(receiptKey)
    return sent
  }

  const startPlayOnce = async (stunServer = null, initialCapture = true) => {
    disposeConnection(false)
    shouldReconnect = true
    lastStunServer = stunServer
    captureRequested = Boolean(initialCapture)
    notifyConnection('preparing')
    lastEventSequence = 0

    const configuration = { iceServers: [] }
    if (stunServer) configuration.iceServers.push({ urls: stunServer })
    pc = new RTCPeerConnection(configuration)

    const remoteStream = new MediaStream()
    pc.ontrack = (event) => {
      if (!remoteStream.getTracks().some((track) => track.id === event.track.id)) {
        remoteStream.addTrack(event.track)
      }
      const video = document.getElementById('video')
      if (video) video.srcObject = remoteStream
    }

    pc.onconnectionstatechange = () => {
      const state = pc?.connectionState || 'closed'
      notifyConnection(state)
      if (state === 'failed' || state === 'disconnected') scheduleReconnect()
    }
    pc.oniceconnectionstatechange = () => {
      if (pc?.iceConnectionState === 'failed') scheduleReconnect()
    }

    eventChannel = pc.createDataChannel('voice-events', { ordered: true })
    eventChannel.onopen = () => {
      sendControl({
        type: 'capture',
        enabled: Boolean(microphoneStream) && captureRequested
      })
    }
    eventChannel.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        if (!Number.isFinite(message.seq) || message.seq <= lastEventSequence) return
        lastEventSequence = message.seq
        if (onVoiceEvent) onVoiceEvent(message)
      } catch (error) {
        console.warn('Ignored invalid voice event', error)
      }
    }
    eventChannel.onclose = () => {
      scheduleReconnect()
    }
    eventChannel.onerror = () => {
      scheduleReconnect()
    }

    try {
      microphoneStream = await openMicrophone()
      pc.addTrack(microphoneStream.getAudioTracks()[0], microphoneStream)
      microphoneStream.getAudioTracks()[0].enabled = captureRequested
    } catch (error) {
      microphoneStream = null
      pc.addTransceiver('audio', { direction: 'recvonly' })
      if (onNotification) {
        onNotification(`麥克風無法使用，已切換為文字對話：${error.message}`, 'warning')
      }
      notifyConnection('text_only')
    }
    pc.addTransceiver('video', { direction: 'recvonly' })

    try {
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      const response = await fetch('/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_role: 'console',
          sdp: pc.localDescription.sdp,
          type: pc.localDescription.type
        })
      })
      if (!response.ok) {
        let message = `HTTP ${response.status}: ${response.statusText}`
        try {
          const payload = await response.json()
          message = payload.msg || message
        } catch (_) {
          // Keep the HTTP fallback.
        }
        throw new Error(message)
      }
      const data = await response.json()
      sessionIdValue = data.sessionid
      if (onSessionId) onSessionId(sessionIdValue)
      const sessionInput = document.getElementById('sessionid')
      if (sessionInput) sessionInput.value = data.sessionid
      await pc.setRemoteDescription(new RTCSessionDescription({
        sdp: data.sdp,
        type: data.type
      }))
      return sessionIdValue
    } catch (error) {
      if (onNotification) onNotification(`WebRTC 連線失敗：${error.message}`, 'error')
      stopPlay()
      throw error
    }
  }

  const startPlay = (stunServer = null, initialCapture = true) => {
    if (startPromise) return startPromise
    const pending = startPlayOnce(stunServer, initialCapture)
    startPromise = pending
    const clearPending = () => {
      if (startPromise === pending) startPromise = null
    }
    pending.then(clearPending, clearPending)
    return pending
  }

  function disposeConnection(manual = true) {
    if (manual) {
      shouldReconnect = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventChannel) {
      eventChannel.onclose = null
      eventChannel.onerror = null
      eventChannel.close()
    }
    eventChannel = null
    if (pc) {
      pc.close()
      pc = null
    }
    microphoneStream?.getTracks().forEach((track) => track.stop())
    microphoneStream = null
    sessionIdValue = 0
    const video = document.getElementById('video')
    if (video) video.srcObject = null
    notifyConnection('closed')
  }

  function stopPlay() {
    disposeConnection(true)
  }

  return {
    startPlay,
    stopPlay,
    setCaptureEnabled,
    interruptVoice,
    acknowledgeBoardDisplay,
  }
}
