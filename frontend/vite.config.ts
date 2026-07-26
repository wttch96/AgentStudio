import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// host 明确绑定回环地址，防止开发服务器默认暴露给局域网。
export default defineConfig({
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
    // 浏览器只访问前端同源地址；代理目标仍是仅监听回环地址的 Flask。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: false,
      },
      '/health': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: false,
      },
    },
  },
})
