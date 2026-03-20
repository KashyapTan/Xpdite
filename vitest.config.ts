import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/ui/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/ui/**/*.{ts,tsx}'],
      exclude: [
        'src/ui/**/*.test.{ts,tsx}',
        'src/ui/test/**',
        'src/ui/vite-env.d.ts',
        'src/ui/main.tsx',
      ],
    },
  },
})
