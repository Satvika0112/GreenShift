import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Playwright E2E specs live under e2e/ and use @playwright/test, not
    // vitest — excluded here so `npm test` never tries to run them (and
    // vice versa: playwright.config.ts's testDir is scoped to ./e2e only).
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
  },
});
