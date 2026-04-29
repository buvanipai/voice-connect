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
    rose: 'from-rose-400 to-red-400 text-white',
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
  const [editing, setEditing] = useState(null)
  const [calls, setCalls] = useState([])
  const [callsLoading, setCallsLoading] = useState(false)
  const [addForm, setAddForm] = useState({
    name: '',
    website_url: '',
    email: '',
    password: '',
    area_code: '',
    country: 'US',
    plan: 'starter',
  })
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState('')
  const [editForm, setEditForm] = useState({
    name: '',
    website_url: '',
    area_code: '',
    country: '',
    plan: 'starter',
    forward_to_number: '',
    sms_10dlc_approved: false,
  })
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState('')

  function openEdit(client) {
    setEditing(client)
    setCalls([])
    setCallsLoading(true)
    setEditForm({
      name: client.name || '',
      website_url: client.website_url || '',
      area_code: client.area_code || '',
      country: client.country || 'US',
      plan: client.plan?.key || 'starter',
      forward_to_number: client.forward_to_number || '',
      sms_10dlc_approved: Boolean(client.sms_10dlc_approved),
    })
    setEditError('')
    
    // Fetch call history
    api.getClientCalls(client.id)
      .then((data) => {
        setCalls(data || [])
      })
      .catch((err) => {
        console.error('Failed to fetch calls:', err)
        setCalls([])
      })
      .finally(() => {
        setCallsLoading(false)
      })
  }

  function closeEdit() {
    setEditing(null)
    setEditError('')
  }

  async function saveEdit(event) {
    event.preventDefault()
    if (!editing) return
    setEditSaving(true)
    setEditError('')
    try {
      const updated = await api.updateClient(editing.id, editForm)
      setClients((current) => current.map((c) => (c.id === updated.id ? updated : c)))
      closeEdit()
    } catch (err) {
      setEditError(err.message || 'Update failed')
    } finally {
      setEditSaving(false)
    }
  }

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
    const monthlyMinutes = clients.reduce(
      (sum, client) => sum + Number(client.usage?.minutes_used || client.minutes_used || 0),
      0
    )
    const nearLimit = clients.filter((client) => {
      const included = Number(client.usage?.plan_limit_minutes || client.usage?.included_minutes || 0)
      const used = Number(client.usage?.minutes_used || client.minutes_used || 0)
      return included > 0 && used >= included * 0.9 && used < included
    }).length
    const overLimit = clients.filter((client) => {
      const included = Number(client.usage?.plan_limit_minutes || client.usage?.included_minutes || 0)
      const used = Number(client.usage?.minutes_used || client.minutes_used || 0)
      return included > 0 && used >= included
    }).length
    return { pending, active, monthlyMinutes, nearLimit, overLimit }
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

  async function handleAddClient(e) {
    e.preventDefault()
    setAdding(true)
    setAddError('')
    try {
      const newClient = await api.addClient(addForm)
      setClients((current) => [newClient, ...current])
      setAddForm({
        name: '',
        website_url: '',
        email: '',
        password: '',
        area_code: '',
        country: 'US',
        plan: 'starter',
      })
    } catch (err) {
      setAddError(err.message || 'Add client failed')
    } finally {
      setAdding(false)
    }
  }

  // Trigger add form via 'Add client' button
  function startAddingClient() {
    setAddForm({
      name: '',
      website_url: '',
      email: 'trigger',  // Non-empty to show form
      password: '',
      area_code: '',
      country: 'US',
      plan: 'starter',
    })
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
            Clients create their own account or admin can add them. Admin handles provisioning and
            keeps visibility into status, ownership, and usage after go-live.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setAddForm({
              name: '',
              website_url: '',
              email: '',
              password: '',
              area_code: '',
              country: 'US',
              plan: 'starter',
            })}
            className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Add client
          </button>
          <button
            type="button"
            onClick={loadClients}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-5">
        <StatCard label="Pending approval" value={stats.pending} tone="amber" />
        <StatCard label="Active clients" value={stats.active} tone="emerald" />
        <StatCard label="Monthly minutes" value={stats.monthlyMinutes.toFixed(1)} tone="slate" />
        <StatCard label="Near limit" value={stats.nearLimit} tone="amber" />
        <StatCard label="Over limit" value={stats.overLimit} tone="rose" />
      </div>

      {error ? (
        <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      {addForm.email ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4 overflow-y-auto"
          onClick={() => setAddForm((f) => ({ ...f, email: '' }))}
        >
          <form
            onClick={(e) => e.stopPropagation()}
            onSubmit={handleAddClient}
            className="w-full max-w-2xl rounded-[28px] bg-white p-6 shadow-2xl my-8"
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
                  Add client
                </p>
                <h2 className="mt-1 text-xl font-bold text-slate-950">Create new client account</h2>
              </div>
              <button
                type="button"
                onClick={() => setAddForm((f) => ({ ...f, email: '' }))}
                className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                ✕
              </button>
            </div>
            {addError && (
              <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {addError}
              </div>
            )}
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Company name
                </label>
                <input
                  type="text"
                  required
                  value={addForm.name}
                  onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Website
                </label>
                <input
                  type="url"
                  required
                  value={addForm.website_url}
                  onChange={(e) => setAddForm((f) => ({ ...f, website_url: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={addForm.email}
                  onChange={(e) => setAddForm((f) => ({ ...f, email: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength="8"
                  value={addForm.password}
                  onChange={(e) => setAddForm((f) => ({ ...f, password: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                    Area code
                  </label>
                  <input
                    type="text"
                    value={addForm.area_code}
                    onChange={(e) => setAddForm((f) => ({ ...f, area_code: e.target.value }))}
                    placeholder="e.g. 312"
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                    Country
                  </label>
                  <input
                    type="text"
                    value={addForm.country}
                    onChange={(e) => setAddForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))}
                    maxLength={2}
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm uppercase focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Plan
                </label>
                <select
                  value={addForm.plan}
                  onChange={(e) => setAddForm((f) => ({ ...f, plan: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                >
                  <option value="starter">Starter • 100 min included</option>
                  <option value="growth">Growth • 300 min included</option>
                  <option value="agency">Agency • 1000 min included</option>
                </select>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setAddForm((f) => ({ ...f, email: '' }))}
                disabled={adding}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={adding}
                className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {adding ? 'Adding...' : 'Add client'}
              </button>
            </div>
          </form>
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
                  <th className="px-6 py-4 font-semibold">Plan</th>
                  <th className="px-6 py-4 font-semibold">Usage</th>
                  <th className="px-6 py-4 font-semibold">Connected inbox</th>
                  <th className="px-6 py-4 font-semibold">Joined</th>
                  <th className="px-6 py-4 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {clients.map((client) => {
                  const busy = actionState[client.id]
                  const planLimitMinutes = Number(client.usage?.plan_limit_minutes || client.usage?.included_minutes || 0)
                  const minutesUsed = Number(client.usage?.minutes_used || client.minutes_used || 0)
                  const usagePercent = planLimitMinutes > 0
                    ? Math.round((minutesUsed / planLimitMinutes) * 100)
                    : 0
                  const usagePercentClamped = Math.min(100, Math.max(0, usagePercent))
                  const overLimit = planLimitMinutes > 0 && minutesUsed >= planLimitMinutes
                  const nearLimit = !overLimit && planLimitMinutes > 0 && minutesUsed >= (planLimitMinutes * 0.9)
                  return (
                    <tr
                      key={client.id}
                      onClick={() => openEdit(client)}
                      className="cursor-pointer align-top transition hover:bg-slate-50"
                    >
                      <td className="px-6 py-5">
                        <div className="font-semibold text-slate-950">{client.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{client.email}</div>
                        <a
                          href={client.website_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
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
                          {client.area_code ? `Pref ${client.area_code}` : 'Any area'}
                          {' • '}
                          {client.country || 'US'}
                        </div>
                      </td>
                      <td className="px-6 py-5 text-xs text-slate-600">
                        <div className="font-semibold text-slate-900">{client.plan?.label || 'Starter'}</div>
                        <div className="mt-1">
                          {client.plan?.included_minutes || 100} included min
                        </div>
                        <div className="mt-1 text-slate-500">
                          ${client.plan?.overage_rate?.toFixed?.(2) || '0.35'}/min over
                        </div>
                      </td>
                      <td className="px-6 py-5 text-xs text-slate-600">
                        <div>Minutes used: {minutesUsed.toFixed(2)}</div>
                        <div className="mt-1">Plan limit: {planLimitMinutes.toFixed(0)} min</div>
                        <div className="mt-1">Used: {usagePercent}%</div>
                        {overLimit ? (
                          <span className="mt-2 inline-flex rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-rose-700">
                            Over limit
                          </span>
                        ) : nearLimit ? (
                          <span className="mt-2 inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-amber-700">
                            Near limit
                          </span>
                        ) : null}
                        <div className="mt-2 h-1.5 w-40 rounded-full bg-slate-200">
                          <div
                            className={`h-1.5 rounded-full ${usagePercent >= 100 ? 'bg-rose-500' : usagePercent >= 90 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                            style={{ width: `${usagePercentClamped}%` }}
                          />
                        </div>
                        <div className="mt-1">{client.usage?.call_count || 0} total calls</div>
                        <div className="mt-1">{client.usage?.caller_count || 0} callers</div>
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
                      <td className="px-6 py-5" onClick={(e) => e.stopPropagation()}>
                        <div className="flex flex-col gap-2">
                          <button
                            type="button"
                            disabled={Boolean(busy)}
                            onClick={() => handleProvision(client.id)}
                            className={
                              client.status === 'active'
                                ? 'rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60'
                                : 'rounded-xl bg-slate-950 px-3 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60'
                            }
                          >
                            {busy === 'provisioning'
                              ? 'Working...'
                              : client.status === 'active'
                                ? 'Re-sync ElevenLabs'
                                : client.status === 'provisioning_failed'
                                  ? 'Retry provisioning'
                                  : 'Provision client'}
                          </button>
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

      {editing ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4 overflow-y-auto"
          onClick={closeEdit}
        >
          <form
            onClick={(e) => e.stopPropagation()}
            onSubmit={saveEdit}
            className="w-full max-w-2xl rounded-[28px] bg-white p-6 shadow-2xl my-8"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
                  Edit client
                </p>
                <h2 className="mt-1 text-xl font-bold text-slate-950">{editing.name}</h2>
                <p className="mt-1 text-xs text-slate-500">{editing.email}</p>
              </div>
              <button
                type="button"
                onClick={closeEdit}
                className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                ✕
              </button>
            </div>

            <div className="mt-5 space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Name
                </label>
                <input
                  type="text"
                  value={editForm.name}
                  onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Website URL
                </label>
                <input
                  type="url"
                  value={editForm.website_url}
                  onChange={(e) => setEditForm((f) => ({ ...f, website_url: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                    Area code
                  </label>
                  <input
                    type="text"
                    value={editForm.area_code}
                    onChange={(e) => setEditForm((f) => ({ ...f, area_code: e.target.value }))}
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                    Country
                  </label>
                  <input
                    type="text"
                    value={editForm.country}
                    onChange={(e) => setEditForm((f) => ({ ...f, country: e.target.value.toUpperCase() }))}
                    maxLength={2}
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm uppercase focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Plan
                </label>
                <select
                  value={editForm.plan}
                  onChange={(e) => setEditForm((f) => ({ ...f, plan: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                >
                  <option value="starter">Starter • 100 min included</option>
                  <option value="growth">Growth • 300 min included</option>
                  <option value="agency">Agency • 1000 min included</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Forward calls to
                </label>
                <input
                  type="tel"
                  placeholder="+13125551234"
                  value={editForm.forward_to_number}
                  onChange={(e) => setEditForm((f) => ({ ...f, forward_to_number: e.target.value }))}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                />
                <p className="mt-1 text-xs text-slate-500">
                  E.164 format. Leave blank to disable live transfer.
                </p>
              </div>
              <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <input
                  type="checkbox"
                  checked={editForm.sms_10dlc_approved}
                  onChange={(e) => setEditForm((f) => ({ ...f, sms_10dlc_approved: e.target.checked }))}
                  className="mt-0.5 h-4 w-4"
                />
                <span className="text-xs text-slate-700">
                  <span className="block font-semibold">SMS 10DLC approved</span>
                  <span className="text-slate-500">
                    Check once this client's A2P brand + campaign are approved in Twilio. Unblocks the SMS toggle in their settings.
                  </span>
                </span>
              </label>
              <p className="text-xs text-slate-500">
                Provisioned resources (phone number, agent, email) can't be edited — delete and re-provision to change them.
              </p>
            </div>

            <div className="mt-6 border-t border-slate-200 pt-6">
              <h3 className="text-sm font-semibold text-slate-900">Call history</h3>
              {callsLoading ? (
                <div className="mt-3 text-xs text-slate-500">Loading calls...</div>
              ) : calls.length === 0 ? (
                <div className="mt-3 text-xs text-slate-500">No calls yet.</div>
              ) : (
                <div className="mt-3 overflow-hidden rounded-xl border border-slate-200">
                  <table className="w-full text-xs">
                    <thead className="border-b border-slate-200 bg-slate-50">
                      <tr>
                        <th className="px-3 py-2 text-left font-semibold text-slate-700">Caller</th>
                        <th className="px-3 py-2 text-left font-semibold text-slate-700">Intent</th>
                        <th className="px-3 py-2 text-right font-semibold text-slate-700">Duration</th>
                        <th className="px-3 py-2 text-left font-semibold text-slate-700">Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {calls.slice(0, 10).map((call) => (
                        <tr key={call.id} className="hover:bg-slate-50">
                          <td className="px-3 py-2 font-mono text-slate-600">{call.caller_phone}</td>
                          <td className="px-3 py-2 text-slate-600">{call.intent || '—'}</td>
                          <td className="px-3 py-2 text-right text-slate-600">
                            {call.duration_minutes || 0} min
                          </td>
                          <td className="px-3 py-2 text-slate-500">
                            {call.occurred_at ? new Date(call.occurred_at).toLocaleString() : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {editError ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {editError}
              </div>
            ) : null}

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeEdit}
                className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={editSaving}
                className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {editSaving ? 'Saving...' : 'Save changes'}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </Layout>
  )
}
