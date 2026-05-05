export function formatDurationMs(durationMs?: number | null): string {
  if (durationMs === undefined || durationMs === null || Number.isNaN(durationMs)) {
    return '';
  }

  const safeMs = Math.max(0, durationMs);
  if (safeMs < 1000) {
    return safeMs === 0 ? '0s' : `${Math.max(0.1, safeMs / 1000).toFixed(1)}s`;
  }

  const totalSeconds = safeMs / 1000;
  if (totalSeconds < 10) {
    return `${totalSeconds.toFixed(1)}s`;
  }

  if (totalSeconds < 60) {
    return `${Math.round(totalSeconds)}s`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}
