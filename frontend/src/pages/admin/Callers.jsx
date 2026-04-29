import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import CallerSlideOver from '../../components/CallerSlideOver'
import { api } from '../../api'

const INTENT_KEYS = ['JOB_SEEKER', 'US_STAFFING', 'SALES', 'GENERAL_INQUIRY']

function resolveLabel(key, labels) {
  if (labels && labels[key]) return labels[key]
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function AdminCallers() {
  const [clients, setClients] = useState([])
  const [callers, setCallers] = useState([])
  const [clientId, setClientId] = useState('')
  const [intent, setIntent] = useState('')
  const [loading, setLoading] = useState(false)
  const [intentLabels, setIntentLabels] = useState({})
  const [selectedPhone, setSelectedPhone] = useState(null)
  const [selectedClientId, setSelectedClientId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    Promise.all([api.listClients(), api.getSettings()])
      .then(([clientsData, settingsData]) => {
        setClients(clientsData)
        setIntentLabels(settingsData.intent_labels || {})
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    api.listCallers(clientId || null, intent || null)
      .then(setCallers)
      .catch(() => setCallers([]))
      .finally(() => setLoading(false))
  }, [clientId, intent])

  async function openDetail(phone, callerClientId) {
    setSelectedPhone(phone)
    setSelectedClientId(callerClientId || clientId || null)
    setDetailLoading(true)
    setDetail(null)
    try {
      const data = await api.getCaller(phone, callerClientId || clientId || null)
      setDetail(data)
    } finally {
      setDetailLoading(false)
    }
  }

  function closeDetail() {
    setSelectedPhone(null)
    setSelectedClientId(null)
    setDetail(null)
  }

  const selectClass =
    'rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200'

  return (
    <Layout>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
            Admin view
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">All callers</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Browse every caller across all client accounts. Filter by client and intent.
          </p>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        <select
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className={selectClass}
        >
          <option value="">All clients</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          className={selectClass}
        >
          <option value="">All types</option>
          {INTENT_KEYS.map((key) => (
            <option key={key} value={key}>{resolveLabel(key, intentLabels)}</option>
          ))}
        </select>
      </div>

      <div className="mt-5">
        {loading ? (
          <p className="text-sm text-slate-500">Loading callers…</p>
        ) : callers.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">
            No callers found.
          </div>
        ) : (
          <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-3 font-medium text-slate-700">Phone</th>
                  <th className="px-4 py-3 font-medium text-slate-700">Name</th>
                  <th className="px-4 py-3 font-medium text-slate-700">Last intent</th>
                  <th className="px-4 py-3 font-medium text-slate-700">Last call</th>
                  <th className="px-4 py-3 font-medium text-slate-700">Intents</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {callers.map((c) => (
                  <tr
                    key={c.phone_number}
                    onClick={() => openDetail(c.phone_number, c.client_id)}
                    className="cursor-pointer hover:bg-amber-50"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">{c.phone_number}</td>
                    <td className="px-4 py-3 text-slate-900">{c.name || '—'}</td>
                    <td className="px-4 py-3">
                      {c.last_intent ? (
                        <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                          {resolveLabel(c.last_intent, intentLabels)}
                        </span>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {c.last_interaction ? new Date(c.last_interaction).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">{c.intents?.join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {(selectedPhone || detailLoading) && (
        <CallerSlideOver
          caller={detailLoading ? { phone_number: selectedPhone } : detail}
          intentLabels={intentLabels}
          onClose={closeDetail}
        />
      )}
    </Layout>
  )
}
