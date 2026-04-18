import { useEffect } from 'react'

const SKIP_KEYS = new Set([
  'intents', 'phone_number', 'name', 'created_at', 'last_interaction',
  'last_intent', 'transcript_summary',
])

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function EntityRow({ label, value }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex gap-2 items-baseline">
      <dt className="w-36 shrink-0 text-xs text-slate-500 capitalize">
        {label.replaceAll('_', ' ')}
      </dt>
      <dd className="text-sm text-slate-800 break-words min-w-0">{String(value)}</dd>
    </div>
  )
}

function IntentCard({ intentName, data }) {
  if (!data || typeof data !== 'object') return null

  const summary = data.transcript_summary
  const entities = Object.entries(data).filter(([k]) => k !== 'transcript_summary')

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 inline-flex rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-amber-800">
        {intentName}
      </div>

      {entities.length > 0 && (
        <dl className="space-y-2">
          {entities.map(([k, v]) => (
            <EntityRow key={k} label={k} value={v} />
          ))}
        </dl>
      )}

      {summary && (
        <div className="mt-3 rounded-xl bg-white p-3 ring-1 ring-slate-200">
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
            Transcript summary
          </div>
          <p className="text-sm leading-6 text-slate-700">{summary}</p>
        </div>
      )}
    </div>
  )
}

export default function CallerSlideOver({ caller, onClose }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!caller) return null

  const intents = caller.intents || {}
  const intentNames = Object.keys(intents)
  const isLoading = !caller.last_intent && intentNames.length === 0 && !caller.created_at

  // Top-level fields that aren't shown via intent cards or the header
  const topLevelExtras = Object.entries(caller).filter(
    ([k]) => !SKIP_KEYS.has(k) && k !== 'phone_number'
  )

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        className="fixed inset-0 bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      />

      <div className="relative z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5">
          <div>
            <div className="font-mono text-lg font-bold text-slate-950">
              {caller.phone_number}
            </div>
            {caller.name ? (
              <div className="mt-0.5 text-sm text-slate-500">{caller.name}</div>
            ) : null}
          </div>
          <button
            onClick={onClose}
            className="ml-4 mt-0.5 rounded-xl p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-5 px-6 py-5">
          {isLoading ? (
            <div className="py-10 text-center text-sm text-slate-400">Loading caller data…</div>
          ) : (
            <>
              {/* Dates */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-400">First call</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">{formatDate(caller.created_at)}</div>
                </div>
                <div className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Last interaction</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">{formatDate(caller.last_interaction)}</div>
                </div>
              </div>

              {/* Top-level entities (e.g. contact_preference, email_address etc.) */}
              {topLevelExtras.length > 0 && (
                <dl className="space-y-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  {topLevelExtras.map(([k, v]) => (
                    <EntityRow key={k} label={k} value={v} />
                  ))}
                </dl>
              )}

              {/* Per-intent cards */}
              {intentNames.length > 0 ? (
                <div className="space-y-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                    Intent history
                  </div>
                  {intentNames.map((name) => (
                    <IntentCard key={name} intentName={name} data={intents[name]} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400">No intent data recorded yet.</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
