/**
 * Tests for useTokenUsage hook.
 */
import { describe, expect, test } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTokenUsage } from '../../hooks/useTokenUsage';
import type { TokenUsageSnapshot } from '../../types';

describe('useTokenUsage', () => {
  describe('initial state', () => {
    test('should have correct initial values', () => {
      const { result } = renderHook(() => useTokenUsage());

      expect(result.current.tokenUsage).toEqual({
        total: 0,
        input: 0,
        output: 0,
        limit: 128000,
      });
      expect(result.current.showTokenPopup).toBe(false);
    });

    test('should initialize with default limit of 128000', () => {
      const { result } = renderHook(() => useTokenUsage());

      expect(result.current.tokenUsage.limit).toBe(128000);
    });
  });

  describe('addTokens', () => {
    test('should add input and output tokens', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      expect(result.current.tokenUsage.input).toBe(100);
      expect(result.current.tokenUsage.output).toBe(50);
      expect(result.current.tokenUsage.total).toBe(150);
    });

    test('should accumulate tokens across multiple calls', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      act(() => {
        result.current.addTokens(200, 100);
      });

      expect(result.current.tokenUsage.input).toBe(300);
      expect(result.current.tokenUsage.output).toBe(150);
      expect(result.current.tokenUsage.total).toBe(450);
    });

    test('should preserve limit when adding tokens', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(1000, 500);
      });

      expect(result.current.tokenUsage.limit).toBe(128000);
    });

    test('should handle zero token additions', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      act(() => {
        result.current.addTokens(0, 0);
      });

      expect(result.current.tokenUsage.total).toBe(150);
    });

    test('should handle large token counts', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(50000, 25000);
      });

      expect(result.current.tokenUsage.input).toBe(50000);
      expect(result.current.tokenUsage.output).toBe(25000);
      expect(result.current.tokenUsage.total).toBe(75000);
    });
  });

  describe('resetTokens', () => {
    test('should reset all token counts to zero', () => {
      const { result } = renderHook(() => useTokenUsage());

      // Add some tokens first
      act(() => {
        result.current.addTokens(500, 250);
      });

      expect(result.current.tokenUsage.total).toBe(750);

      // Reset
      act(() => {
        result.current.resetTokens();
      });

      expect(result.current.tokenUsage).toEqual({
        total: 0,
        input: 0,
        output: 0,
        limit: 128000,
      });
    });

    test('should reset to default limit', () => {
      const { result } = renderHook(() => useTokenUsage());

      // Change limit
      act(() => {
        result.current.setTokenUsage({ limit: 200000 });
      });

      expect(result.current.tokenUsage.limit).toBe(200000);

      // Reset should restore default limit
      act(() => {
        result.current.resetTokens();
      });

      expect(result.current.tokenUsage.limit).toBe(128000);
    });

    test('should be idempotent when called multiple times', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      act(() => {
        result.current.resetTokens();
        result.current.resetTokens();
        result.current.resetTokens();
      });

      expect(result.current.tokenUsage.total).toBe(0);
    });
  });

  describe('setTokenUsage', () => {
    test('should partially update token usage', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      act(() => {
        result.current.setTokenUsage({ input: 200 });
      });

      expect(result.current.tokenUsage.input).toBe(200);
      expect(result.current.tokenUsage.output).toBe(50);
      expect(result.current.tokenUsage.total).toBe(150);
    });

    test('should update limit', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.setTokenUsage({ limit: 200000 });
      });

      expect(result.current.tokenUsage.limit).toBe(200000);
    });

    test('should update multiple fields at once', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.setTokenUsage({
          total: 1000,
          input: 700,
          output: 300,
          limit: 50000,
        });
      });

      expect(result.current.tokenUsage).toEqual({
        total: 1000,
        input: 700,
        output: 300,
        limit: 50000,
      });
    });

    test('should handle empty partial update', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      const before = { ...result.current.tokenUsage };

      act(() => {
        result.current.setTokenUsage({});
      });

      expect(result.current.tokenUsage).toEqual(before);
    });
  });

  describe('showTokenPopup', () => {
    test('should toggle popup visibility', () => {
      const { result } = renderHook(() => useTokenUsage());

      expect(result.current.showTokenPopup).toBe(false);

      act(() => {
        result.current.setShowTokenPopup(true);
      });

      expect(result.current.showTokenPopup).toBe(true);

      act(() => {
        result.current.setShowTokenPopup(false);
      });

      expect(result.current.showTokenPopup).toBe(false);
    });
  });

  describe('getSnapshot / restoreSnapshot', () => {
    test('should capture current token usage as snapshot', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(1000, 500);
        result.current.setTokenUsage({ limit: 256000 });
      });

      let snapshot: TokenUsageSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      expect(snapshot!.tokenUsage).toEqual({
        total: 1500,
        input: 1000,
        output: 500,
        limit: 256000,
      });
    });

    test('should restore state from snapshot', () => {
      const { result } = renderHook(() => useTokenUsage());

      const snapshot: TokenUsageSnapshot = {
        tokenUsage: {
          total: 5000,
          input: 3000,
          output: 2000,
          limit: 100000,
        },
      };

      act(() => {
        result.current.restoreSnapshot(snapshot);
      });

      expect(result.current.tokenUsage).toEqual(snapshot.tokenUsage);
    });

    test('snapshot and restore should be symmetric', () => {
      const { result } = renderHook(() => useTokenUsage());

      // Set up state
      act(() => {
        result.current.addTokens(2500, 1250);
        result.current.setTokenUsage({ limit: 64000 });
      });

      // Take snapshot
      let snapshot: TokenUsageSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      // Reset
      act(() => {
        result.current.resetTokens();
      });

      expect(result.current.tokenUsage.total).toBe(0);

      // Restore
      act(() => {
        result.current.restoreSnapshot(snapshot!);
      });

      expect(result.current.tokenUsage.total).toBe(3750);
      expect(result.current.tokenUsage.input).toBe(2500);
      expect(result.current.tokenUsage.output).toBe(1250);
      expect(result.current.tokenUsage.limit).toBe(64000);
    });

    test('should create independent snapshot copy', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100, 50);
      });

      let snapshot: TokenUsageSnapshot;
      act(() => {
        snapshot = result.current.getSnapshot();
      });

      // Modify state after snapshot
      act(() => {
        result.current.addTokens(200, 100);
      });

      // Snapshot should be unchanged
      expect(snapshot!.tokenUsage.total).toBe(150);
      expect(result.current.tokenUsage.total).toBe(450);
    });
  });

  describe('display formatting calculations', () => {
    test('should correctly calculate percentage of limit used', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(64000, 0); // 50% of 128000
      });

      const percentage = (result.current.tokenUsage.total / result.current.tokenUsage.limit) * 100;
      expect(percentage).toBe(50);
    });

    test('should handle tokens exceeding limit', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(100000, 50000); // 150000 total, exceeds 128000
      });

      expect(result.current.tokenUsage.total).toBe(150000);
      expect(result.current.tokenUsage.total).toBeGreaterThan(result.current.tokenUsage.limit);

      const percentage = (result.current.tokenUsage.total / result.current.tokenUsage.limit) * 100;
      expect(percentage).toBeGreaterThan(100);
    });

    test('should format token counts correctly for display', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(1234, 5678);
      });

      // Test that values are numbers and can be formatted
      const { input, output, total } = result.current.tokenUsage;
      expect(Number.isInteger(input)).toBe(true);
      expect(Number.isInteger(output)).toBe(true);
      expect(Number.isInteger(total)).toBe(true);

      // Example display formatting
      const displayTotal = total.toLocaleString();
      expect(displayTotal).toBe('6,912');
    });
  });

  describe('reset on new conversation', () => {
    test('should allow reset for starting fresh conversation', () => {
      const { result } = renderHook(() => useTokenUsage());

      // Simulate a conversation with multiple exchanges
      act(() => {
        result.current.addTokens(1000, 500); // First exchange
      });
      act(() => {
        result.current.addTokens(1500, 750); // Second exchange
      });
      act(() => {
        result.current.addTokens(2000, 1000); // Third exchange
      });

      expect(result.current.tokenUsage.total).toBe(6750);

      // Start new conversation
      act(() => {
        result.current.resetTokens();
      });

      expect(result.current.tokenUsage).toEqual({
        total: 0,
        input: 0,
        output: 0,
        limit: 128000,
      });
    });
  });

  describe('edge cases', () => {
    test('should handle very small token counts', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(1, 1);
      });

      expect(result.current.tokenUsage.total).toBe(2);
    });

    test('should maintain consistency between input + output and total', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        result.current.addTokens(1234, 5678);
      });

      act(() => {
        result.current.addTokens(111, 222);
      });

      const { input, output, total } = result.current.tokenUsage;
      expect(input + output).toBe(total);
    });

    test('should handle rapid consecutive updates', () => {
      const { result } = renderHook(() => useTokenUsage());

      act(() => {
        for (let i = 0; i < 100; i++) {
          result.current.addTokens(10, 5);
        }
      });

      expect(result.current.tokenUsage.input).toBe(1000);
      expect(result.current.tokenUsage.output).toBe(500);
      expect(result.current.tokenUsage.total).toBe(1500);
    });
  });
});
