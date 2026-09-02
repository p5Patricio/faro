import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Separate from vite.config.ts on purpose: `tsc -b` only typechecks
// vite.config.ts (tsconfig.node.json), and this project runs the rolldown
// build of Vite, whose plugin types clash with vitest's bundled Vite.
export default defineConfig({
  envDir: '..',
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
