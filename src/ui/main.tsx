import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createHashRouter, RouterProvider } from 'react-router-dom'
import { TabProvider } from './contexts/TabContext'
import Layout from './components/Layout.tsx'
import App from './pages/App.tsx'
import Settings from './pages/Settings.tsx'
import ChatHistory from './pages/ChatHistory.tsx'
import MeetingAlbum from './pages/MeetingAlbum.tsx'

// CHANGE 2: Use createHashRouter here
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
        element: <Settings />,
      },
      {
        path: '/history',
        element: <ChatHistory />,
      },
      {
        path: '/album',
        element: <MeetingAlbum />,
      }
    ]
  }
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TabProvider>
      <RouterProvider router={router} />
    </TabProvider>
  </StrictMode>,
)