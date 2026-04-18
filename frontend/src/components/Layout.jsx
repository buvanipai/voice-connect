import { NavLink, useNavigate } from 'react-router-dom'

function NavItem({ to, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
          isActive
            ? 'bg-amber-500 text-slate-950'
            : 'text-slate-100 hover:bg-slate-800 hover:text-white'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

export default function Layout({ children }) {
  const navigate = useNavigate()
  const role = localStorage.getItem('vc_role')
  const status = localStorage.getItem('vc_status')

  function logout() {
    localStorage.removeItem('vc_token')
    localStorage.removeItem('vc_role')
    localStorage.removeItem('vc_client_id')
    localStorage.removeItem('vc_status')
    navigate('/login')
  }

  const adminLinks = [
    { to: '/admin/clients', label: 'Clients' },
    { to: '/admin/callers', label: 'All Callers' },
    { to: '/admin/settings', label: 'Settings' },
    { to: '/admin/failed', label: 'Failed Notifications' },
  ]

  const clientLinks = [
    { to: '/client/callers', label: 'Overview' },
    { to: '/client/settings', label: 'Settings' },
  ]

  const links = role === 'admin' ? adminLinks : clientLinks

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <div className="w-56 bg-slate-900 flex flex-col">
        <div className="px-4 py-5 border-b border-slate-800">
          <span className="text-white font-bold text-lg tracking-tight">VoiceConnect</span>
          <div className="text-slate-300 text-xs mt-0.5 capitalize">{role}</div>
          {role === 'client' && status ? (
            <div className="mt-2 inline-flex rounded-full bg-amber-500/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-200">
              {status.replace('_', ' ')}
            </div>
          ) : null}
        </div>
        <nav className="flex-1 px-2 py-4 space-y-1">
          {links.map((l) => (
            <NavItem key={l.to} to={l.to} label={l.label} />
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-slate-800">
          <button
            onClick={logout}
            className="w-full text-left text-slate-300 hover:text-white text-sm"
          >
            Sign out
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 bg-gray-50 overflow-auto">
        <div className="max-w-6xl mx-auto px-6 py-8">{children}</div>
      </div>
    </div>
  )
}
