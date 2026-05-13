/**
 * Token usage tracking hook.
 * 
 * Manages token usage statistics for context window monitoring.
 */
import { useState, useCallback } from 'react';
import type { TokenUsage, TokenUsageSnapshot } from '../types';

const UNKNOWN_LIMIT = 0;

interface UseTokenUsageReturn {
  tokenUsage: TokenUsage;
  showTokenPopup: boolean;
  setShowTokenPopup: (show: boolean) => void;
  addTokens: (input: number, output: number, cached?: number, cacheWrite?: number) => void;
  resetTokens: () => void;
  setTokenUsage: (usage: Partial<TokenUsage>) => void;
  getSnapshot: () => TokenUsageSnapshot;
  restoreSnapshot: (snapshot: TokenUsageSnapshot) => void;
}

export function useTokenUsage(): UseTokenUsageReturn {
  const [tokenUsage, setTokenUsageState] = useState<TokenUsage>({
    total: 0,
    input: 0,
    output: 0,
    cached: null,
    cacheWrite: null,
    limit: UNKNOWN_LIMIT,
  });
  const [showTokenPopup, setShowTokenPopup] = useState(false);

  const addTokens = useCallback((input: number, output: number, cached?: number, cacheWrite?: number) => {
    setTokenUsageState(prev => ({
      ...prev,
      total: prev.total + input + output,
      input: prev.input + input,
      output: prev.output + output,
      cached: cached === undefined ? prev.cached : (prev.cached ?? 0) + cached,
      cacheWrite: cacheWrite === undefined ? prev.cacheWrite : (prev.cacheWrite ?? 0) + cacheWrite,
    }));
  }, []);

  const resetTokens = useCallback(() => {
    setTokenUsageState(prev => ({
      total: 0,
      input: 0,
      output: 0,
      cached: null,
      cacheWrite: null,
      limit: prev.limit,
    }));
  }, []);

  const setTokenUsage = useCallback((usage: Partial<TokenUsage>) => {
    setTokenUsageState(prev => ({
      ...prev,
      ...usage,
    }));
  }, []);

  const getSnapshot = useCallback((): TokenUsageSnapshot => ({
    tokenUsage: { ...tokenUsage },
  }), [tokenUsage]);

  const restoreSnapshot = useCallback((s: TokenUsageSnapshot) => {
    setTokenUsageState({
      cached: null,
      cacheWrite: null,
      ...s.tokenUsage,
    });
  }, []);

  return {
    tokenUsage,
    showTokenPopup,
    setShowTokenPopup,
    addTokens,
    resetTokens,
    setTokenUsage,
    getSnapshot,
    restoreSnapshot,
  };
}
