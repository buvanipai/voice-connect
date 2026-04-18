import { useEffect, useState } from 'react'
import Layout from '../../components/Layout'
import CallerSlideOver from '../../components/CallerSlideOver'
import { api } from '../../api'

const INTENTS = ['', 'JOB_SEEKER', 'US_STAFFING', 'SALES', 'GENERAL_INQUIRY']

function statusTone(status) {
  if (status === 'active') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (status === 'provisioning_failed') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (status === 'provisioning') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

export default function ClientCallers() {
  const [profile, setProfile] = useState(null)
  const [callers, setCallers] = useState([])
  const [intent, setIntent] = useState('')
  const [loading, setLoading] = useState(true)
  const [selectedPhone, setSelectedPhone] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  async function loadProfile() {
    const data = await api.meProfile()
    setProfile(data)
    localStorage.setItem('vc_status', data.status || '')
    return data
  }

  async function loadCallers(selectedIntent = '') {
    setLoading(true)
    try {
      const data = await api.meListCallers(selectedIntent || null)
      setCallers(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProfile().then((data) => {
      if (data.status !== 'active') {
        setCallers([])
        setLoading(false)
      }
    })
  }, [])

  useEffect(() => {
    if (profile?.status === 'active') {
      loadCallers(intent)
    }
  }, [intent])

  async function openDetail(phone) {
    setSelectedPhone(phone)
    setDetailLoading(true)
    try {
      const data = await api.meGetCaller(phone)
      setDetail(data)
    } finally {
      setDetailLoading(false)
    }
  }

  function closeDetail() {
    setSelectedPhone(null)
    setDetail(null)
  }

  return (
    <Layout>
      {profile ? (
        <div className={`mb-6 rounded-[28px] border px-6 py-5 ${statusTone(profile.status)}`}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em]">
                Account status
              </div>
              <h1 className="mt-2 text-3xl font-bold text-slate-950">{profile.name}</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-700">
                {profile.status === 'active'
                  ? 'Your production setup is live. Use the assigned number on your website and review caller activity below.'
                  : profile.status === 'provisioning_failed'
                    ? 'Provisioning hit an error. Admin can retry from the client dashboard once the issue is fixed.'
                    : 'Your signup is in place. An admin still needs to provision your Twilio number and AI agent before live caller traffic can start.'}
              </p>
              {profile.provisioning_error ? (
                <p className="mt-3 text-sm text-rose-700">{profile.provisioning_error}</p>
              ) : null}
            </div>

            <div className="rounded-2xl bg-white/70 px-4 py-3 shadow-sm">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-500">
                Assigned number
              </div>
              <div className="mt-2 font-mono text-xl font-bold text-slate-950">
                {profile.phone_number || 'Pending'}
              </div>
              <div className="mt-2 text-xs text-slate-500">
                {profile.status === 'active'
                  ? 'Place this number on your website.'
                  : 'This appears once provisioning completes.'}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {profile?.status === 'active' ? (
        <>
          <div className="mb-5 grid gap-4 md:grid-cols-3">
            <div className="rounded-3xl bg-slate-950 p-5 text-white shadow-lg">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Total callers</div>
              <div className="mt-3 text-3xl font-bold">{profile.usage?.caller_count || 0}</div>
            </div>
            <div className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Last activity</div>
              <div className="mt-3 text-sm font-semibold text-slate-900">
                {profile.usage?.last_call_at
                  ? new Date(profile.usage.last_call_at).toLocaleString()
                  : 'No calls yet'}
              </div>
            </div>
            <div className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Connected inbox</div>
              <div className="mt-3 text-sm font-semibold text-slate-900">
                {profile.gmail_connected ? profile.gmail_email || 'Connected' : 'Not connected'}
              </div>
            </div>
          </div>

          <div className="mb-5 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-slate-950">Caller activity</h2>
              <p className="mt-1 text-sm text-slate-500">
                Review every caller associated with your AI phone number.
              </p>
            </div>
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
            >
              {INTENTS.map((item) => (
                <option key={item} value={item}>
                  {item || 'All intents'}
                </option>
              ))}
            </select>
          </div>

          {loading ? (
            <p className="text-sm text-slate-500">Loading callers...</p>
          ) : callers.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">
              No callers yet.
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
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {callers.map((caller) => (
                    <tr
                      key={caller.phone_number}
                      onClick={() => openDetail(caller.phone_number)}
                      className="cursor-pointer hover:bg-amber-50"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-slate-700">{caller.phone_number}</td>
                      <td className="px-4 py-3 text-slate-900">{caller.name || '—'}</td>
                      <td className="px-4 py-3">
                        {caller.last_intent ? (
                          <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                            {caller.last_intent}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {caller.last_interaction
                          ? new Date(caller.last_interaction).toLocaleString()
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : (
        <div className="rounded-[28px] border border-dashed border-slate-300 bg-white px-6 py-10">
          <h2 className="text-xl font-bold text-slate-950">Waiting for production provisioning</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            You can still log in and update your follow-up settings, but caller history will stay empty until your number and AI agent are provisioned by admin.
          </p>
        </div>
      )}

      {(selectedPhone || detailLoading) && (
        <CallerSlideOver
          caller={detailLoading ? { phone_number: selectedPhone } : detail}
          onClose={closeDetail}
        />
      )}
    </Layout>
  )
}
