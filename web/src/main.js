// Derived from Kedreamix/Linly-Talker-Stream.
// Copyright [Linly-talker-stream@kedreamix].
// Licensed under the Apache License, Version 2.0.
//
// Modified by HongXian0903, 2026.
// See LICENSE and NOTICE for details.
import { createApp } from 'vue'
import ConsoleRoot from './ConsoleRoot.vue'
import { installSessionExpiry } from './adminSession.js'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
import './console-prototype.css'

installSessionExpiry()
createApp(ConsoleRoot).mount('#app')
