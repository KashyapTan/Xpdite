/**
 * Token usage tracking hook.
 * 
 * Manages token usage statistics for context window monitoring.
 */
import { useState, useCallback } from 'react';
import type { TokenUsage, TokenUsageSnapshot } from '../types';

const DEFAULT_LIMIT = 128000;

interface UseTokenUsageReturn {
  tokenUsage: TokenUsage;
  showTokenPopup: boolean;
  setShowTokenPopup: (show: boolean) => void;
  addTokens: (input: number, output: number) => void;
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
    limit: DEFAULT_LIMIT,
  });
  const [showTokenPopup, setShowTokenPopup] = useState(false);

  const addTokens = useCallback((input: number, output: number) => {
    setTokenUsageState(prev => ({
      ...prev,
      total: prev.total + input + output,
      input: prev.input + input,
      output: prev.output + output,
    }));
  }, []);

  const resetTokens = useCallback(() => {
    setTokenUsageState({
      total: 0,
      input: 0,
      output: 0,
      limit: DEFAULT_LIMIT,
    });
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
    setTokenUsageState({ ...s.tokenUsage });
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
