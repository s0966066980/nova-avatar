// Derived from Kedreamix/Linly-Talker-Stream.
// Copyright [Linly-talker-stream@kedreamix].
// Licensed under the Apache License, Version 2.0.
//
// Modified by HongXian0903, 2026.
// See LICENSE and NOTICE for details.
import { ref } from 'vue'

export function useSpeechRecognition(options = {}) {
  const {
    onResult = () => {},
    onFinalResult = () => {},
    onError = () => {},
    language = 'zh-TW',
    continuous = true
  } = options
  
  const isSupported = ref(
    'webkitSpeechRecognition' in window || 'SpeechRecognition' in window
  )
  
  let recognition = null
  let isRecognizing = false
  let shouldContinue = false
  
  if (isSupported.value) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    recognition = new SpeechRecognition()
    
    recognition.continuous = continuous
    recognition.interimResults = true
    recognition.lang = language
    
    recognition.onresult = (event) => {
      let interimTranscript = ''
      let finalTranscript = ''
      
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const transcript = event.results[i][0].transcript
        
        if (event.results[i].isFinal) {
          finalTranscript += transcript
        } else {
          interimTranscript += transcript
        }
      }
      
      if (interimTranscript) {
        onResult(interimTranscript)
      }
      
      if (finalTranscript) {
        onFinalResult(finalTranscript)
      }
    }
    
    recognition.onerror = (event) => {
      console.error('語音識別錯誤:', event.error)
      
      // no-speech 錯誤在連續模式下很常見，不需要特別處理
      if (event.error === 'no-speech' && shouldContinue) {
        console.log('未檢測到語音，繼續監聽...')
        return
      }
      
      onError(event.error)
    }
    
    recognition.onend = () => {
      isRecognizing = false
      console.log('語音識別結束，shouldContinue:', shouldContinue)
      
      // 在連續模式下，如果標誌為 true，則自動重啟識別
      if (shouldContinue) {
        console.log('連續模式：自動重啟語音識別')
        setTimeout(() => {
          if (shouldContinue && !isRecognizing) {
            try {
              recognition.start()
              isRecognizing = true
            } catch (error) {
              console.error('重啟語音識別失敗:', error)
            }
          }
        }, 100)
      }
    }
  }
  
  const startRecognition = () => {
    if (recognition && !isRecognizing) {
      try {
        shouldContinue = true
        recognition.start()
        isRecognizing = true
        console.log('啟動語音識別，連續模式:', recognition.continuous)
      } catch (error) {
        console.error('啟動語音識別失敗:', error)
      }
    }
  }
  
  const stopRecognition = () => {
    if (recognition) {
      try {
        shouldContinue = false
        if (isRecognizing) {
          recognition.stop()
        }
        console.log('停止語音識別')
      } catch (error) {
        console.error('停止語音識別失敗:', error)
      }
    }
  }
  
  const updateSettings = (settings) => {
    if (recognition) {
      recognition.lang = settings.language || 'zh-TW'
      recognition.continuous = settings.continuous !== undefined ? settings.continuous : true
    }
  }
  
  return {
    isSupported: isSupported.value,
    startRecognition,
    stopRecognition,
    updateSettings
  }
}
