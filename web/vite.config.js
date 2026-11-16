import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import yaml from 'js-yaml'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

function resolveConfigPath(configFile) {
  if (path.isAbsolute(configFile)) {
    return configFile
  }
  const inConfigDir = path.resolve(__dirname, '../config', configFile)
  if (fs.existsSync(inConfigDir)) {
    return inConfigDir
  }
  return path.resolve(repoRoot, configFile)
}

export function createViteConfig({ command = 'serve', env = process.env } = {}) {
  // 讀取配置檔案，前後端使用統一配置
  // 埠 / SSL 讀預設服務配置；數字人引擎不依賴這份 yaml
  const configFile = env.CONFIG_FILE || 'config.yaml'
  const quietConfig = env.VITE_CONFIG_QUIET === '1'
  const configPath = resolveConfigPath(configFile)
  let config = null
  let useSSL = false
  let backendPort = 8010
  let backendHost = 'localhost'
  let webPort = 3000
  let webHost = '0.0.0.0'
  let sslCertRel = 'ssl_certs/localhost.crt'
  let sslKeyRel = 'ssl_certs/localhost.key'

  try {
    if (fs.existsSync(configPath)) {
      const configContent = fs.readFileSync(configPath, 'utf8')
      config = yaml.load(configContent)

      // 讀取後端配置
      useSSL = config?.app?.ssl === true
      backendPort = config?.app?.listenport || 8010
      backendHost = config?.app?.listenhost || '0.0.0.0'
      sslCertRel = config?.app?.ssl_cert || sslCertRel
      sslKeyRel = config?.app?.ssl_key || sslKeyRel

      // 讀取前端配置
      webPort = config?.app?.web?.port || 3000
      webHost = config?.app?.web?.host || '0.0.0.0'

      if (!quietConfig) {
        console.log('┌─────────────────────────────────────────────┐')
        console.log('│  📡 Nova Avatar 配置載入成功                │')
        console.log('├─────────────────────────────────────────────┤')
        console.log(`│  配置檔案:  ${configFile.padEnd(27)} │`)
        console.log(`│  SSL/HTTPS: ${useSSL ? '✅ 已啟用' : '❌ 未啟用'}                        │`)
        console.log(`│  後端地址:  ${useSSL ? 'https' : 'http'}://${backendHost === '0.0.0.0' ? 'localhost' : backendHost}:${backendPort}${backendPort < 10000 ? '    ' : '   '}│`)
        console.log(`│  前端地址:  ${useSSL ? 'https' : 'http'}://${webHost === '0.0.0.0' ? 'localhost' : webHost}:${webPort}${webPort < 10000 ? '    ' : '   '}│`)
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
  const sslCertPath = path.resolve(repoRoot, sslCertRel)
  const sslKeyPath = path.resolve(repoRoot, sslKeyRel)

  return {
    plugins: [vue()],
    server: {
      host: webHost,
      port: webPort,
      // 根據配置檔案自動啟用/停用 HTTPS（僅 dev/preview 讀取憑證）
      ...(useSSL && command === 'serve' && {
        https: {
          key: fs.readFileSync(sslKeyPath),
          cert: fs.readFileSync(sslCertPath)
        }
      }),
      proxy: {
        // 與後端 aiohttp 路由對齊；漏掉任一路徑會讓前端打到 Vite 自己並 404
        '^/(health|human|humanaudio|asr|record|offer|interrupt_talk|is_speaking|set_audiotype|download|clear_history|api)(/|$)': {
          target: backendTarget,
          changeOrigin: true,
          secure: false
        }
      }
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      rollupOptions: {
        input: { console: path.resolve(__dirname, 'index.html'), stage: path.resolve(__dirname, 'stage.html') },
        output: {
          manualChunks: {
            'vendor': ['vue'],
            'bootstrap': ['bootstrap']
          }
        }
      }
    }
  }
}

// 保持 page-routing.test.js 檢查 `process.env.VITE_CONFIG_QUIET` 的參考
export default defineConfig(({ command }) => createViteConfig({ command, env: process.env }))
