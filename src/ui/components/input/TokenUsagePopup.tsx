/**
 * Token usage popup component.
 * 
 * Shows context window usage statistics in a popup.
 */
import React from 'react';
import type { TokenUsage } from '../../types';
import { getModelProviderKey } from '../../utils/modelDisplay';

interface TokenUsagePopupProps {
  tokenUsage: TokenUsage;
  modelId?: string;
  show: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onClick: () => void;
  contextWindowIcon: string;
}

export function TokenUsagePopup({
  tokenUsage,
  modelId = '',
  show,
  onMouseEnter,
  onMouseLeave,
  onClick,
  contextWindowIcon,
}: TokenUsagePopupProps) {
  const providerKey = modelId ? getModelProviderKey(modelId) : '';
  const normalizedModelId = modelId.toLowerCase();
  const isOllamaModel = providerKey === 'ollama';
  const supportsCacheWriteMetric = providerKey === 'anthropic'
    || (providerKey === 'openrouter' && (
      normalizedModelId.includes('anthropic/')
      || normalizedModelId.includes('claude')
    ));
  const showCacheWriteMetric = tokenUsage.cacheWrite !== null || supportsCacheWriteMetric;
  const hasLimit = tokenUsage.limit > 0;
  const percentage = hasLimit ? Math.round((tokenUsage.total / tokenUsage.limit) * 100) : 0;
  const inputPercentage = Math.round((tokenUsage.input / tokenUsage.total || 0) * 100);
  const outputPercentage = Math.round((tokenUsage.output / tokenUsage.total || 0) * 100);
  const hasCachedTokens = tokenUsage.cached !== null;
  const cachedPercentage = hasCachedTokens && tokenUsage.input > 0
    ? Math.round((tokenUsage.cached / tokenUsage.input) * 100)
    : 0;
  const totalLabel = tokenUsage.total.toLocaleString();
  const limitLabel = hasLimit ? `${tokenUsage.limit.toLocaleString()} tokens` : 'Unknown limit';
  const cachedTokenLabel = hasCachedTokens
    ? `${tokenUsage.cached.toLocaleString()} (${cachedPercentage}% of input)`
    : isOllamaModel
      ? 'Not supported'
      : 'Not reported';

  return (
    <div
      className="context-window-insights-icon"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
    >
      <img
        src={contextWindowIcon}
        alt="Context Window Insights"
        className="context-window-insights-svg"
        title="Context Window Insights"
      />

      {show && (
        <div className="token-usage-popup">
          <div className="token-popup-header">
            <span className="token-popup-title">Context Window</span>
            <span className="token-popup-subtitle">
              {totalLabel} / {limitLabel}
              {hasLimit ? ` • ${percentage}%` : ''}
            </span>
          </div>

          <div className="token-progress-bar-container">
            <div
              className="token-progress-bar-fill"
              style={{ width: `${Math.min(100, percentage)}%` }}
            ></div>
          </div>

          <div className="token-usage-section">
            <div className="token-usage-row">
              <span className="token-usage-label">Total Tokens</span>
              <span className="token-usage-value">
                {totalLabel}
                {hasLimit ? ` (${percentage}%)` : ''}
              </span>
            </div>
            <div className="token-usage-row">
              <span className="token-usage-label">Input Tokens</span>
              <span className="token-usage-value">
                {tokenUsage.input.toLocaleString()} ({inputPercentage}%)
              </span>
            </div>
            <div className="token-usage-row">
              <span className="token-usage-label">Output Tokens</span>
              <span className="token-usage-value">
                {tokenUsage.output.toLocaleString()} ({outputPercentage}%)
              </span>
            </div>
            <div className="token-usage-row">
              <span
                className="token-usage-label"
                title="Prompt input tokens served from a provider prompt cache."
              >
                Cached Tokens
              </span>
              <span className="token-usage-value">
                {cachedTokenLabel}
              </span>
            </div>
            {showCacheWriteMetric && (
              <div className="token-usage-row">
                <span
                  className="token-usage-label"
                  title="Prompt input tokens written into a provider prompt cache."
                >
                  Cache Created
                </span>
                <span className="token-usage-value">
                  {tokenUsage.cacheWrite !== null
                    ? tokenUsage.cacheWrite.toLocaleString()
                    : 'Not reported'}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
