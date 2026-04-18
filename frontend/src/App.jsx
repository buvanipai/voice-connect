import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import AdminClients from './pages/admin/Clients'
import AdminCallers from './pages/admin/Callers'
import AdminSettings from './pages/admin/Settings'
import AdminFailedNotifications from './pages/admin/FailedNotifications'
import ClientCallers from './pages/client/Callers'
import ClientSettings from './pages/client/Settings'

function getRole() {
  return localStorage.getItem('vc_role')
}

function RequireAdmin({ children }) {
  return getRole() === 'admin' ? children : <Navigate to="/login" replace />
}

function RequireClient({ children }) {
  return getRole() === 'client' ? children : <Navigate to="/login" replace />
}

function DefaultRedirect() {
  const role = getRole()
  if (role === 'admin') return <Navigate to="/admin/clients" replace />
  if (role === 'client') return <Navigate to="/client/callers" replace />
  return <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Login initialMode="signup" />} />

        {/* Admin routes */}
        <Route path="/admin/clients" element={<RequireAdmin><AdminClients /></RequireAdmin>} />
        <Route path="/admin/callers" element={<RequireAdmin><AdminCallers /></RequireAdmin>} />
        <Route path="/admin/settings" element={<RequireAdmin><AdminSettings /></RequireAdmin>} />
        <Route path="/admin/failed" element={<RequireAdmin><AdminFailedNotifications /></RequireAdmin>} />

        {/* Client routes */}
        <Route path="/client/callers" element={<RequireClient><ClientCallers /></RequireClient>} />
        <Route path="/client/settings" element={<RequireClient><ClientSettings /></RequireClient>} />

        {/* Default */}
        <Route path="/" element={<DefaultRedirect />} />
        <Route path="*" element={<DefaultRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
