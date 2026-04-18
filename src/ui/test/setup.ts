import '@testing-library/jest-dom'

if (typeof window !== 'undefined') {
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    writable: true,
    value: () => {},
  })

  // Mock window.matchMedia for components that use it
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })

  // Mock ResizeObserver for components using it
  class MockResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = MockResizeObserver

  // Mock IntersectionObserver for components using it
  class MockIntersectionObserver {
    root = null
    rootMargin = ''
    thresholds: number[] = []
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] { return [] }
  }
  window.IntersectionObserver = MockIntersectionObserver

  Object.defineProperty(window.HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    writable: true,
    value: () => ({
      canvas: document.createElement('canvas'),
      clearRect: () => {},
      fillRect: () => {},
      fillText: () => {},
      measureText: (text: string) => ({ width: text.length * 8 }),
    }),
  })
}
