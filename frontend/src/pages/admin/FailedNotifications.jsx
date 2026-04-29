import { useState, useEffect } from 'react'
import Layout from '../../components/Layout'
import { api } from '../../api'

function channelClass(method) {
  if (method === 'email') return 'bg-sky-100 text-sky-800'
  return 'bg-amber-100 text-amber-800'
}

export default function AdminFailedNotifications() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listFailedNotifications()
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Layout>
      <div className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
          Delivery failures
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Failed notifications</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Follow-up emails that could not be delivered. Review reasons to fix underlying issues.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : items.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">
          No failed notifications — all follow-ups delivered successfully.
        </div>
      ) : (
        <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left">
              <tr>
                <th className="px-4 py-3 font-medium text-slate-700">Timestamp</th>
                <th className="px-4 py-3 font-medium text-slate-700">Caller</th>
                <th className="px-4 py-3 font-medium text-slate-700">Channel</th>
                <th className="px-4 py-3 font-medium text-slate-700">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((n) => (
                <tr key={n.id} className="align-top">
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {n.timestamp ? new Date(n.timestamp).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-700">{n.caller_number}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-[0.12em] ${channelClass(n.preferred_method)}`}>
                      {n.preferred_method}
                    </span>
                  </td>
                  <td className="px-4 py-3 max-w-xs text-xs leading-5 text-slate-600">{n.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  )
}
