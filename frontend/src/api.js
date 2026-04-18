const API_URL = import.meta.env.VITE_API_URL || ''

function getToken() {
  return localStorage.getItem('vc_token')
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  }
  if (body !== undefined) opts.body = JSON.stringify(body)

  const res = await fetch(`${API_URL}${path}`, opts)

  if (res.status === 401) {
    localStorage.removeItem('vc_token')
    localStorage.removeItem('vc_role')
    localStorage.removeItem('vc_client_id')
    localStorage.removeItem('vc_status')
    window.location.href = '/login'
    return
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const json = await res.json()
      detail = json.detail || JSON.stringify(json)
    } catch (_) {}
    throw new Error(detail)
  }

  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // Auth
  login: (email, password) =>
    request('POST', '/auth/login', { email, password }),
  signup: (data) =>
    request('POST', '/auth/signup', data),

  // Admin — clients
  listClients: () => request('GET', '/api/clients'),
  addClient: (data) => request('POST', '/api/clients', data),
  provisionClient: (id) => request('POST', `/api/clients/${id}/provision`),
  deleteClient: (id) => request('DELETE', `/api/clients/${id}`),

  // Admin — callers
  listCallers: (clientId, intent) => {
    const params = new URLSearchParams()
    if (clientId) params.set('client_id', clientId)
    if (intent) params.set('intent', intent)
    const qs = params.toString()
    return request('GET', `/api/callers${qs ? '?' + qs : ''}`)
  },
  getCaller: (phone, clientId) => {
    const params = new URLSearchParams()
    if (clientId) params.set('client_id', clientId)
    const qs = params.toString()
    return request('GET', `/api/callers/${encodeURIComponent(phone)}${qs ? '?' + qs : ''}`)
  },

  // Admin — settings
  getSettings: () => request('GET', '/api/settings'),
  saveSettings: (data) => request('POST', '/api/settings', data),

  // Admin — failed notifications
  listFailedNotifications: () => request('GET', '/api/failed-notifications'),

  // Client — /me/*
  meProfile: () => request('GET', '/me/profile'),
  meListCallers: (intent) => {
    const params = new URLSearchParams()
    if (intent) params.set('intent', intent)
    const qs = params.toString()
    return request('GET', `/me/callers${qs ? '?' + qs : ''}`)
  },
  meGetCaller: (phone) =>
    request('GET', `/me/callers/${encodeURIComponent(phone)}`),
  meGetSettings: () => request('GET', '/me/settings'),
  meSaveSettings: (data) => request('POST', '/me/settings', data),

  // Gmail OAuth
  getGmailConnectUrl: () => request('GET', '/auth/gmail/connect-url'),
  gmailOAuthUrl: (clientId) => `${API_URL}/auth/gmail/${clientId}`,
}
