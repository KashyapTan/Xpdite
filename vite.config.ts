import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: [
      'react-markdown',
      'remark-gfm',
      'react-syntax-highlighter',
      'react-syntax-highlighter/dist/esm/styles/prism',
      'ansi-to-html',
      '@xterm/xterm',
      '@xterm/addon-fit',
      '@xterm/addon-web-links',
    ],
    holdUntilCrawlEnd: false,
  },
  css: {
    transformer: 'lightningcss',
  },
  base: './',
  build: {
    outDir: 'dist-react'
  },
  server: {
    host: '127.0.0.1',
    port: 5123,
    strictPort: true,
    preTransformRequests: false,
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
        './src/ui/components/chat/ResponseArea.tsx',
        './src/ui/components/chat/LoadingDots.tsx',
        './src/ui/components/icons/AppIcons.tsx',
        './src/ui/components/icons/ProviderLogos.tsx',
        './src/ui/components/icons/iconPaths.ts',
        './src/ui/components/input/QueryInput.tsx',
        './src/ui/components/input/QueueDropdown.tsx',
        './src/ui/components/input/ModeSelector.tsx',
        './src/ui/components/input/TokenUsagePopup.tsx',
        './src/ui/components/input/ScreenshotChips.tsx',
      ],
    },
  }
})
