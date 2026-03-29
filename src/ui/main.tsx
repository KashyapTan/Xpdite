import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider } from 'react-router-dom'
import { TabProvider } from './contexts/TabContext'
import { BootProvider } from './contexts/BootContext'
import Layout from './components/Layout.tsx'
import App from './pages/App.tsx'

// Lazy-load non-chat pages to keep initial bundle small
const Settings = lazy(() => import('./pages/Settings.tsx'))
const ChatHistory = lazy(() => import('./pages/ChatHistory.tsx'))
const MeetingAlbum = lazy(() => import('./pages/MeetingAlbum.tsx'))
const MeetingRecorder = lazy(() => import('./pages/MeetingRecorder.tsx'))
const MeetingRecordingDetail = lazy(() => import('./pages/MeetingRecordingDetail.tsx'))
const ScheduledJobsResults = lazy(() => import('./pages/ScheduledJobsResults.tsx'))

// eslint-disable-next-line react-refresh/only-export-components
const LazyFallback = () => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'rgba(255,255,255,0.5)', fontFamily: 'Montserrat, sans-serif', fontSize: '13px' }}>
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