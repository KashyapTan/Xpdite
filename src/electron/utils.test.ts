import { describe, expect, test } from 'vitest';

import { isDev } from './utils.js';

describe('isDev', () => {
  test('returns true only when NODE_ENV is development', () => {
    process.env.NODE_ENV = 'development';
    expect(isDev()).toBe(true);

    process.env.NODE_ENV = 'production';
    expect(isDev()).toBe(false);
  });
});
