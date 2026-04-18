import { StrictMode, Suspense, lazy } from 'react'
import type { ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider } from 'react-router-dom'
import { TabProvider } from './contexts/TabContext'
import { BootProvider } from './contexts/BootContext'
import './CSS/base/theme.css'
import './CSS/base/global.css'
import Layout from './components/Layout.tsx'
import App from './pages/App.tsx'
type PageModule = { default: ComponentType }

const pageModules = import.meta.glob(['./pages/*.tsx', '!./pages/App.tsx']) as Record<string, () => Promise<PageModule>>

// Lazy-load non-chat pages to keep initial bundle small
const Settings = lazy(pageModules['./pages/Settings.tsx'])
const ChatHistory = lazy(pageModules['./pages/ChatHistory.tsx'])
const MeetingAlbum = lazy(pageModules['./pages/MeetingAlbum.tsx'])
const MeetingRecorder = lazy(pageModules['./pages/MeetingRecorder.tsx'])
const MeetingRecordingDetail = lazy(pageModules['./pages/MeetingRecordingDetail.tsx'])
const ScheduledJobsResults = lazy(pageModules['./pages/ScheduledJobsResults.tsx'])

// eslint-disable-next-line react-refresh/only-export-components
const LazyFallback = () => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--color-text-dim)', fontFamily: 'var(--font-family-ui)', fontSize: '13px' }}>
    Loading...
  </div>
)

const router = createHashRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        path: '/',
        element: <App />,
      },
      {
        path: '/settings',
        element: <Suspense fallback={<LazyFallback />}><Settings /></Suspense>,
      },
      {
        path: '/history',
        element: <Suspense fallback={<LazyFallback />}><ChatHistory /></Suspense>,
      },
      {
        path: '/album',
        element: <Suspense fallback={<LazyFallback />}><MeetingAlbum /></Suspense>,
      },
      {
        path: '/recorder',
        element: <Suspense fallback={<LazyFallback />}><MeetingRecorder /></Suspense>,
      },
      {
        path: '/recording/:id',
        element: <Suspense fallback={<LazyFallback />}><MeetingRecordingDetail /></Suspense>,
      },
      {
        path: '/scheduled-jobs',
        element: <Suspense fallback={<LazyFallback />}><ScheduledJobsResults /></Suspense>,
      },
    ]
  }
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BootProvider>
      <TabProvider>
        <RouterProvider router={router} />
      </TabProvider>
    </BootProvider>
  </StrictMode>,
)

