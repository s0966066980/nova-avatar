// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import { PresentationTimeline, decodeClock, audioPlayoutOffset } from './prerecordedTimeline.js'

const players = new WeakMap()
export const presentationPlayer = (video) => players.get(video)

export async function presentationRequest(url, options = {}) {
  const response = await fetch(url, options)
  const result = await response.json()
  if (!response.ok || result.code !== 0) throw new Error(result.msg || `HTTP ${response.status}`)
  return result.data
}

export async function waitPresentationJob(job, onProgress = () => {}) {
  for (;;) {
    const current = await presentationRequest(`/api/presentation/jobs/${job.id}`)
    onProgress(current)
    if (current.status === 'done') return current.result
    if (['failed', 'cancelled'].includes(current.status)) throw new Error(current.error || '工作中斷')
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
}

function loadVideo(url) {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video')
    video.muted = true
    video.loop = true
    video.playsInline = true
    video.preload = 'auto'
    const timeout = setTimeout(() => reject(new Error('影片載入逾時')), 30000)
    video.onloadeddata = () => { clearTimeout(timeout); resolve(video) }
    video.onerror = () => { clearTimeout(timeout); reject(new Error('影片無法播放，請修復素材')) }
    video.src = url
  })
}

const vertex = `attribute vec2 p;varying vec2 uv;void main(){uv=(p+1.)/2.;gl_Position=vec4(p,0.,1.);}`
const fragment = `precision mediump float;
varying vec2 uv;uniform sampler2D a;uniform sampler2D b;uniform sampler2D bg;
uniform float blend;uniform vec2 bgScale;
vec4 key(vec4 c){float d=c.g-max(c.r,c.b);float alpha=1.-smoothstep(.08,.24,d);
c.g=min(c.g,max(c.r,c.b)+.08);return vec4(c.rgb*alpha,alpha);}
void main(){vec4 foreground=mix(key(texture2D(a,uv)),key(texture2D(b,uv)),blend);
vec3 background=texture2D(bg,(uv-.5)*bgScale+.5).rgb;
gl_FragColor=vec4(foreground.rgb+background*(1.-foreground.a),1.);}`

function shader(gl, kind, source) {
  const result = gl.createShader(kind)
  gl.shaderSource(result, source)
  gl.compileShader(result)
  if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) throw new Error('此裝置無法建立去背畫面')
  return result
}

export class PrerecordedPlayer {
  constructor(remote, settings, onError = () => {}, peerConnection = null) {
    this.remote = remote
    this.settings = settings
    this.onError = onError
    this.peerConnection = peerConnection
    this.clockOffset = null
    this.timeline = new PresentationTimeline()
    this.canvas = document.createElement('canvas')
    this.canvas.className = 'prerecorded-player'
    this.canvas.setAttribute('aria-label', '預錄數位人與舞台背景')
    this.canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;pointer-events:none;z-index:2;'
    this.remoteOpacity = remote.style.opacity
    this.remoteVisibility = remote.style.visibility
    remote.style.opacity = '0'
    remote.style.visibility = 'hidden'
    remote.insertAdjacentElement('afterend', this.canvas)
    this.clock = document.createElement('canvas')
    this.clock.width = 64
    this.clock.height = 32
    this.clockContext = this.clock.getContext('2d', { willReadFrequently: true })
    this.disposed = false
    this.videos = {}
    this.state = 'idle'
    this.mediaMs = 0
    this.lastClock = -1
    this.metrics = { frames: 0, maxFrameGapMs: 0, transitions: [], clockFrames: 0, startedAt: 0 }
  }

