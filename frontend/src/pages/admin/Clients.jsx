import { useEffect, useMemo, useState } from 'react'
import Layout from '../../components/Layout'
import { api } from '../../api'

function formatStatus(status) {
  return (status || 'pending').replaceAll('_', ' ')
}

function statusClasses(status) {
  if (status === 'active') return 'bg-emerald-100 text-emerald-800'
  if (status === 'provisioning') return 'bg-amber-100 text-amber-800'
  if (status === 'provisioning_failed') return 'bg-rose-100 text-rose-800'
  return 'bg-slate-200 text-slate-700'
}

function StatCard({ label, value, tone = 'slate' }) {
  const tones = {
    slate: 'from-slate-900 to-slate-800 text-white',
    amber: 'from-amber-400 to-orange-400 text-slate-950',
    emerald: 'from-emerald-400 to-teal-400 text-slate-950',
  }

  return (
    <div className={`rounded-3xl bg-gradient-to-br p-5 shadow-lg ${tones[tone]}`}>
      <div className="text-xs uppercase tracking-[0.2em] opacity-70">{label}</div>
      <div className="mt-3 text-3xl font-bold">{value}</div>
    </div>
  )
}

export default function AdminClients() {
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(true)
  const [actionState, setActionState] = useState({})
  const [error, setError] = useState('')

  async function loadClients() {
    setLoading(true)
    setError('')
    try {
      const data = await api.listClients()
      setClients(data)
    } catch (err) {
      setError(err.message || 'Unable to load clients')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadClients()
  }, [])

  const stats = useMemo(() => {
    const pending = clients.filter((client) => client.status === 'pending').length
    const active = clients.filter((client) => client.status === 'active').length
    const callers = clients.reduce(
      (sum, client) => sum + (client.usage?.caller_count || 0),
      0
    )
    return { pending, active, callers }
  }, [clients])

  async function handleProvision(id) {
    setActionState((current) => ({ ...current, [id]: 'provisioning' }))
    setError('')
    try {
      const updated = await api.provisionClient(id)
      setClients((current) => current.map((client) => (client.id === id ? updated : client)))
    } catch (err) {
      setError(err.message || 'Provisioning failed')
    } finally {
      setActionState((current) => ({ ...current, [id]: null }))
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this client account and release any provisioned resources?')) return
    setActionState((current) => ({ ...current, [id]: 'deleting' }))
    setError('')
    try {
      await api.deleteClient(id)
      setClients((current) => current.filter((client) => client.id !== id))
    } catch (err) {
      setError(err.message || 'Delete failed')
    } finally {
      setActionState((current) => ({ ...current, [id]: null }))
    }
  }

  return (
    <Layout>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
            Client lifecycle
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Self-serve signups</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Clients now create their own account first. Admin handles provisioning and
            keeps visibility into status, ownership, and usage after go-live.
          </p>
        </div>
        <button
          type="button"
          onClick={loadClients}
          className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        <StatCard label="Pending approval" value={stats.pending} tone="amber" />
        <StatCard label="Active clients" value={stats.active} tone="emerald" />
        <StatCard label="Tracked callers" value={stats.callers} tone="slate" />
      </div>

      {error ? (
        <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="mt-8 rounded-[28px] border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="px-6 py-10 text-sm text-slate-500">Loading clients...</div>
        ) : clients.length === 0 ? (
          <div className="px-6 py-10 text-sm text-slate-500">
            No signups yet. Once a client registers, they will appear here.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50/80 text-slate-600">
                <tr>
                  <th className="px-6 py-4 font-semibold">Client</th>
                  <th className="px-6 py-4 font-semibold">Status</th>
                  <th className="px-6 py-4 font-semibold">Assigned number</th>
                  <th className="px-6 py-4 font-semibold">Usage</th>
                  <th className="px-6 py-4 font-semibold">Connected inbox</th>
                  <th className="px-6 py-4 font-semibold">Joined</th>
                  <th className="px-6 py-4 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {clients.map((client) => {
                  const busy = actionState[client.id]
                  return (
                    <tr key={client.id} className="align-top">
                      <td className="px-6 py-5">
                        <div className="font-semibold text-slate-950">{client.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{client.email}</div>
                        <a
                          href={client.website_url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-block text-xs text-sky-700 underline"
                        >
                          {client.website_url}
                        </a>
                      </td>
                      <td className="px-6 py-5">
                        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em] ${statusClasses(client.status)}`}>
                          {formatStatus(client.status)}
                        </span>
                        {client.provisioning_error ? (
                          <div className="mt-2 max-w-xs text-xs leading-5 text-rose-600">
                            {client.provisioning_error}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-6 py-5">
                        <div className="font-mono text-xs text-slate-700">
                          {client.phone_number || 'Not provisioned'}
                        </div>
                        <div className="mt-2 text-xs text-slate-500">
                          {client.area_code ? `Area ${client.area_code}` : 'Any area'}
                          {' • '}
                          {client.country || 'US'}
                        </div>
                      </td>
                      <td className="px-6 py-5 text-xs text-slate-600">
                        <div>{client.usage?.caller_count || 0} callers</div>
                        <div className="mt-2">
                          {client.usage?.last_call_at
                            ? `Last activity ${new Date(client.usage.last_call_at).toLocaleString()}`
                            : 'No call activity yet'}
                        </div>
                      </td>
                      <td className="px-6 py-5 text-xs text-slate-600">
                        {client.gmail_connected ? client.gmail_email || 'Connected' : 'Not connected'}
                      </td>
                      <td className="px-6 py-5 text-xs text-slate-500">
                        {client.created_at ? new Date(client.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex flex-col gap-2">
                          {client.status !== 'active' ? (
                            <button
                              type="button"
                              disabled={Boolean(busy)}
                              onClick={() => handleProvision(client.id)}
                              className="rounded-xl bg-slate-950 px-3 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {busy === 'provisioning'
                                ? 'Provisioning...'
                                : client.status === 'provisioning_failed'
                                  ? 'Retry provisioning'
                                  : 'Provision client'}
                            </button>
                          ) : (
                            <div className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
                              Live in production
                            </div>
                          )}
                          <button
                            type="button"
                            disabled={Boolean(busy)}
                            onClick={() => handleDelete(client.id)}
                            className="rounded-xl border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {busy === 'deleting' ? 'Deleting...' : 'Delete account'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  )
}
