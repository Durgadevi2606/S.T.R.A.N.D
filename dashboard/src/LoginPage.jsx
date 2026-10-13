import React, { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

const ROLES = [
  {
    id: 'commander',
    name: 'Incident Commander',
    badge: 'ALPHA-1',
    icon: 'military_tech',
  },
  {
    id: 'analyst',
    name: 'SAR Radar Analyst',
    badge: 'BRAVO-2',
    icon: 'satellite_alt',
  },
  {
    id: 'field_ops',
    name: 'Field Operations',
    badge: 'CHARLIE-3',
    icon: 'flight_takeoff',
  },
  {
    id: 'logistics',
    name: 'Logistics Coordinator',
    badge: 'DELTA-4',
    icon: 'route',
  },
]

export default function LoginPage({ onLoginSuccess }) {
  const [callsign, setCallsign] = useState('commander.durga')
  const [apiKey, setApiKey] = useState('dev-key-change-in-production')
  const [role, setRole] = useState('commander')
  const [theater, setTheater] = useState('Track B: EMSR-927')
  const [showKey, setShowKey] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e) => {
    if (e) e.preventDefault()
    setError('')

    if (!callsign.trim()) {
      setError('Please provide an operator callsign')
      return
    }
    if (!apiKey.trim()) {
      setError('Please enter your S.T.R.A.N.D security access key')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          callsign: callsign.trim(),
          api_key: apiKey.trim(),
          role,
          theater,
        }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `Authentication failed (HTTP ${res.status})`)
      }

      const data = await res.json()
      localStorage.setItem('strand_operator', JSON.stringify(data.operator))
      localStorage.setItem('strand_api_key', apiKey.trim())

      if (onLoginSuccess) {
        onLoginSuccess(data.operator, apiKey.trim())
      }
    } catch (err) {
      console.error('Login error:', err)
      setError(err.message || 'Network error connecting to S.T.R.A.N.D API')
    } finally {
      setLoading(false)
    }
  }

  const handleQuickDemo = () => {
    setCallsign('commander.durga')
    setApiKey('dev-key-change-in-production')
    setRole('commander')
    setTheater('Track B: EMSR-927')
    setTimeout(() => {
      handleLogin()
    }, 50)
  }

  return (
    <div className="h-screen w-screen overflow-y-auto bg-[#0e0e10] text-[#e5e1e4] flex flex-col justify-between selection:bg-rose-500/30 selection:text-rose-200 relative font-sans">
      {/* Background Decorative Tactical Grid */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.035]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #ffffff 1px, transparent 1px), linear-gradient(to bottom, #ffffff 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />

      {/* Top Telemetry Header */}
      <header className="w-full border-b border-[#574143]/20 bg-[#131315]/95 backdrop-blur-md px-5 py-2.5 flex items-center justify-between z-10 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-[#201f22] border border-rose-500/40 flex items-center justify-center text-rose-300 shadow-[0_0_12px_rgba(251,113,133,0.25)] flex-shrink-0">
            <span className="material-symbols-outlined text-[16px]">satellite_alt</span>
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-[13px] tracking-wider text-[#e5e1e4] uppercase">
                S.T.R.A.N.D
              </span>
              <span className="px-1.5 py-0.2 rounded bg-[#201f22] font-mono text-[9px] text-rose-300 border border-rose-500/30 uppercase">
                ACCESS TERMINAL
              </span>
            </div>
            <span className="text-[10px] text-[#debfc1]/60 hidden sm:inline">
              Satellite Terrain Response & Network Damage
            </span>
          </div>
        </div>

        {/* Telemetry Status Pills */}
        <div className="flex items-center gap-2 text-[10px] font-mono">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#1c1b1d] border border-[#574143]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
            <span className="text-[#debfc1]/70 hidden md:inline">NEON POSTGIS:</span>
            <span className="text-emerald-400 font-semibold">CONNECTED</span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#1c1b1d] border border-[#574143]/30">
            <span className="text-[#debfc1]/70">DEFCON:</span>
            <span className="text-amber-400 font-semibold">2</span>
          </div>
          <div className="hidden md:flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#1c1b1d] border border-[#574143]/30">
            <span className="text-[#debfc1]/70">TRACK:</span>
            <span className="text-rose-300 font-semibold">B</span>
          </div>
        </div>
      </header>

      {/* Center Auth Card */}
      <main className="flex-1 flex items-center justify-center px-4 py-4 z-10">
        <div className="w-full max-w-[460px] bg-[#161518] border border-[#574143]/35 rounded-xl shadow-[0_0_40px_rgba(0,0,0,0.8)] backdrop-blur-xl overflow-hidden my-auto">
          {/* Card Title Bar */}
          <div className="px-5 py-3.5 border-b border-[#574143]/20 bg-[#1b1a1e]/80 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[17px] text-rose-400">verified_user</span>
              <span className="text-[12px] font-mono font-bold tracking-wider text-[#e5e1e4] uppercase">
                Mission Control Clearance
              </span>
            </div>
            <span className="text-[9px] font-mono text-[#debfc1]/60 px-1.5 py-0.2 rounded bg-[#201f22] border border-[#574143]/30">
              AES-256 SECURED
            </span>
          </div>

          {/* Login Form */}
          <form onSubmit={handleLogin} className="p-4 space-y-3">
            {error && (
              <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/40 text-rose-300 text-[11px] flex items-start gap-2">
                <span className="material-symbols-outlined text-[16px] text-rose-400 flex-shrink-0 mt-0.5">
                  error
                </span>
                <span className="leading-tight">{error}</span>
              </div>
            )}

            {/* Role Selection */}
            <div>
              <label className="block text-[10px] font-mono uppercase tracking-wider text-[#debfc1]/70 mb-1">
                Operational Role & Clearance
              </label>
              <div className="grid grid-cols-2 gap-1.5">
                {ROLES.map((r) => {
                  const isSelected = role === r.id
                  return (
                    <button
                      type="button"
                      key={r.id}
                      onClick={() => setRole(r.id)}
                      className={`p-2 rounded-lg border text-left transition-all cursor-pointer flex items-center justify-between ${
                        isSelected
                          ? 'bg-[#242226] border-rose-500/60 shadow-[0_0_10px_rgba(251,113,133,0.15)] text-[#e5e1e4]'
                          : 'bg-[#18171a] border-[#574143]/25 hover:border-[#574143]/50 text-[#debfc1]/70'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 overflow-hidden">
                        <span
                          className={`material-symbols-outlined text-[16px] ${
                            isSelected ? 'text-rose-400' : 'text-zinc-500'
                          }`}
                        >
                          {r.icon}
                        </span>
                        <span className="text-[11px] font-semibold truncate leading-tight">{r.name}</span>
                      </div>
                      <span
                        className={`text-[8px] font-mono px-1 py-0.2 rounded font-semibold flex-shrink-0 ml-1 ${
                          isSelected
                            ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                            : 'bg-zinc-800 text-zinc-400'
                        }`}
                      >
                        {r.badge}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Callsign Input */}
            <div>
              <label className="block text-[10px] font-mono uppercase tracking-wider text-[#debfc1]/70 mb-1">
                Operator Callsign
              </label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 text-[16px]">
                  person
                </span>
                <input
                  type="text"
                  value={callsign}
                  onChange={(e) => setCallsign(e.target.value)}
                  placeholder="e.g. commander.durga"
                  className="w-full bg-[#1b1a1d] border border-[#574143]/30 rounded-lg pl-8 pr-3 py-1.5 text-[12px] text-[#e5e1e4] focus:outline-none focus:border-rose-500/70 focus:ring-1 focus:ring-rose-500/40 font-mono transition-all placeholder:text-zinc-600"
                />
              </div>
            </div>

            {/* Security API Key Input */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[10px] font-mono uppercase tracking-wider text-[#debfc1]/70">
                  Access Security Key (X-API-KEY)
                </label>
                <span className="text-[9px] font-mono text-rose-400/80">Dev Default Loaded</span>
              </div>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 text-[16px]">
                  key
                </span>
                <input
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter security key..."
                  className="w-full bg-[#1b1a1d] border border-[#574143]/30 rounded-lg pl-8 pr-9 py-1.5 text-[12px] text-[#e5e1e4] focus:outline-none focus:border-rose-500/70 focus:ring-1 focus:ring-rose-500/40 font-mono transition-all placeholder:text-zinc-600"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {showKey ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
            </div>

            {/* Operational Theater Selection */}
            <div>
              <label className="block text-[10px] font-mono uppercase tracking-wider text-[#debfc1]/70 mb-1">
                Mission Theater AOI
              </label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 text-[16px]">
                  public
                </span>
                <select
                  value={theater}
                  onChange={(e) => setTheater(e.target.value)}
                  className="w-full bg-[#1b1a1d] border border-[#574143]/30 rounded-lg pl-8 pr-3 py-1.5 text-[11px] text-[#e5e1e4] focus:outline-none focus:border-rose-500/70 focus:ring-1 focus:ring-rose-500/40 font-mono transition-all cursor-pointer"
                >
                  <option value="Track B: EMSR-927">Track B: South Asia Monsoon Floods (EMSR-927)</option>
                  <option value="Global AOI CDSE">Global Autonomous Ingestion (Copernicus CDSE)</option>
                </select>
              </div>
            </div>

            {/* Primary Login Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 rounded-lg bg-rose-500 hover:bg-rose-600 text-white font-semibold text-[13px] flex items-center justify-center gap-2 transition-all shadow-[0_0_20px_rgba(251,113,133,0.35)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-1"
            >
              {loading ? (
                <>
                  <span className="inline-block w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                  <span>Verifying Clearance...</span>
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[17px]">login</span>
                  <span>Authenticate & Enter Command Theater</span>
                </>
              )}
            </button>

            {/* Quick Demo Access Button */}
            <div className="pt-1.5 border-t border-[#574143]/20">
              <button
                type="button"
                onClick={handleQuickDemo}
                disabled={loading}
                className="w-full py-1.5 px-3 rounded-lg bg-[#201f22] hover:bg-[#28272b] border border-[#574143]/40 text-rose-300 hover:text-rose-200 text-[11px] font-mono flex items-center justify-center gap-1.5 transition-all cursor-pointer"
              >
                <span className="material-symbols-outlined text-[15px] text-rose-400">bolt</span>
                <span>⚡ Quick Demo Authorization (Dev Key)</span>
              </button>
            </div>
          </form>

          {/* Card Footer */}
          <div className="px-4 py-2 bg-[#131315] border-t border-[#574143]/20 flex items-center justify-between text-[9px] font-mono text-[#debfc1]/50">
            <span>SESSION TIMEOUT: 8 HOURS</span>
            <span className="text-rose-400/80">STANDBY FOR SAR INGESTION</span>
          </div>
        </div>
      </main>

      {/* Page Footer */}
      <footer className="w-full border-t border-[#574143]/20 bg-[#131315]/80 px-5 py-2 flex flex-col sm:flex-row items-center justify-between text-[10px] font-mono text-[#debfc1]/50 z-10 flex-shrink-0">
        <div>Contains modified Copernicus Sentinel data (2026). OpenStreetMap contributors.</div>
        <div className="flex items-center gap-3 mt-1 sm:mt-0">
          <span>Multimodal AI Hackathon Track B</span>
          <span className="text-zinc-600">|</span>
          <span className="text-rose-400/80">S.T.R.A.N.D v1.0.0</span>
        </div>
      </footer>
    </div>
  )
}
