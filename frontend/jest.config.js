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
  // Measures ALL the real source, not just the files imported by the tests (otherwise
  // a never-tested file would simply not appear in the report, inflating the
  // percentage). `app.config.ts` (bootstrap/DI, zero logic) stays excluded on purpose:
  // no trivial specs. `main.ts` is already outside `src/app/**` (#118).
  collectCoverageFrom: ['src/app/**/*.ts', '!src/app/**/*.spec.ts', '!src/app/app.config.ts'],
  // Global threshold (`npm run test:coverage`, invoked by CI): current levels
  // with a margin of a few points below, so as not to make the gate fragile to
  // small fluctuations. No per-file thresholds (#118).
  coverageThreshold: {
    global: {
      statements: 95,
      branches: 88,
      functions: 93,
      lines: 95,
    },
  },
};
