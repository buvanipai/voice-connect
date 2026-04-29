import { useEffect, useState } from 'react'
import Layout from '../../components/Layout'
import { api } from '../../api'

const INTENT_KEYS = [
  { key: 'JOB_SEEKER',      placeholder: 'e.g. Job Applicant' },
  { key: 'US_STAFFING',     placeholder: 'e.g. Staffing Request' },
  { key: 'SALES',           placeholder: 'e.g. Sales Inquiry' },
  { key: 'GENERAL_INQUIRY', placeholder: 'e.g. General Question' },
]

export default function ClientSettings() {
  const [profile, setProfile] = useState(null)
  const [form, setForm] = useState({
    intent_labels: {},
    forward_to_number: '',
    inactivity_timeout_seconds: 28,
    max_call_duration_seconds: 300,
    channels: { email: true },
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [gmailLoading, setGmailLoading] = useState(false)
  const [error, setError] = useState('')
  const [agentPrompt, setAgentPrompt] = useState('')
  const [agentLoading, setAgentLoading] = useState(false)
  const [agentSaving, setAgentSaving] = useState(false)
  const [agentSaved, setAgentSaved] = useState(false)
  const [agentError, setAgentError] = useState('')

  useEffect(() => {
    Promise.all([api.meProfile(), api.meGetSettings()])
      .then(([profileData, settingsData]) => {
        setProfile(profileData)
        localStorage.setItem('vc_status', profileData.status || '')
        setForm({
          intent_labels: settingsData.intent_labels || {},
          forward_to_number: settingsData.forward_to_number || '',
          inactivity_timeout_seconds: settingsData.inactivity_timeout_seconds || 28,
          max_call_duration_seconds: settingsData.max_call_duration_seconds || 300,
          channels: {
            email: settingsData.channels?.email !== false,
          },
        })
      })
      .catch((err) => setError(err.message || 'Unable to load settings'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (profile?.status !== 'active') return
    setAgentLoading(true)
    api.meGetAgent()
      .then((data) => setAgentPrompt(data.prompt || ''))
      .catch((err) => setAgentError(err.message || 'Unable to load agent'))
      .finally(() => setAgentLoading(false))
  }, [profile?.status])

  async function handleSaveAgent(e) {
    e.preventDefault()
    setAgentError('')
    setAgentSaving(true)
    setAgentSaved(false)
    try {
      await api.meSaveAgent({ prompt: agentPrompt })
      setAgentSaved(true)
      setTimeout(() => setAgentSaved(false), 2500)
    } catch (err) {
      setAgentError(err.message || 'Unable to save agent prompt')
    } finally {
      setAgentSaving(false)
    }
  }

  async function handleSave(e) {
    e.preventDefault()
    setError('')

    const inactivityTimeout = Number(form.inactivity_timeout_seconds)
    const maxDurationSeconds = Number(form.max_call_duration_seconds)
    if (!Number.isFinite(inactivityTimeout) || inactivityTimeout < 15 || inactivityTimeout > 60) {
      setError('End call after silence must be between 15 and 60 seconds.')
      return
    }
    if (!Number.isFinite(maxDurationSeconds) || maxDurationSeconds < 120 || maxDurationSeconds > 600) {
      setError('Maximum call length must be between 2 and 10 minutes.')
      return
    }

    setSaving(true)
    setSaved(false)
    try {
      await api.meSaveSettings({
        ...form,
        inactivity_timeout_seconds: inactivityTimeout,
        max_call_duration_seconds: maxDurationSeconds,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function connectGmail() {
    setError('')
    setGmailLoading(true)
    const popup = window.open('', '_blank')
    try {
      const data = await api.getGmailConnectUrl()
      if (popup) {
        popup.location.href = data.url
      } else {
        window.location.href = data.url
      }
    } catch (err) {
      if (popup) popup.close()
      setError(err.message || 'Unable to start Gmail connection')
    } finally {
      setGmailLoading(false)
    }
  }

  if (loading) {
    return (
      <Layout>
        <p className="text-sm text-slate-500">Loading...</p>
      </Layout>
    )
  }

  const gmailDisconnected = profile && !profile.gmail_connected

  return (
    <Layout>
      {gmailDisconnected ? (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-300 bg-rose-50 px-5 py-4 text-sm text-rose-800 shadow-sm">
          <div>
            <div className="font-semibold">Gmail not connected.</div>
            <div className="mt-1 text-xs leading-5 text-rose-700">
              Follow-up emails will fall back to the platform mailbox until you connect Gmail.
            </div>
          </div>
          <button
            type="button"
            disabled={gmailLoading || profile?.status !== 'active'}
            onClick={connectGmail}
            className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {gmailLoading ? 'Opening...' : 'Connect Gmail'}
          </button>
        </div>
      ) : null}

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
            Client settings
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Email and inbox</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Connect Gmail and manage how your AI handles calls, transfers, and follow-up emails.
          </p>
        </div>
        <div className="rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Status</div>
          <div className="mt-2 text-sm font-semibold capitalize text-slate-900">
            {(profile?.status || 'pending').replaceAll('_', ' ')}
          </div>
        </div>
      </div>

      {error ? (
        <div className="mb-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="mb-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-[28px] bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Assigned number</div>
          <div className="mt-3 font-mono text-2xl font-bold text-slate-950">
            {profile?.phone_number || 'Pending'}
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {profile?.status === 'active'
              ? 'This is the number your team should place on the website.'
              : 'The number will appear here once admin finishes provisioning.'}
          </p>
        </div>

        <div className="rounded-[28px] bg-slate-950 p-6 text-white shadow-lg">
          <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Gmail</div>
          <div className="mt-3 text-lg font-semibold">
            {profile?.gmail_connected ? profile.gmail_email || 'Connected' : 'Not connected'}
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            {profile?.status === 'active'
              ? 'Connect the client inbox so email follow-ups send from the right mailbox.'
              : 'Gmail becomes available after provisioning is complete.'}
          </p>
          <button
            type="button"
            disabled={gmailLoading || profile?.status !== 'active'}
            onClick={connectGmail}
            className="mt-5 rounded-xl bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {gmailLoading
              ? 'Opening...'
              : profile?.gmail_connected
                ? 'Reconnect Gmail'
                : 'Connect Gmail'}
          </button>
        </div>
      </div>

      {profile?.status === 'active' ? (
        <div className="mb-6 rounded-[28px] bg-white shadow-sm ring-1 ring-slate-200">
          <form onSubmit={handleSaveAgent} className="space-y-4 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-slate-900">Agent personality</div>
                <p className="mt-1 text-xs text-slate-500">
                  This is the full prompt your AI agent follows on every call. Describe your business, tone, and what callers are likely to ask.
                </p>
              </div>
              {agentSaved ? (
                <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
                  Saved
                </span>
              ) : null}
            </div>
            {agentError ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {agentError}
              </div>
            ) : null}
            <textarea
              rows={12}
              value={agentPrompt}
              onChange={(e) => setAgentPrompt(e.target.value)}
              disabled={agentLoading}
              className="w-full resize-y rounded-2xl border border-slate-300 px-4 py-3 font-mono text-xs leading-6 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200 disabled:bg-slate-50"
              placeholder={agentLoading ? 'Loading agent prompt...' : 'You are a friendly phone agent for ...'}
            />
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={agentLoading || agentSaving || !agentPrompt.trim()}
                className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {agentSaving ? 'Saving...' : 'Save prompt'}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      <div className="mb-6 rounded-[28px] bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div className="text-sm font-semibold text-slate-900">Call handling</div>
        <p className="mt-1 text-xs text-slate-500">
          Control follow-up email delivery and where live calls forward when the caller wants a human.
        </p>

        <div className="mt-5 space-y-4">
          <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div>
              <div className="text-sm font-semibold text-slate-900">Email follow-ups</div>
              <div className="text-xs text-slate-500">
                Agent offers to email a summary after the caller confirms.
              </div>
            </div>
            <label className="relative inline-flex cursor-pointer items-center">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={form.channels.email}
                onChange={(e) =>
                  setForm((current) => ({
                    ...current,
                    channels: { ...current.channels, email: e.target.checked },
                  }))
                }
              />
              <span className="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-amber-500" />
              <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition peer-checked:translate-x-5" />
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Forward calls to
            </label>
            <input
              type="tel"
              placeholder="+13125551234"
              value={form.forward_to_number}
              onChange={(e) =>
                setForm((current) => ({ ...current, forward_to_number: e.target.value }))
              }
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
            />
            <p className="mt-1 text-xs text-slate-500">
              E.164 format. If empty, the agent takes a message instead of transferring.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              End call after X seconds of silence
            </label>
            <input
              type="number"
              min={15}
              max={60}
              value={form.inactivity_timeout_seconds}
              onChange={(e) =>
                setForm((current) => ({
                  ...current,
                  inactivity_timeout_seconds: e.target.value,
                }))
              }
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
            />
            <p className="mt-1 text-xs text-slate-500">Allowed range: 15-60 seconds.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Maximum call length (minutes)
            </label>
            <input
              type="number"
              min={2}
              max={10}
              value={Math.round(Number(form.max_call_duration_seconds || 0) / 60)}
              onChange={(e) => {
                const minutes = Number(e.target.value)
                setForm((current) => ({
                  ...current,
                  max_call_duration_seconds: Number.isFinite(minutes) ? minutes * 60 : '',
                }))
              }}
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
            />
            <p className="mt-1 text-xs text-slate-500">Allowed range: 2-10 minutes.</p>
          </div>
        </div>
      </div>

      <div className="rounded-[28px] bg-white shadow-sm ring-1 ring-slate-200">
        <form onSubmit={handleSave} className="space-y-5 p-6">
          <div>
            <div className="mb-3">
              <div className="text-sm font-medium text-slate-700">Caller type labels</div>
              <p className="mt-1 text-xs text-slate-500">
                Rename caller categories to match your business. These labels appear in your callers table and detail views.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {INTENT_KEYS.map(({ key, placeholder }) => (
                <div key={key}>
                  <label className="block text-xs text-slate-500 mb-1">
                    {key.replace(/_/g, ' ')}
                  </label>
                  <input
                    type="text"
                    value={form.intent_labels[key] || ''}
                    onChange={(e) =>
                      setForm((current) => ({
                        ...current,
                        intent_labels: {
                          ...current.intent_labels,
                          [key]: e.target.value,
                        },
                      }))
                    }
                    placeholder={placeholder}
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? 'Saving...' : 'Save settings'}
            </button>
            {saved ? <span className="text-sm text-emerald-600">Saved</span> : null}
          </div>
        </form>
      </div>
    </Layout>
  )
}