  async start() {
    try {
      const gl = this.canvas.getContext('webgl', { alpha: false, antialias: false, preserveDrawingBuffer: false })
      if (!gl) throw new Error('瀏覽器不支援影片去背，請使用支援 WebGL 的瀏覽器')
      this.gl = gl
      const program = gl.createProgram()
      this.shaders = [shader(gl, gl.VERTEX_SHADER, vertex), shader(gl, gl.FRAGMENT_SHADER, fragment)]
      this.shaders.forEach((item) => gl.attachShader(program, item))
      gl.linkProgram(program)
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('去背畫面初始化失敗')
      gl.useProgram(program)
      this.program = program
      this.buffer = gl.createBuffer()
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer)
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW)
      const location = gl.getAttribLocation(program, 'p')
      gl.enableVertexAttribArray(location)
      gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0)
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true)
      this.textures = ['a', 'b', 'bg'].map((name, index) => {
        const texture = gl.createTexture()
        gl.activeTexture(gl.TEXTURE0 + index)
        gl.bindTexture(gl.TEXTURE_2D, texture)
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([12,16,24,255]))
        gl.uniform1i(gl.getUniformLocation(program, name), index)
        return texture
      })
      this.blendLocation = gl.getUniformLocation(program, 'blend')
      this.bgScaleLocation = gl.getUniformLocation(program, 'bgScale')
      const loaded = await Promise.all(['idle', 'talking'].map(async (slot) => {
        const metadata = this.settings.slots[slot].current
        const video = await loadVideo(metadata.url)
        video.onerror = () => this.fail(new Error(`${slot === 'idle' ? '待機' : '說話'}影片播放失敗`))
        return [slot, video]
      }))
      if (this.disposed) { loaded.forEach(([, video]) => this.releaseVideo(video)); return }
      this.videos = Object.fromEntries(loaded)
      const info = this.settings.slots.idle.current
      const height = info.height
      this.canvas.height = height - height % 2
      this.canvas.width = Math.round(info.width * this.canvas.height / info.height / 2) * 2
      gl.viewport(0, 0, this.canvas.width, this.canvas.height)
      await this.setBackground(this.settings.background)
      if (this.disposed) return
      await this.videos.idle.play()
      if (this.disposed) return
      this.canvas.addEventListener('webglcontextlost', (event) => { event.preventDefault(); this.fail(new Error('畫面資源中斷，請重新連線')) })
      this.metrics.startedAt = performance.now()
      this.tick = (now) => {
        if (this.disposed) return
        this.raf = requestAnimationFrame(this.tick)
        this.nextDraw ??= now
        if (now < this.nextDraw) return
        this.nextDraw = Math.max(this.nextDraw + 40, now)
        if (this.lastDraw) this.metrics.maxFrameGapMs = Math.max(this.metrics.maxFrameGapMs, now - this.lastDraw)
        this.lastDraw = now
        try {
          if (this.remote.readyState >= 2 && this.remote.videoWidth === 64) {
            this.clockContext.drawImage(this.remote, 0, 0, 64, 32)
            const clock = decodeClock(this.clockContext.getImageData(0, 0, 64, 32).data)
            if (clock !== null) {
              if (this.lastRawClock !== undefined && this.lastRawClock - clock > 0x800000) this.clockEpoch = (this.clockEpoch || 0) + 0x1000000
              this.lastRawClock = clock
              const milliseconds = clock + (this.clockEpoch || 0)
              if (milliseconds > this.lastClock) this.metrics.clockFrames++
              this.lastClock = this.videoMediaMs = Math.max(this.lastClock, milliseconds)
            }
          }
          if (this.clockOffset !== null) this.mediaMs = Math.max(0, (this.videoMediaMs || 0) + this.clockOffset)
          if (this.clockUpdatedAt && now - this.clockUpdatedAt > 3000) {
            this.clockOffset = null
            this.waitForClock('語音時鐘暫時中斷；待機畫面繼續播放，時鐘恢復後會繼續說話。')
          }
          this.setState(this.previewState || (this.errorReported || this.clockOffset === null ? 'idle' : this.timeline.advance(this.mediaMs)), now)
          this.draw(now)
          this.recordVideoTrack?.requestFrame?.()
          this.metrics.frames++
        } catch (error) { this.fail(error) }
      }
      this.raf = requestAnimationFrame(this.tick)
      if (this.peerConnection) void this.prepareClock().catch((error) => this.fail(error))
      if (this.disposed) return
      this.poll = setInterval(async () => {
        try {
          const current = await presentationRequest(`/api/presentation/${this.settings.avatar_id}`)
          if (this.disposed) return
          if (current.background?.id !== this.backgroundId) await this.setBackground(current.background)
        } catch (error) { this.onError(error.message) }
      }, 2000)
    } catch (error) { this.fail(error) }
  }

  receive(event) { this.timeline.receive(event) }

  async prepareClock() {
    const sample = async () => {
      if (this.disposed || this.clockPolling) return
      this.clockPolling = true
      try {
        const offset = audioPlayoutOffset((await this.peerConnection.getStats()).values())
        if (offset !== null && !this.disposed) {
          this.clockOffset = offset
          this.clockUpdatedAt = performance.now()
          this.clockWarning = false
        }
      } finally { this.clockPolling = false }
    }
    this.clockPoll = setInterval(() => { sample().catch(() => {}) }, 100)
    await sample().catch(() => {})
    const started = performance.now()
    while (!this.disposed && this.clockOffset === null && performance.now() - started < 10000) {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    if (!this.disposed && this.clockOffset === null) {
      this.waitForClock('正在等待語音時鐘；待機畫面繼續播放，完成校準後即可說話與錄影。')
    }
  }

  waitForClock(message) {
    if (this.clockWarning || this.disposed) return
    this.clockWarning = true
    this.onError(message)
  }

  setState(state, now) {
    if (state === this.state || !this.videos[state]) return
    this.previous = this.state
    this.state = state
    this.transitionAt = now
    this.videos[state].play().catch((error) => this.fail(error))
    this.metrics.transitions.push({ state, mediaMs: this.mediaMs, at: now })
    if (this.metrics.transitions.length > 1000) this.metrics.transitions.shift()
  }

  async setBackground(metadata) {
    const identity = metadata?.id
    this.backgroundId = identity
    let candidate = null
    if (metadata) {
      if (metadata.kind === 'video') { candidate = await loadVideo(metadata.url); await candidate.play() }
      else candidate = await new Promise((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('舞台背景載入失敗'))
        image.src = metadata.url
      })
    }
    if (this.disposed || this.backgroundId !== identity) { if (candidate?.pause) this.releaseVideo(candidate); return }
    if (this.background?.pause) this.releaseVideo(this.background)
    this.background = candidate
  }

  texture(index, image) {
    const gl = this.gl
    gl.activeTexture(gl.TEXTURE0 + index)
    gl.bindTexture(gl.TEXTURE_2D, this.textures[index])
    if (image && (image.readyState === undefined || image.readyState >= 2)) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image)
    } else if (index === 2) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([12,16,24,255]))
    }
  }

  draw(now) {
    const amount = this.previous ? Math.min(1, (now - this.transitionAt) / 100) : 1
    this.texture(0, this.videos[this.previous || this.state])
    if (this.previous) this.texture(1, this.videos[this.state])
    this.gl.uniform1i(this.gl.getUniformLocation(this.program, 'b'), this.previous ? 1 : 0)
    this.texture(2, this.background)
    const backgroundRatio = this.background ? (this.background.videoWidth || this.background.naturalWidth) / (this.background.videoHeight || this.background.naturalHeight) : 1
    const ratio = this.canvas.width / this.canvas.height
    this.gl.uniform2f(this.bgScaleLocation, Math.min(1, ratio / backgroundRatio), Math.min(1, backgroundRatio / ratio))
    this.gl.uniform1f(this.blendLocation, amount)
    this.gl.drawArrays(this.gl.TRIANGLE_STRIP, 0, 4)
    if (amount === 1 && this.previous) { this.videos[this.previous].pause(); this.previous = null }
  }

  fail(error) {
    if (this.disposed) return
    if (!this.errorReported) this.onError(error.message || String(error))
    this.errorReported = true
    this.timeline.reset()
    if (this.videos.idle?.readyState >= 2 && this.gl && !this.gl.isContextLost()) {
      this.setState('idle', performance.now())
    } else {
      if (!this.fallback) {
        this.fallback = new Image()
        this.fallback.alt = '素材播放失敗，顯示數位人預覽'
        this.fallback.style.cssText = this.canvas.style.cssText
        this.fallback.src = `/api/avatars/${this.settings.avatar_id}/scene-preview`
        this.canvas.insertAdjacentElement('afterend', this.fallback)
      }
    }
  }

  startRecording(onFinished) {
    if (this.recorder || this.disposed || !this.gl || this.errorReported) throw new Error('目前畫面不能開始錄影')
    if (document.visibilityState !== 'visible') throw new Error('錄影頁面必須保持在前景')
    if (this.peerConnection && this.clockOffset === null) throw new Error('正在準備語音播放時鐘，請稍候')
    let stream = this.canvas.captureStream(0)
    if (!stream.getVideoTracks()[0]?.requestFrame) {
      stream.getTracks().forEach((track) => track.stop())
      stream = this.canvas.captureStream(25)
    }
    const audio = this.remote.srcObject?.getAudioTracks()[0]
    if (!audio) { stream.getTracks().forEach((track) => track.stop()); throw new Error('回答音軌尚未就緒') }
    stream.addTrack(audio.clone())
    const mimeType = ['video/mp4;codecs=avc1.42001E,mp4a.40.2', 'video/mp4;codecs=avc1.42E01E,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'].find((type) => MediaRecorder.isTypeSupported(type))
    if (!mimeType) { stream.getTracks().forEach((track) => track.stop()); throw new Error('此瀏覽器不支援場景錄影') }
    let recorder
    try { recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 6000000 }) }
    catch (error) { stream.getTracks().forEach((track) => track.stop()); throw error }
    const chunks = []
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop())
      document.removeEventListener('visibilitychange', visibility)
      this.recorder = null
      this.recordVideoTrack = null
      onFinished(new Blob(chunks, { type: recorder.mimeType }))
    }
    const visibility = () => {
      if (document.visibilityState !== 'visible') { this.onError('頁面離開前景，已停止並保存這次錄影'); this.stopRecording() }
    }
    document.addEventListener('visibilitychange', visibility)
    try { recorder.start(1000); this.recorder = recorder; this.recordVideoTrack = stream.getVideoTracks()[0] }
    catch (error) {
      document.removeEventListener('visibilitychange', visibility)
      stream.getTracks().forEach((track) => track.stop())
      throw error
    }
  }

  stopRecording() { if (this.recorder?.state !== 'inactive') this.recorder?.stop() }

  releaseVideo(video) { video.pause(); video.removeAttribute('src'); video.load() }

  dispose() {
    this.stopRecording()
    this.disposed = true
    cancelAnimationFrame(this.raf)
    clearInterval(this.poll)
    clearInterval(this.clockPoll)
    this.timeline.reset()
    Object.values(this.videos).forEach((video) => this.releaseVideo(video))
    if (this.background?.pause) this.releaseVideo(this.background)
    this.textures?.forEach((texture) => this.gl.deleteTexture(texture))
    this.shaders?.forEach((item) => this.gl.deleteShader(item))
    if (this.buffer) this.gl.deleteBuffer(this.buffer)
    if (this.program) this.gl.deleteProgram(this.program)
    this.canvas.remove()
    this.remote.style.opacity = this.remoteOpacity
    this.remote.style.visibility = this.remoteVisibility
    this.fallback?.remove()
    if (players.get(this.remote) === this) players.delete(this.remote)
  }
}

export async function mountPresentation(remote, settings, onError, peerConnection = null) {
  players.get(remote)?.dispose()
  if (settings?.mode !== 'prerecorded') return null
  const player = new PrerecordedPlayer(remote, settings, onError, peerConnection)
  players.set(remote, player)
  await player.start()
  return player
}

export async function exportSceneRecording(blob, onProgress) {
  const form = new FormData()
  form.append('file', blob, blob.type.includes('mp4') ? 'scene.mp4' : 'scene.webm')
  const job = await presentationRequest('/api/presentation/records', { method: 'POST', body: form })
  return waitPresentationJob(job, onProgress)
}
