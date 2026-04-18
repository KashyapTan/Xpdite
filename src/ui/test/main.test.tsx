import type { ReactNode } from 'react'

import { beforeEach, describe, expect, test, vi } from 'vitest'

const createHashRouterMock = vi.fn()
const createRootMock = vi.fn()
const renderMock = vi.fn()

vi.mock('react-dom/client', () => ({
  createRoot: createRootMock,
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    RouterProvider: ({ children }: { children?: ReactNode }) => <div data-testid="router-provider">{children}</div>,
    createHashRouter: createHashRouterMock,
  }
})

describe('ui main entrypoint', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    document.body.innerHTML = '<div id="root"></div>'
    createRootMock.mockReturnValue({ render: renderMock })
    createHashRouterMock.mockImplementation((routes) => ({ routes }))
  })

  test('registers the main application routes and renders them into the root container', async () => {
    await import('../main.tsx')

    expect(createRootMock).toHaveBeenCalledWith(document.getElementById('root'))
    expect(renderMock).toHaveBeenCalledTimes(1)
    const routes = createHashRouterMock.mock.calls[0]?.[0] as Array<{ path: string; children?: Array<{ path: string }> }>
    expect(routes).toHaveLength(1)
    expect(routes[0]?.path).toBe('/')
    expect(routes[0]?.children?.map((route) => route.path)).toEqual([
      '/',
      '/settings',
      '/history',
      '/album',
      '/recorder',
      '/recording/:id',
      '/scheduled-jobs',
    ])
  })
})
