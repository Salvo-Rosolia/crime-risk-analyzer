module.exports = {
  preset: 'jest-preset-angular',
  setupFilesAfterEnv: ['<rootDir>/setup-jest.ts'],
  testPathIgnorePatterns: ['<rootDir>/node_modules/', '<rootDir>/e2e/'],
  moduleNameMapper: {
    '^@core/(.*)$': '<rootDir>/src/app/core/$1',
    '^@features/(.*)$': '<rootDir>/src/app/features/$1',
    '^@app/(.*)$': '<rootDir>/src/app/$1',
    '^@environments/(.*)$': '<rootDir>/src/environments/$1',
  },
  // Misura TUTTO il sorgente reale, non solo i file importati dai test (altrimenti
  // un file mai testato semplicemente non comparirebbe nel report, gonfiando la
  // percentuale). `app.config.ts` (bootstrap/DI, zero logica) resta escluso apposta:
  // niente spec triviali. `main.ts` è già fuori da `src/app/**` (#118).
  collectCoverageFrom: ['src/app/**/*.ts', '!src/app/**/*.spec.ts', '!src/app/app.config.ts'],
  // Soglia globale (`npm run test:coverage`, invocata dalla CI): livelli attuali
  // con un margine di qualche punto sotto, per non rendere il gate fragile a
  // piccole oscillazioni. Niente soglie per-file (#118).
  coverageThreshold: {
    global: {
      statements: 95,
      branches: 88,
      functions: 93,
      lines: 95,
    },
  },
};
