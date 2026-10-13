// Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
// Modified by HongXian0903, 2026. See LICENSE and NOTICE.

import { newClientId, releaseSession, avatarIsReady } from '../sessionTransport.js'
import { configureReplyPlayout } from '../replyPlayout.js'
import { mountPresentation, presentationPlayer } from '../prerecordedPlayer.js'

// One peer connection carries avatar A/V, the microphone uplink and voice events.
export function useWebRTC(options = {}) {
  const clientId = newClientId()
  let generation = 0
  let releasePromise = Promise.resolve()
  let pc = null
  let eventChannel = null
  let microphoneStream = null
  let sessionIdValue = 0
  let lastEventSequence = 0
  // A connection must never begin transmitting microphone audio by default.
  // The console's microphone control is the explicit user consent boundary.
  let captureRequested = false
  let reconnectTimer = null
  let shouldReconnect = false
  let lastStunServer = null
  let startPromise = null
  let playbackState = null
  const boardDisplayReceipts = new Set()
  const { onNotification, onVoiceEvent, onConnectionState, onSessionId, onPlaybackState } = options

  const notifyConnection = (state) => {
    if (onConnectionState) onConnectionState(state)
  }

  const notifyPlayback = (state) => {
    if (playbackState === state) return
    playbackState = state
    if (onPlaybackState) onPlaybackState(state)
  }

  // Call directly from a click handler so browsers can authorize sound using
  // that user gesture. Automatic attempts report when a click is required.
  const resumePlayback = async () => {
    const video = document.getElementById('video')
    const stream = video?.srcObject
    if (!stream || !video.play) return false
    video.muted = false
    if (video.volume === 0) video.volume = 1
    try {
      await video.play()
      if (video.srcObject !== stream) return false
      notifyPlayback(video.paused ? 'blocked' : 'playing')
      return !video.paused
    } catch (error) {
      // A superseded connection must not change the new player's state.
      if (video.srcObject !== stream) return false
      notifyPlayback('blocked')
      if (error?.name !== 'NotAllowedError' && error?.name !== 'AbortError' && onNotification) {
        onNotification(`語音播放失敗：${error.message}`, 'error')
      }
      return false
    }
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
      if (!(await avatarIsReady())) { scheduleReconnect(); return }
      try {
        await startPlay(lastStunServer, captureRequested)
      } catch (error) {
        if (onNotification) onNotification(`語音通道重連失敗：${error.message}`, 'error')
        if (shouldReconnect) scheduleReconnect()
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
    setCaptureEnabled(true)
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

  const startPlayOnce = async (stunServer = null, initialCapture = false) => {
    disposeConnection(false)
    shouldReconnect = true
    lastStunServer = stunServer
    captureRequested = Boolean(initialCapture)
    notifyConnection('preparing')
    lastEventSequence = 0

    const configuration = { iceServers: [] }
    if (stunServer) configuration.iceServers.push({ urls: stunServer })
    const peer = new RTCPeerConnection(configuration)
    pc = peer
    const attempt = generation
    const isCurrent = () => pc === peer && generation === attempt
    const checkCurrent = () => { if (!isCurrent()) throw new DOMException('連線已取消', 'AbortError') }

    const remoteStream = new MediaStream()
    const video = document.getElementById('video')
    if (video) {
      // Keep one media pipeline as audio and video tracks arrive separately.
      video.srcObject = remoteStream
      const updatePlayback = () => {
        if (video.srcObject !== remoteStream || !remoteStream.getTracks().length) return
        notifyPlayback(video.paused || video.muted || video.volume === 0 ? 'blocked' : 'playing')
      }
      video.onplaying = updatePlayback
      video.onpause = updatePlayback
      video.onvolumechange = updatePlayback
    }
    pc.ontrack = (event) => {
      if (!isCurrent()) return
      configureReplyPlayout(event)
      if (!remoteStream.getTracks().some((track) => track.id === event.track.id)) {
        remoteStream.addTrack(event.track)
      }
      void resumePlayback()
    }

    pc.onconnectionstatechange = () => {
      if (!isCurrent()) return
      const state = peer.connectionState || 'closed'
      notifyConnection(state)
      if (state === 'failed' || state === 'disconnected') scheduleReconnect()
    }
    pc.oniceconnectionstatechange = () => {
      if (isCurrent() && peer.iceConnectionState === 'failed') scheduleReconnect()
    }

    eventChannel = pc.createDataChannel('voice-events', { ordered: true })
    eventChannel.onopen = () => {
      if (!isCurrent()) return
      sendControl({
        type: 'capture',
        enabled: Boolean(microphoneStream) && captureRequested
      })
    }
    eventChannel.onmessage = (event) => {
      if (!isCurrent()) return
      try {
        const message = JSON.parse(event.data)
        if (!Number.isFinite(message.seq) || message.seq <= lastEventSequence) return
        lastEventSequence = message.seq
        if (message.type === 'presentation_changing') { scheduleReconnect(); return }
        presentationPlayer(document.getElementById('video'))?.receive(message)
        if (onVoiceEvent) onVoiceEvent(message)
      } catch (error) {
        console.warn('Ignored invalid voice event', error)
      }
    }
    eventChannel.onclose = () => {
      if (isCurrent()) scheduleReconnect()
    }
    eventChannel.onerror = () => {
      if (isCurrent()) scheduleReconnect()
    }

    try {
      const microphone = await openMicrophone()
      if (!isCurrent()) { microphone.getTracks().forEach((track) => track.stop()); checkCurrent() }
      microphoneStream = microphone
      pc.addTrack(microphoneStream.getAudioTracks()[0], microphoneStream)
      microphoneStream.getAudioTracks()[0].enabled = captureRequested
    } catch (error) {
      checkCurrent()
      microphoneStream = null
      pc.addTransceiver('audio', { direction: 'recvonly' })
      if (onNotification) {
        onNotification(`麥克風無法使用，已切換為文字對話：${error.message}`, 'warning')
      }
      notifyConnection('text_only')
    }
    pc.addTransceiver('video', { direction: 'recvonly' })

    try {
      await releasePromise
      checkCurrent()
      const offer = await peer.createOffer()
      checkCurrent()
      await peer.setLocalDescription(offer)
      checkCurrent()
      const response = await fetch('/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_role: 'console', client_id: clientId, stun_server: stunServer,
          sdp: peer.localDescription.sdp,
          type: peer.localDescription.type
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
        const error = new Error(message)
        error.retryable = [409, 429, 503].includes(response.status)
        throw error
      }
      const data = await response.json()
      if (!isCurrent()) { await releaseSession(data.sessionid, clientId); checkCurrent() }
      sessionIdValue = data.sessionid
      if (onSessionId) onSessionId(sessionIdValue)
      const sessionInput = document.getElementById('sessionid')
      if (sessionInput) sessionInput.value = data.sessionid
      await peer.setRemoteDescription(new RTCSessionDescription({
        sdp: data.sdp,
        type: data.type
      }))
      checkCurrent()
      if (video) await mountPresentation(video, data.presentation, (message) => { if(isCurrent()) onNotification?.(message, 'error') }, peer)
      checkCurrent()
      return sessionIdValue
    } catch (error) {
      if (isCurrent()) {
        if (onNotification) onNotification(`WebRTC 連線失敗：${error.message}`, 'error')
        disposeConnection(false)
        if (error.retryable && shouldReconnect) scheduleReconnect()
      }
      throw error
    }
  }

  const startPlay = (stunServer = null, initialCapture = false) => {
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
    generation += 1
    if (sessionIdValue) releasePromise = releaseSession(sessionIdValue, clientId)
    presentationPlayer(document.getElementById('video'))?.dispose()
    if (manual) {
      startPromise = null
      shouldReconnect = false
      if (reconnectTimer) clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventChannel) {
      eventChannel.onopen = null
      eventChannel.onmessage = null
      eventChannel.onclose = null
      eventChannel.onerror = null
      eventChannel.close()
    }
    eventChannel = null
    if (pc) {
      pc.ontrack = null
      pc.onconnectionstatechange = null
      pc.oniceconnectionstatechange = null
      pc.close()
      pc = null
    }
    microphoneStream?.getTracks().forEach((track) => track.stop())
    microphoneStream = null
    sessionIdValue = 0
    onSessionId?.(0)
    const video = document.getElementById('video')
    if (video) {
      video.onplaying = null
      video.onpause = null
      video.onvolumechange = null
      video.srcObject = null
    }
    notifyPlayback('idle')
    notifyConnection('closed')
  }

  function stopPlay() {
    disposeConnection(true)
  }

  // Vue unmount does not run when an entire browser tab is closed/refreshed.
  globalThis.addEventListener?.('pagehide', stopPlay)

  return {
    startPlay,
    stopPlay,
    resumePlayback,
    setCaptureEnabled,
    interruptVoice,
    acknowledgeBoardDisplay,
  }
}
