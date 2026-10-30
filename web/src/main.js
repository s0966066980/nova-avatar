// Derived from Kedreamix/Linly-Talker-Stream.
// Copyright [Linly-talker-stream@kedreamix].
// Licensed under the Apache License, Version 2.0.
//
// Modified by HongXian0903, 2026.
// See LICENSE and NOTICE for details.
import { createApp } from 'vue'
import ConsoleRoot from './ConsoleRoot.vue'
import { installSessionExpiry } from './adminSession.js'
import { applyThemePreference, readThemePreference } from './consoleTheme.js'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
// 樣式與圖示字型由 npm 套件打包，場域斷網時仍可顯示。
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-icons/font/bootstrap-icons.min.css'
import '@fontsource/plus-jakarta-sans/latin-400.css'
import '@fontsource/plus-jakarta-sans/latin-500.css'
import '@fontsource/plus-jakarta-sans/latin-600.css'
import '@fontsource/plus-jakarta-sans/latin-700.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import './console-prototype.css'

// 在掛載前套用主題，登入頁與控制台第一個畫面就是使用者選的配色。
applyThemePreference(readThemePreference(globalThis.localStorage))
installSessionExpiry()
createApp(ConsoleRoot).mount('#app')
