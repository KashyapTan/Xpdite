export function logPerf(message: string): void {
  console.log(message);

  if (typeof window === 'undefined') {
    return;
  }

  const transportPromise = window.electronAPI?.perfLog?.(message);
  if (!transportPromise) {
    return;
  }

  void transportPromise.catch(() => {
    // Ignore logging transport errors.
  });
}
