import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
  }`

export function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-6">
          <NavLink to="/applications" className="text-lg font-semibold text-slate-900">
            Job Tracker
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            <NavLink to="/applications" className={linkClass}>
              Applications
            </NavLink>
            <NavLink to="/settings" className={linkClass}>
              Settings
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="max-w-[200px] truncate text-sm text-slate-500" title={user?.email}>
            {user?.email}
          </span>
          <button
            type="button"
            onClick={() => handleLogout()}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  )
}
