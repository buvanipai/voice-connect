import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { api } from '../../api'

const INTENT_KEYS = [
  { key: 'JOB_SEEKER',      placeholder: 'e.g. Job Applicant' },
  { key: 'US_STAFFING',     placeholder: 'e.g. Staffing Request' },
  { key: 'SALES',           placeholder: 'e.g. Sales Inquiry' },
  { key: 'GENERAL_INQUIRY', placeholder: 'e.g. General Question' },
]

export default function AdminSettings() {
  const [form, setForm] = useState({ sms_job_seeker: '', sms_sales: '', intent_labels: {} })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.getSettings()
      .then((data) =>
        setForm({
          sms_job_seeker: data.sms_job_seeker || '',
          sms_sales: data.sms_sales || '',
          intent_labels: data.intent_labels || {},
        })
      )
      .catch((err) => setError(err.message || 'Unable to load settings'))
      .finally(() => setLoading(false))
  }, [])

  async function handleSave(e) {
    e.preventDefault()
    setError('')
    setSaving(true)
    setSaved(false)
    try {
      await api.saveSettings(form)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Layout>
        <p className="text-sm text-slate-500">Loading…</p>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
          Platform defaults
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">SMS settings</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Platform-wide follow-up message templates. Clients can override these in their own settings.
        </p>
      </div>

      {error ? (
        <div className="mb-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <div className="rounded-[28px] bg-white shadow-sm ring-1 ring-slate-200">
        <form onSubmit={handleSave} className="space-y-5 p-6">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Job seeker follow-up
            </label>
            <textarea
              rows={4}
              value={form.sms_job_seeker}
              onChange={(e) => setForm((f) => ({ ...f, sms_job_seeker: e.target.value }))}
              className="w-full resize-none rounded-2xl border border-slate-300 px-4 py-3 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="Message sent to job seekers after their call…"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Sales lead follow-up
            </label>
            <textarea
              rows={4}
              value={form.sms_sales}
              onChange={(e) => setForm((f) => ({ ...f, sms_sales: e.target.value }))}
              className="w-full resize-none rounded-2xl border border-slate-300 px-4 py-3 text-sm focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
              placeholder="Message sent to sales leads after their call…"
            />
          </div>

          <div className="border-t border-slate-100 pt-5">
            <div className="mb-3">
              <div className="text-sm font-medium text-slate-700">Caller type labels</div>
              <p className="mt-1 text-xs text-slate-500">
                Platform-wide names for each caller category. These appear in the admin callers view.
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
                      setForm((f) => ({
                        ...f,
                        intent_labels: {
                          ...f.intent_labels,
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
              {saving ? 'Saving…' : 'Save settings'}
            </button>
            {saved ? <span className="text-sm text-emerald-600">Saved</span> : null}
          </div>
        </form>
      </div>
    </Layout>
  )
}
