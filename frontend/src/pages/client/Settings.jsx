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
  const [form, setForm] = useState({ sms_job_seeker: '', sms_sales: '', intent_labels: {} })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [gmailLoading, setGmailLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.meProfile(), api.meGetSettings()])
      .then(([profileData, settingsData]) => {
        setProfile(profileData)
        localStorage.setItem('vc_status', profileData.status || '')
        setForm({
          sms_job_seeker: settingsData.sms_job_seeker || '',
          sms_sales: settingsData.sms_sales || '',
          intent_labels: settingsData.intent_labels || {},
        })
      })
      .catch((err) => setError(err.message || 'Unable to load settings'))
      .finally(() => setLoading(false))
  }, [])

  async function handleSave(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    setSaved(false)
    try {
      await api.meSaveSettings(form)
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
    const popup = window.open('', '_blank', 'noopener,noreferrer')
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

  return (
    <Layout>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
            Client settings
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Messaging and inbox</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Customize follow-up copy and connect Gmail so post-call emails come from the client account instead of the platform fallback.
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

      <div className="rounded-[28px] bg-white shadow-sm ring-1 ring-slate-200">
        <form onSubmit={handleSave} className="space-y-5 p-6">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Job seeker follow-up
            </label>
            <textarea
              rows={4}
              value={form.sms_job_seeker}
              onChange={(e) => setForm((current) => ({ ...current, sms_job_seeker: e.target.value }))}
              className="w-full resize-none rounded-2xl border border-slate-300 px-4 py-3 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="Use {{resume_link}} and {{company_name}} placeholders if you want them inserted automatically."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Sales lead follow-up
            </label>
            <textarea
              rows={4}
              value={form.sms_sales}
              onChange={(e) => setForm((current) => ({ ...current, sms_sales: e.target.value }))}
              className="w-full resize-none rounded-2xl border border-slate-300 px-4 py-3 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="Leave blank to inherit the admin default."
            />
          </div>

          <div className="border-t border-slate-100 pt-5">
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
