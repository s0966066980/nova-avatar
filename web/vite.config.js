import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'fs'
import path from 'path'
import yaml from 'js-yaml'

// 讀取配置檔案，前後端使用統一配置
// 埠 / SSL 讀預設服務配置；數字人引擎不依賴這份 yaml
// CONFIG_FILE 可為絕對路徑（啟動腳本傳入）或 config/ 下的檔名
// 正式使用由後端同源提供 web/dist；此開發伺服器預設只綁本機，僅供開發
const configFile = process.env.CONFIG_FILE || 'config.yaml'
const quietConfig = process.env.VITE_CONFIG_QUIET === '1'
const configPath = path.resolve(__dirname, '../config', configFile)
let config = null
let useSSL = false
let backendPort = 8010
let webPort = 3000
let webHost = '127.0.0.1'

try {
  if (fs.existsSync(configPath)) {
    const configContent = fs.readFileSync(configPath, 'utf8')
    config = yaml.load(configContent)
    
    // 讀取後端配置
    useSSL = config?.app?.ssl === true
    backendPort = config?.app?.listenport || 8010

    // 讀取開發伺服器配置
    webPort = config?.app?.web?.port || 3000
    webHost = config?.app?.web?.host || webHost
    
    if (!quietConfig) {
      console.log('┌─────────────────────────────────────────────┐')
      console.log('│  📡 Nova Avatar 配置載入成功                │')
      console.log('├─────────────────────────────────────────────┤')
      console.log(`│  配置檔案:  ${path.basename(configPath).padEnd(27)} │`)
      console.log(`│  SSL/HTTPS: ${useSSL ? '✅ 已啟用' : '❌ 未啟用'}                        │`)
      console.log(`│  後端地址:  ${useSSL ? 'https' : 'http'}://localhost:${backendPort}${backendPort < 10000 ? '    ' : '   '}│`)
      console.log(`│  開發伺服器: ${useSSL ? 'https' : 'http'}://${webHost}:${webPort}${webPort < 10000 ? '   ' : '  '}│`)
      console.log('└─────────────────────────────────────────────┘')
    }
  } else {
    console.warn(`⚠️  配置檔案不存在: ${configPath}`)
    console.warn('⚠️  使用預設配置 (HTTP 模式)')
  }
} catch (error) {
  console.error('⚠️  無法讀取配置檔案，使用預設值:', error.message)
}

const protocol = useSSL ? 'https' : 'http'
// 後端地址使用 localhost（前端訪問後端時）
const backendTarget = `${protocol}://localhost:${backendPort}`

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  server: {
    host: webHost,
    port: webPort,
    // 根據配置檔案自動啟用/停用 HTTPS
    ...(useSSL && command === 'serve' && {
      https: {
        key: fs.readFileSync(path.resolve(__dirname, '../ssl_certs/localhost.key')),
        cert: fs.readFileSync(path.resolve(__dirname, '../ssl_certs/localhost.crt'))
      }
    }),
    proxy: {
      // 與後端 aiohttp 路由對齊；漏掉任一路徑會讓前端打到 Vite 自己並 404
      '^/(health|human|humanaudio|asr|record|offer|interrupt_talk|is_speaking|set_audiotype|download|clear_history|api)(/|$)': {
        target: backendTarget,
        // Keep the browser's Host so the backend's Origin check sees one origin,
        // and name the real client so LAN requests are not treated as loopback.
        changeOrigin: false,
        xfwd: true,
        secure: false
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      input: { console: path.resolve(__dirname, "index.html"), stage: path.resolve(__dirname, "stage.html") },
      output: {
        manualChunks: {
          'vendor': ['vue'],
          'bootstrap': ['bootstrap']
        }
      }
    }
  }
}))
