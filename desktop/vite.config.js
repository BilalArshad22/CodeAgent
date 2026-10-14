import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: './', // important for electron production build
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
});
