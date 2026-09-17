import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/documents/review-assets/',
  plugins: [vue()],
  define: {
    // TipTap and other CJS-era checks read process.env.NODE_ENV; the browser bundle has no process.
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    outDir: '../src/app/document_review/static',
    emptyOutDir: true,
    lib: {
      entry: 'src/index.ts',
      formats: ['es'],
      fileName: () => 'review.js',
    },
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        assetFileNames: (asset) =>
          asset.names.some((name) => name.endsWith('.css')) ? 'review.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
