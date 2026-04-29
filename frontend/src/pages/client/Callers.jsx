import { useEffect, useState } from 'react'
import Layout from '../../components/Layout'
import CallerSlideOver from '../../components/CallerSlideOver'
import { api } from '../../api'

const INTENT_KEYS = ['JOB_SEEKER', 'US_STAFFING', 'SALES', 'GENERAL_INQUIRY']
const CALL_LOGS_PAGE_SIZE = 10

function resolveLabel(key, labels) {
  if (labels && labels[key]) return labels[key]
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function statusTone(status) {
  if (status === 'active') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (status === 'provisioning_failed') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (status === 'provisioning') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

export default function ClientCallers() {
  const [profile, setProfile] = useState(null)
  const [callers, setCallers] = useState([])
  const [callLogs, setCallLogs] = useState([])
  const [callLogsPage, setCallLogsPage] = useState(1)
  const [intent, setIntent] = useState('')
  const [loading, setLoading] = useState(true)
  const [callsLoading, setCallsLoading] = useState(false)
  const [intentLabels, setIntentLabels] = useState({})
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

  async function loadCalls() {
    setCallsLoading(true)
    try {
      const data = await api.meListCalls(200)
      const sorted = [...(data || [])].sort(
        (a, b) => new Date(b?.occurred_at || 0).getTime() - new Date(a?.occurred_at || 0).getTime()
      )
      setCallLogs(sorted)
      setCallLogsPage(1)
    } finally {
      setCallsLoading(false)
    }
  }

  useEffect(() => {
    Promise.all([loadProfile(), api.meGetSettings()])
      .then(([data, settingsData]) => {
        setIntentLabels(settingsData.intent_labels || {})
        if (data.status !== 'active') {
          setCallers([])
          setLoading(false)
        } else {
          loadCalls()
        }
      })
      .catch(() => setLoading(false))
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

  function endReasonBadge(reason) {
    if (reason === 'inactivity_timeout') {
      return (
        <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
          Timed out
        </span>
      )
    }
    if (reason === 'max_duration_exceeded') {
      return (
        <span className="inline-block rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700">
          Max duration
        </span>
      )
    }
    return <span className="text-xs text-slate-400">Normal</span>
  }

  const totalCallLogPages = Math.max(1, Math.ceil(callLogs.length / CALL_LOGS_PAGE_SIZE))
  const safeCallLogsPage = Math.min(callLogsPage, totalCallLogPages)
  const callLogStart = (safeCallLogsPage - 1) * CALL_LOGS_PAGE_SIZE
  const visibleCallLogs = callLogs.slice(callLogStart, callLogStart + CALL_LOGS_PAGE_SIZE)
  const failedFollowups = callLogs.filter((call) => call.followup_status === 'send_failed')
  const sentFollowups = callLogs.filter((call) => call.followup_status === 'sent')

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
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">This month</div>
              <div className="mt-3 text-3xl font-bold">{profile.usage?.monthly_minutes || 0} min</div>
            </div>
            <div className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Plan</div>
              <div className="mt-3 text-sm font-semibold text-slate-900">{profile.plan?.label || 'Starter'}</div>
              <div className="mt-1 text-xs text-slate-500">
                {profile.usage?.monthly_minutes || 0} / {profile.usage?.included_minutes || 0} included min
              </div>
            </div>
            <div className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Connected inbox</div>
              <div className="mt-3 text-sm font-semibold text-slate-900">
                {profile.gmail_connected ? profile.gmail_email || 'Connected' : 'Not connected'}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {profile.usage?.last_call_at
                  ? `Last activity ${new Date(profile.usage.last_call_at).toLocaleString()}`
                  : 'No calls yet'}
              </div>
              {profile.email_send_method && (
                <div className="mt-2 text-xs">
                  <span className="inline-block rounded px-2 py-0.5 bg-slate-100 text-slate-600">
                    {profile.email_send_method === 'oauth' && '📧 OAuth'}
                    {profile.email_send_method === 'fallback' && '⚙️ Fallback'}
                    {profile.email_send_method === 'none' && '❌ Not configured'}
                  </span>
                </div>
              )}
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
              <option value="">All types</option>
              {INTENT_KEYS.map((key) => (
                <option key={key} value={key}>
                  {resolveLabel(key, intentLabels)}
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
                            {resolveLabel(caller.last_intent, intentLabels)}
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

          <div className="mt-6">
            <h2 className="text-xl font-bold text-slate-950">Call logs</h2>
            <p className="mt-1 text-sm text-slate-500">
              Recent calls sorted newest to oldest, with timeout labels.
            </p>

            {callsLoading ? (
              <p className="mt-3 text-sm text-slate-500">Loading calls...</p>
            ) : callLogs.length === 0 ? (
              <div className="mt-3 rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-8 text-center text-sm text-slate-500">
                No calls yet.
              </div>
            ) : (
              <div className="mt-3 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-3 font-medium text-slate-700">Caller</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Intent</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Status</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Duration</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visibleCallLogs.map((call) => (
                      <tr key={call.id}>
                        <td className="px-4 py-3 font-mono text-xs text-slate-700">{call.caller_phone || '—'}</td>
                        <td className="px-4 py-3 text-slate-900">
                          {call.intent ? resolveLabel(call.intent, intentLabels) : '—'}
                        </td>
                        <td className="px-4 py-3">{endReasonBadge(call.ended_reason)}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">{call.duration_minutes || 0} min</td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {call.occurred_at ? new Date(call.occurred_at).toLocaleString() : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {callLogs.length > CALL_LOGS_PAGE_SIZE && (
              <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                <span>
                  Showing {callLogStart + 1}-{Math.min(callLogStart + CALL_LOGS_PAGE_SIZE, callLogs.length)} of {callLogs.length}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={safeCallLogsPage <= 1}
                    onClick={() => setCallLogsPage((p) => Math.max(1, p - 1))}
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span>
                    Page {safeCallLogsPage} / {totalCallLogPages}
                  </span>
                  <button
                    type="button"
                    disabled={safeCallLogsPage >= totalCallLogPages}
                    onClick={() => setCallLogsPage((p) => Math.min(totalCallLogPages, p + 1))}
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="mt-8">
            <h2 className="text-xl font-bold text-slate-950">Follow-up delivery</h2>
            <p className="mt-1 text-sm text-slate-500">
              Email sending results for post-call follow-ups.
            </p>

            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
                <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Attempts</div>
                <div className="mt-2 text-2xl font-bold text-slate-900">{sentFollowups.length + failedFollowups.length}</div>
              </div>
              <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
                <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Sent</div>
                <div className="mt-2 text-2xl font-bold text-emerald-700">{sentFollowups.length}</div>
              </div>
              <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
                <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Failed</div>
                <div className="mt-2 text-2xl font-bold text-rose-700">{failedFollowups.length}</div>
              </div>
            </div>

            {failedFollowups.length === 0 ? (
              <div className="mt-3 rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-8 text-center text-sm text-slate-500">
                No failed follow-up emails.
              </div>
            ) : (
              <div className="mt-3 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-left">
                    <tr>
                      <th className="px-4 py-3 font-medium text-slate-700">Caller</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Email</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Date</th>
                      <th className="px-4 py-3 font-medium text-slate-700">Error</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {failedFollowups.slice(0, 25).map((call) => (
                      <tr key={`failed-${call.id}`}>
                        <td className="px-4 py-3 font-mono text-xs text-slate-700">{call.caller_phone || '—'}</td>
                        <td className="px-4 py-3 text-xs text-slate-700">{call.caller_email || '—'}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {call.followup_timestamp ? new Date(call.followup_timestamp).toLocaleString() : (call.occurred_at ? new Date(call.occurred_at).toLocaleString() : '—')}
                        </td>
                        <td className="px-4 py-3 text-xs text-rose-700">{call.followup_error || 'Send failed'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
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
          intentLabels={intentLabels}
          onClose={closeDetail}
        />
      )}
    </Layout>
  )
}
