import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

function persistSession(data) {
  localStorage.setItem('vc_token', data.access_token)
  localStorage.setItem('vc_role', data.role)
  localStorage.setItem('vc_status', data.status || '')
  if (data.client_id) {
    localStorage.setItem('vc_client_id', data.client_id)
  } else {
    localStorage.removeItem('vc_client_id')
  }
}

function Field({ label, ...props }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      <input
        {...props}
        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-amber-500 focus:ring-2 focus:ring-amber-200"
      />
    </label>
  )
}

export default function Login({ initialMode = 'login' }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState(initialMode)
  const [loginForm, setLoginForm] = useState({ email: '', password: '' })
  const [signupForm, setSignupForm] = useState({
    name: '',
    website_url: '',
    area_code: '',
    country: 'US',
    email: '',
    password: '',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const heading = useMemo(
    () =>
      mode === 'login'
        ? {
            title: 'Sign in to VoiceConnect',
            body: 'Admins can review signups and usage. Clients can log in once their account has been created or approved.',
          }
        : {
            title: 'Create your client account',
            body: 'Sign up first, then an admin can provision your Twilio number and AI agent for production use.',
          },
    [mode]
  )

  async function handleLogin(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api.login(loginForm.email, loginForm.password)
      persistSession(data)
      navigate(data.role === 'admin' ? '/admin/clients' : '/client/callers', { replace: true })
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleSignup(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api.signup(signupForm)
      persistSession(data)
      navigate('/client/callers', { replace: true })
    } catch (err) {
      setError(err.message || 'Signup failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(251,191,36,0.2),_transparent_30%),linear-gradient(180deg,#fff7ed_0%,#f8fafc_50%,#e2e8f0_100%)] px-4 py-10">
      <div className="mx-auto grid min-h-[calc(100vh-5rem)] max-w-6xl items-center gap-8 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-[32px] bg-slate-950 px-8 py-10 text-white shadow-2xl shadow-slate-900/20 lg:px-12 lg:py-14">
          <div className="inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-amber-300">
            Smart Number SaaS
          </div>
          <h1 className="mt-6 max-w-xl text-4xl font-bold tracking-tight lg:text-5xl">
            Self-serve signup for clients, clear oversight for admin.
          </h1>
          <p className="mt-5 max-w-xl text-sm leading-6 text-slate-300">
            Clients create their own account first. Admin can then review who signed up,
            provision their phone number and AI agent, and track caller usage once they go live.
          </p>
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Step 1</div>
              <div className="mt-2 text-sm font-semibold">Client signs up</div>
              <p className="mt-2 text-xs leading-5 text-slate-300">
                Website, email, password, and market details are captured up front.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Step 2</div>
              <div className="mt-2 text-sm font-semibold">Admin provisions</div>
              <p className="mt-2 text-xs leading-5 text-slate-300">
                Twilio number, ElevenLabs knowledge base, and agent are attached when approved.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Step 3</div>
              <div className="mt-2 text-sm font-semibold">Client goes live</div>
              <p className="mt-2 text-xs leading-5 text-slate-300">
                Once active, the client sees callers, messaging settings, Gmail, and their assigned number.
              </p>
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-white/60 bg-white/90 p-6 shadow-xl shadow-slate-300/30 backdrop-blur lg:p-8">
          <div className="flex items-center gap-2 rounded-full bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => {
                setError('')
                setMode('login')
              }}
              className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
                mode === 'login' ? 'bg-slate-900 text-white' : 'text-slate-600'
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => {
                setError('')
                setMode('signup')
              }}
              className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
                mode === 'signup' ? 'bg-slate-900 text-white' : 'text-slate-600'
              }`}
            >
              Sign up
            </button>
          </div>

          <h2 className="mt-6 text-2xl font-bold text-slate-950">{heading.title}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{heading.body}</p>

          {error ? (
            <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          {mode === 'login' ? (
            <form onSubmit={handleLogin} className="mt-6 space-y-4">
              <Field
                label="Email or admin username"
                type="text"
                value={loginForm.email}
                onChange={(e) => setLoginForm((current) => ({ ...current, email: e.target.value }))}
                required
                autoFocus
              />
              <Field
                label="Password"
                type="password"
                value={loginForm.password}
                onChange={(e) => setLoginForm((current) => ({ ...current, password: e.target.value }))}
                required
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-xl bg-amber-500 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Signing in...' : 'Sign in'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleSignup} className="mt-6 space-y-4">
              <Field
                label="Company name"
                type="text"
                value={signupForm.name}
                onChange={(e) => setSignupForm((current) => ({ ...current, name: e.target.value }))}
                required
                autoFocus
              />
              <Field
                label="Website URL"
                type="url"
                value={signupForm.website_url}
                onChange={(e) => setSignupForm((current) => ({ ...current, website_url: e.target.value }))}
                required
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Area code"
                  type="text"
                  value={signupForm.area_code}
                  onChange={(e) => setSignupForm((current) => ({ ...current, area_code: e.target.value }))}
                />
                <Field
                  label="Country"
                  type="text"
                  value={signupForm.country}
                  onChange={(e) => setSignupForm((current) => ({ ...current, country: e.target.value }))}
                  required
                />
              </div>
              <Field
                label="Email"
                type="email"
                value={signupForm.email}
                onChange={(e) => setSignupForm((current) => ({ ...current, email: e.target.value }))}
                required
              />
              <Field
                label="Password"
                type="password"
                value={signupForm.password}
                onChange={(e) => setSignupForm((current) => ({ ...current, password: e.target.value }))}
                required
                minLength={8}
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Creating account...' : 'Create account'}
              </button>
            </form>
          )}

          <p className="mt-5 text-xs leading-5 text-slate-500">
            Admin login stays on the same page. Clients can sign up directly and will land in a pending state until their production setup is provisioned.
          </p>

          <p className="mt-4 text-xs text-slate-500">
            {mode === 'login' ? (
              <>
                New client? <Link to="/signup" onClick={() => setMode('signup')} className="font-semibold text-slate-900 underline">Create an account</Link>
              </>
            ) : (
              <>
                Already have an account? <Link to="/login" onClick={() => setMode('login')} className="font-semibold text-slate-900 underline">Sign in</Link>
              </>
            )}
          </p>
        </section>
      </div>
    </div>
  )
}
