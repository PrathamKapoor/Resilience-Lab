import { expect, test } from 'vitest';

test('uses the dashboard base path', () => {
  expect(import.meta.env.BASE_URL).toBe('/dashboard/');
});
