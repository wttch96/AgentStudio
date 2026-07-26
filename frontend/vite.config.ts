import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

function loopbackUrl(host: string, port: string) {
  const normalizedHost = host === '::1' ? '[::1]' : host
  return `http://${normalizedHost}:${port}`
}

// host 明确绑定回环地址，防止开发服务器默认暴露给局域网。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const backendHost = env.BACKEND_HOST || '127.0.0.1'
  const backendPort = env.BACKEND_PORT || '5000'
  const backendTarget = loopbackUrl(backendHost, backendPort)

  return {
    plugins: [vue()],
    build: {
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.indexOf('element-plus') >= 0 || id.indexOf('@element-plus') >= 0) return 'element-plus'
            if (id.indexOf('/marked/') >= 0) return 'markdown'
            if (id.indexOf('/vue/') >= 0 || id.indexOf('vue-router') >= 0) return 'vue'
          },
        },
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      headers: {
        'Permissions-Policy': 'local-fonts=(self)',
      },
      // 浏览器只访问前端同源地址；代理目标跟随 BACKEND_HOST/BACKEND_PORT。
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: false,
        },
        '/health': {
          target: backendTarget,
          changeOrigin: false,
        },
      },
    },
  }
})
