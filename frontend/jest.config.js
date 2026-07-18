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
