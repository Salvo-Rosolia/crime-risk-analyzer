import js from '@eslint/js';

export default [
  // Ignore node_modules and lock file
  {
    ignores: ['node_modules/**', 'package-lock.json'],
  },

  // ── src/*.js — ES modules, browser environment, Leaflet CDN global ──────────
  {
    files: ['src/**/*.js'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        // Browser globals
        window:       'readonly',
        document:     'readonly',
        console:      'readonly',
        fetch:        'readonly',
        setTimeout:   'readonly',
        setInterval:  'readonly',
        clearInterval:'readonly',
        clearTimeout: 'readonly',
        globalThis:   'readonly',
        // Leaflet — loaded from CDN at runtime, not imported
        L:            'readonly',
      },
    },
  },

  // ── tests/*.test.js — Node environment, vitest via explicit imports ──────────
  {
    files: ['tests/**/*.test.js'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        // Node/test runner globals
        globalThis:  'readonly',
        console:     'readonly',
        process:     'readonly',
        // vitest globals are imported explicitly in every test file (no implicit globals needed)
      },
    },
  },

  // ── Config files at root (vitest.config.js etc.) ───────────────────────────
  {
    files: ['*.config.js'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        globalThis: 'readonly',
        console:    'readonly',
        process:    'readonly',
      },
    },
  },
];
