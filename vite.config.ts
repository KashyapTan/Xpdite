import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: [
      'react-router-dom',
      'style-to-js',
      'style-to-js/cjs/index.js',
      'style-to-object',
    ],
    holdUntilCrawlEnd: false,
  },
  css: {
    transformer: 'lightningcss',
  },
  base: './',
  build: {
    outDir: 'dist-react',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('vite/preload-helper')) {
            return 'vite-preload-helper'
          }

          if (!id.includes('node_modules')) {
            return undefined
          }

          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) {
            return 'vendor-react'
          }

          if (/[\\/]node_modules[\\/](react-markdown|remark-[^\\/]+|rehype-[^\\/]+|unified|micromark[^\\/]*|mdast-[^\\/]+|hast-[^\\/]+|hastscript|unist-[^\\/]+|vfile[^\\/]*|zwitch|decode-named-character-reference|character-entities[^\\/]*|trim-lines|devlop|bail|ccount|escape-string-regexp|markdown-table|comma-separated-tokens|space-separated-tokens|property-information|style-to-object|style-to-js|inline-style-parser|html-url-attributes|estree-util-is-identifier-name|entities|@ungap[\\/]structured-clone|extend|is-plain-obj|trough|xtend)[\\/]/.test(id)) {
            return 'vendor-markdown'
          }

          if (id.includes('react-syntax-highlighter') || id.includes('refractor') || id.includes('prismjs')) {
            return 'vendor-syntax'
          }

          if (id.includes('@xterm') || id.includes('ansi-to-html')) {
            return 'vendor-terminal'
          }

          if (id.includes('@chenglou/pretext')) {
            return 'vendor-editor'
          }

          if (id.includes('chat-adapter') || id.includes('baileys') || id.includes('@chat-adapter')) {
            return 'vendor-channels'
          }

          return 'vendor'
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5123,
    strictPort: true,
    preTransformRequests: true,
    watch: {
      ignored: [
        '**/user_data/**',
        '**/codex-temp/**',
        '**/.tmp*/**',
      ],
    },
    warmup: {
      clientFiles: [
        './index.html',
        './src/ui/main.tsx',
        './src/ui/components/Layout.tsx',
        './src/ui/components/boot/BootScreen.tsx',
        './src/ui/components/MobilePlatformBadge.tsx',
        './src/ui/contexts/BootContext.tsx',
        './src/ui/contexts/TabContext.tsx',
        './src/ui/contexts/WebSocketContext.tsx',
        './src/ui/hooks/useChatState.ts',
        './src/ui/hooks/useScreenshots.ts',
        './src/ui/hooks/useTokenUsage.ts',
        './src/ui/pages/App.tsx',
        './src/ui/utils/modelDisplay.ts',
        './src/ui/utils/providerLogos.ts',
        './src/ui/utils/renderableContentBlocks.ts',
        './src/ui/components/TitleBar.tsx',
        './src/ui/components/TabBar.tsx',
        './src/ui/components/icons/AppIcons.tsx',
        './src/ui/components/icons/ProviderLogos.tsx',
        './src/ui/components/icons/iconPaths.ts',
        './src/ui/components/input/QueryInput.tsx',
        './src/ui/components/input/QueueDropdown.tsx',
        './src/ui/components/input/ModeSelector.tsx',
        './src/ui/components/input/TokenUsagePopup.tsx',
        './src/ui/components/input/ScreenshotChips.tsx',
        './src/ui/pages/Settings.tsx',
        './src/ui/pages/ChatHistory.tsx',
        './src/ui/components/settings/SettingsModels.tsx',
      ],
    },
  }
})
