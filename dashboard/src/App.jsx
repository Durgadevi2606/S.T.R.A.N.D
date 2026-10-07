import { useState, useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const API_BASE = 'http://localhost:8000/api/v1'
const API_KEY = 'dev-key-change-in-production'

const LAYER_COLORS = {
  flood: { fill: '#38bdf8', stroke: '#0284c7' },
  roads_intact: '#34d399',
  roads_partial: '#fbbf24',
  roads_severed: '#fb7185',
  bridges_intact: '#34d399',
  bridges_damaged: '#fbbf24',
  bridges_destroyed: '#fb7185',
  settlements_connected: '#34d399',
  settlements_degraded: '#fbbf24',
  settlements_isolated: '#fb7185',
  hlz: '#c084fc',
  ponding: '#f472b6',
}

const BASEMAP_CONFIGS = {
  satellite: {
    id: 'satellite',
    name: 'Satellite',
    icon: 'satellite_alt',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Maxar, Earthstar Geographics',
    maxZoom: 19,
  },
  dark: {
    id: 'dark',
    name: 'Dark Canvas',
    icon: 'radar',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; DeLorme, NAVTEQ',
    maxZoom: 16,
  },
  osm: {
    id: 'osm',
    name: 'Streets',
    icon: 'terrain',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  },
}

const NEPAL_CENTER = [27.88, 85.92]
const NEPAL_ZOOM = 11

export default function App() {
  const mapContainer = useRef(null)
  const map = useRef(null)
  const layerGroups = useRef({})
  const baseTileLayer = useRef(null)

  // State
  const [basemap, setBasemap] = useState('satellite')
  const [analyses, setAnalyses] = useState([])
  const [selectedAnalysis, setSelectedAnalysis] = useState(null)
  const [analysisData, setAnalysisData] = useState(null)
  const [activeLayers, setActiveLayers] = useState({
    flood: true,
    roads: true,
    bridges: true,
    settlements: true,
    hlz: true,
    ponding: false,
  })
  const [sidebarTab, setSidebarTab] = useState('layers')
  const [loading, setLoading] = useState(false)
  const [settlementsList, setSettlementsList] = useState([])
  const [hlzList, setHlzList] = useState([])

  // Copilot State
  const [copilotQuery, setCopilotQuery] = useState('')
  const [copilotResponse, setCopilotResponse] = useState(null)
  const [copilotLoading, setCopilotLoading] = useState(false)

  // Modals & Actions
  const [showSmsModal, setShowSmsModal] = useState(false)
  const [smsAlerts, setSmsAlerts] = useState([])
  const [smsLoading, setSmsLoading] = useState(false)
  const [smsText, setSmsText] = useState('')
  const [copiedSms, setCopiedSms] = useState(false)

  // SAR Radar Upload Modal
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadAoiName, setUploadAoiName] = useState('Koshi Basin Radar Ingestion')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')

  // Toast
  const [toast, setToast] = useState({ show: false, message: '' })

  const showToast = (message) => {
    setToast({ show: true, message })
    setTimeout(() => setToast({ show: false, message: '' }), 3500)
  }

  // Initialize Map
  useEffect(() => {
    if (map.current || !mapContainer.current) return

    const m = L.map(mapContainer.current, {
      center: NEPAL_CENTER,
      zoom: NEPAL_ZOOM,
      zoomControl: false,
    })

    L.control.zoom({ position: 'topright' }).addTo(m)
    L.control.scale({ imperial: false, position: 'bottomright' }).addTo(m)

    const initialCfg = BASEMAP_CONFIGS.satellite
    const initialTile = L.tileLayer(initialCfg.url, {
      attribution: initialCfg.attribution,
      maxZoom: initialCfg.maxZoom,
    }).addTo(m)

    baseTileLayer.current = initialTile
    map.current = m

    fetchAnalyses()

    return () => {
      m.remove()
      map.current = null
    }
  }, [])

  // Switch Basemap
  const switchBasemap = (type) => {
    if (!map.current || !BASEMAP_CONFIGS[type]) return
    if (baseTileLayer.current && map.current.hasLayer(baseTileLayer.current)) {
      map.current.removeLayer(baseTileLayer.current)
    }
    const cfg = BASEMAP_CONFIGS[type]
    const newTile = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
    })
    newTile.addTo(map.current)
    newTile.bringToBack()
    baseTileLayer.current = newTile
    setBasemap(type)
    showToast(`Basemap switched to ${cfg.name}`)
  }

  // Fetch list of analyses
  const fetchAnalyses = async () => {
    try {
      const res = await fetch(`${API_BASE}/analysis`, {
        headers: { 'X-API-Key': API_KEY },
      })
      if (res.ok) {
        const data = await res.json()
        const list = data.analyses || []
        setAnalyses(list)
        if (list.length > 0 && !selectedAnalysis) {
          selectAnalysis(list[0].analysis_id)
        }
      }
    } catch (e) {
      console.error('Failed to fetch analyses:', e)
    }
  }

  // Select Analysis
  const selectAnalysis = async (analysisId) => {
    setSelectedAnalysis(analysisId)
    setLoading(true)

    try {
      const detailRes = await fetch(`${API_BASE}/analysis/${analysisId}`, {
        headers: { 'X-API-Key': API_KEY },
      })
      if (detailRes.ok) {
        const detail = await detailRes.json()
        setAnalysisData(detail)
      }
      await loadAllLayers(analysisId)
      showToast(`Loaded analysis: ${analysisId}`)
    } catch (e) {
      console.error('Failed to load analysis:', e)
      showToast('Error loading analysis details')
    } finally {
      setLoading(false)
    }
  }

  // Load All Layers for Selected Analysis
  const loadAllLayers = async (analysisId) => {
    if (!map.current) return

    Object.values(layerGroups.current).forEach((lg) => {
      if (map.current.hasLayer(lg)) {
        map.current.removeLayer(lg)
      }
    })
    layerGroups.current = {}

    const layerEndpoints = [
      { name: 'flood', url: `${API_BASE}/layers/${analysisId}/flood` },
      { name: 'roads', url: `${API_BASE}/layers/${analysisId}/roads` },
      { name: 'bridges', url: `${API_BASE}/layers/${analysisId}/bridges` },
      { name: 'settlements', url: `${API_BASE}/layers/${analysisId}/settlements` },
      { name: 'hlz', url: `${API_BASE}/layers/${analysisId}/hlz` },
      { name: 'ponding', url: `${API_BASE}/layers/${analysisId}/ponding` },
    ]

    for (const ep of layerEndpoints) {
      try {
        const res = await fetch(ep.url, { headers: { 'X-API-Key': API_KEY } })
        if (!res.ok) continue
        const geojson = await res.json()

        if (ep.name === 'settlements') {
          setSettlementsList(geojson.features || [])
        }
        if (ep.name === 'hlz') {
          setHlzList(geojson.features || [])
        }

        const leafletLayer = createLeafletLayer(ep.name, geojson)
        layerGroups.current[ep.name] = leafletLayer

        if (activeLayers[ep.name] && leafletLayer) {
          map.current.addLayer(leafletLayer)
        }
      } catch (e) {
        console.error(`Failed to load layer ${ep.name}:`, e)
      }
    }
  }

  // Create Styled Leaflet Layer
  const createLeafletLayer = (layerName, geojson) => {
    switch (layerName) {
      case 'flood':
        return L.geoJSON(geojson, {
          style: {
            color: '#38bdf8',
            weight: 2,
            fillColor: '#0284c7',
            fillOpacity: 0.45,
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            const area = p.area_km2 || (p.area_m2 ? (p.area_m2 / 1e6).toFixed(2) : '—')
            const conf = p.confidence ? `${(p.confidence * 100).toFixed(0)}%` : 'Verified'
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🌊 Flood Inundation Extent</strong>
                Area: <b>${area} km²</b><br/>
                Confidence: <b>${conf}</b><br/>
                Method: ${p.detection_method || 'SAR Backscatter'}
              </div>
            `)
          },
        })

      case 'roads':
        return L.geoJSON(geojson, {
          style: (feature) => {
            const dmg = feature.properties?.damage_class
            const color =
              dmg === 'severed'
                ? LAYER_COLORS.roads_severed
                : dmg === 'partially_flooded'
                ? LAYER_COLORS.roads_partial
                : LAYER_COLORS.roads_intact
            const weight = dmg === 'severed' ? 3.5 : dmg === 'partially_flooded' ? 2.5 : 1.5
            return { color, weight, opacity: 0.95 }
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🛣️ ${p.name || 'Road Segment'}</strong>
                Damage: <b style="color: ${p.damage_class === 'severed' ? '#fb7185' : '#34d399'}">${(p.damage_class || 'UNKNOWN').toUpperCase()}</b><br/>
                Length: ${Math.round(p.length_m || 0)}m<br/>
                Flood Overlap: ${p.flood_intersection_ratio ? `${(p.flood_intersection_ratio * 100).toFixed(0)}%` : '0%'}
              </div>
            `)
          },
        })

      case 'bridges':
        return L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => {
            const dmg = feature.properties?.damage_class
            const color =
              dmg === 'destroyed'
                ? LAYER_COLORS.bridges_destroyed
                : dmg === 'damaged'
                ? LAYER_COLORS.bridges_damaged
                : LAYER_COLORS.bridges_intact
            return L.circleMarker(latlng, {
              radius: 7,
              fillColor: color,
              color: '#0e0e10',
              weight: 2,
              fillOpacity: 0.95,
            })
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🌉 ${p.name || 'Bridge Crossing'}</strong>
                Damage: <b style="color: ${p.damage_class === 'destroyed' ? '#fb7185' : '#34d399'}">${(p.damage_class || 'UNKNOWN').toUpperCase()}</b><br/>
                Buffer Flood: ${p.buffer_flood_ratio ? `${(p.buffer_flood_ratio * 100).toFixed(0)}%` : '0%'}
              </div>
            `)
          },
        })

      case 'settlements':
        return L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => {
            const iso = feature.properties?.isolation_status
            const color =
              iso === 'isolated'
                ? LAYER_COLORS.settlements_isolated
                : iso === 'degraded'
                ? LAYER_COLORS.settlements_degraded
                : LAYER_COLORS.settlements_connected
            const urgency = feature.properties?.urgency_score || 0
            const radius = 6 + urgency * 6
            return L.circleMarker(latlng, {
              radius,
              fillColor: color,
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95,
            })
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🏘️ ${p.name || 'Settlement'}</strong>
                Status: <b style="color: ${p.isolation_status === 'isolated' ? '#fb7185' : '#34d399'}">${(p.isolation_status || 'UNKNOWN').toUpperCase()}</b><br/>
                Population: <b>${p.estimated_population?.toLocaleString() ?? '—'}</b><br/>
                Urgency Score: <b style="color: #fb7185;">${typeof p.urgency_score === 'number' ? p.urgency_score.toFixed(2) : '—'}</b><br/>
                Clinic: ${p.has_clinic ? '✅ Operational' : '❌ None'}
              </div>
            `)
          },
        })

      case 'hlz':
        return L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => {
            return L.circleMarker(latlng, {
              radius: 8,
              fillColor: LAYER_COLORS.hlz,
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.9,
            })
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🚁 Helicopter Landing Zone</strong>
                Elevation: <b>${Math.round(p.elevation_m || 0)}m ASL</b><br/>
                Slope: <b>${p.avg_slope_deg ? p.avg_slope_deg.toFixed(1) : '—'}°</b><br/>
                Clearance: <b>${Math.round(p.area_m2 || 0)} m²</b><br/>
                Surface: ${p.surface_estimate ? p.surface_estimate.replace('_', ' ') : 'natural terrain'}
              </div>
            `)
          },
        })

      case 'ponding':
        return L.geoJSON(geojson, {
          style: {
            color: LAYER_COLORS.ponding,
            weight: 2,
            fillColor: LAYER_COLORS.ponding,
            fillOpacity: 0.35,
          },
          onEachFeature: (feature, layer) => {
            layer.bindPopup(`<div class="leaflet-popup-card"><strong>💧 Saturated Soil / Ponding Zone</strong></div>`)
          },
        })

      default:
        return null
    }
  }

  // Toggle Layer Visibility
  const toggleLayer = (layerName) => {
    setActiveLayers((prev) => {
      const nextActive = !prev[layerName]
      const updated = { ...prev, [layerName]: nextActive }
      const lg = layerGroups.current[layerName]
      if (lg && map.current) {
        if (nextActive) {
          map.current.addLayer(lg)
        } else {
          map.current.removeLayer(lg)
        }
      }
      return updated
    })
    showToast(`Layer ${layerName.toUpperCase()} toggled`)
  }

  // Copilot Query
  const handleCopilotQuery = async (queryText) => {
    const q = queryText || copilotQuery
    if (!q.trim() || !selectedAnalysis) return
    setCopilotLoading(true)
    setCopilotResponse(null)

    try {
      const res = await fetch(`${API_BASE}/copilot/${selectedAnalysis}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({ query: q, language: 'en' }),
      })
      if (res.ok) {
        const data = await res.json()
        setCopilotResponse(data)
      } else {
        setCopilotResponse({ answer: 'Tactical spatial engine could not complete query.', confidence: 'low' })
      }
    } catch (e) {
      setCopilotResponse({ answer: `Query execution error: ${e.message}`, confidence: 'low' })
    } finally {
      setCopilotLoading(false)
    }
  }

  // Export SitRep PDF
  const exportSitRep = async () => {
    if (!selectedAnalysis) return
    showToast('Compiling SitRep PDF from spatial database...')
    try {
      const res = await fetch(`${API_BASE}/export/${selectedAnalysis}/sitrep`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `sitrep_${selectedAnalysis.slice(0, 16)}.pdf`
        a.click()
        URL.revokeObjectURL(url)
        showToast('SitRep PDF downloaded!')
      }
    } catch (e) {
      console.error('Export failed:', e)
      showToast('SitRep export failed')
    }
  }

  // Open SMS/LoRa Modal
  const openSmsModal = async (villageName = null) => {
    if (!selectedAnalysis) return
    setSmsLoading(true)
    setShowSmsModal(true)

    try {
      const res = await fetch(`${API_BASE}/export/${selectedAnalysis}/sms`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify({ max_chars: 140 }),
      })
      if (res.ok) {
        const data = await res.json()
        setSmsAlerts(data || [])
        if (villageName) {
          setSmsText(`[STRAND ALERT] ${villageName} cut-off. Ground evacuation blocked. Airdrop rendezvous at designated HLZ. Move to high ground.`)
        } else if (data && data.length > 0) {
          setSmsText(data[0].alert_text)
        }
      }
    } catch (e) {
      console.error('Failed to get SMS alerts:', e)
    } finally {
      setSmsLoading(false)
    }
  }

  // Real Upload SAR File Handler
  const handleSarUpload = async () => {
    if (!uploadFile) {
      showToast('Please select a radar image file')
      return
    }

    setUploading(true)
    setUploadProgress('Uploading radar imagery...')

    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('aoi_name', uploadAoiName)
      formData.append('bbox_west', '85.80')
      formData.append('bbox_south', '27.70')
      formData.append('bbox_east', '86.05')
      formData.append('bbox_north', '28.05')

      setUploadProgress('Calibrating backscatter & running speckle filter...')

      const res = await fetch(`${API_BASE}/analysis/upload-sar`, {
        method: 'POST',
        headers: {
          'X-API-Key': API_KEY,
        },
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Upload failed')
      }

      setUploadProgress('Persisting detected flood polygons & triage network into Neon PG...')
      const newAnalysis = await res.json()

      showToast(`SAR Ingestion Complete! Flood: ${newAnalysis.flood_area_km2} km²`)
      setShowUploadModal(false)
      setUploadFile(null)

      // Refresh analyses and switch to the newly created one!
      await fetchAnalyses()
      selectAnalysis(newAnalysis.analysis_id)
    } catch (e) {
      console.error('Upload error:', e)
      showToast(`Upload failed: ${e.message}`)
    } finally {
      setUploading(false)
      setUploadProgress('')
    }
  }

  const stats = analysisData?.summary || {}

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      {/* ─── TOP NAVIGATION HEADER ─── */}
      <header className="h-14 bg-[#0e0e10]/95 backdrop-blur-md border-b border-[#574143]/30 px-4 flex items-center justify-between z-30 flex-shrink-0 shadow-[0_1px_8px_rgba(0,0,0,0.5)]">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#201f22] border border-rose-500/30 flex items-center justify-center text-rose-300 shadow-[0_0_10px_rgba(251,113,133,0.15)]">
              <span className="material-symbols-outlined text-[18px]">satellite_alt</span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-[15px] tracking-wider text-[#e5e1e4] uppercase font-mono">S.T.R.A.N.D</span>
                <span className="px-1.5 py-0.2 rounded bg-[#2a2a2c] border border-rose-500/30 font-mono text-[10px] text-rose-300 font-semibold">
                  v4.2-PROD
                </span>
              </div>
              <span className="text-[11px] text-[#debfc1]/70 leading-none">Disaster Intelligence Engine</span>
            </div>
          </div>

          <div className="h-5 w-px bg-zinc-800 hidden sm:block"></div>

          {/* Analysis Selection Dropdown */}
          {analyses.length > 0 && (
            <div className="flex items-center gap-1.5 bg-[#201f22] px-2.5 py-1 rounded-md border border-[#574143]/40 hover:border-rose-500/50 transition-colors">
              <span className="material-symbols-outlined text-rose-400 text-[16px]">crisis_alert</span>
              <select
                className="bg-transparent text-[12px] text-[#e5e1e4] font-medium outline-none cursor-pointer pr-1"
                value={selectedAnalysis || ''}
                onChange={(e) => selectAnalysis(e.target.value)}
              >
                {analyses.map((a) => (
                  <option key={a.analysis_id} value={a.analysis_id} className="bg-[#1c1b1d] text-[#e5e1e4]">
                    {a.analysis_id.slice(0, 24)} • {a.flood_area_km2 ? `${a.flood_area_km2} km²` : a.status}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Header Right Status & Actions */}
        <div className="flex items-center gap-3">
          <div className="hidden md:flex items-center gap-2 bg-[#1c1b1d] px-3 py-1 rounded-full border border-zinc-800 text-[11px]">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-[#debfc1]/80 font-mono">NEON PG: <span className="text-emerald-400 font-semibold">ONLINE</span></span>
            </div>
            <div className="h-3 w-px bg-zinc-800"></div>
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-400"></span>
              </span>
              <span className="text-[#debfc1]/80 font-mono">SENTINEL SAR: <span className="text-rose-300 font-semibold">LIVE</span></span>
            </div>
          </div>

          {/* Upload SAR Radar Data CTA */}
          <button
            onClick={() => setShowUploadModal(true)}
            className="flex items-center gap-1.5 bg-[#201f22] hover:bg-[#2a2a2c] text-rose-300 border border-rose-500/50 hover:border-rose-400 px-3 py-1.5 rounded-md transition-all shadow-[0_0_12px_rgba(251,113,133,0.18)] cursor-pointer text-[12px] font-semibold tracking-wide uppercase"
          >
            <span className="material-symbols-outlined text-[16px]">radar</span>
            <span>Upload SAR Radar Data</span>
          </button>
        </div>
      </header>

      {/* ─── TOP 4 STATS OVERVIEW CARDS ─── */}
      <section className="bg-[#0e0e10] border-b border-[#574143]/20 px-4 py-2.5 flex-shrink-0 z-20">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* Card 1: Flood Extent */}
          <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70">
                <span className="material-symbols-outlined text-rose-400 text-[16px]">water_damage</span>
                <span>Flood Extent</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-rose-300 border border-rose-500/20">
                SAR MAPPED
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                {stats.flood_area_km2 ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">km²</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/20">
                Critical Level
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
              <span>Basin Sensor Active</span>
              <span className="text-rose-300">Peak +0.42m</span>
            </div>
          </div>

          {/* Card 2: Severed Roads */}
          <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70">
                <span className="material-symbols-outlined text-rose-400 text-[16px]">alt_route</span>
                <span>Severed Roads</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-rose-300 border border-rose-500/20">
                Arteries Cut
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                {stats.roads_severed_km ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">km</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-rose-300 border border-zinc-700">
                Highway Down
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
              <span>Major Arteries Down</span>
              <span className="text-rose-400 font-medium">Impassable</span>
            </div>
          </div>

          {/* Card 3: Bridges Destroyed */}
          <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70">
                <span className="material-symbols-outlined text-amber-400 text-[16px]">warning</span>
                <span>Bridges Lost</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-amber-300 border border-amber-500/20">
                Collapses
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                {stats.bridges_destroyed ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">Spans</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
                {stats.bridges_damaged ?? 0} Damaged
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
              <span>Main Corridor Crossings</span>
              <span className="text-amber-400 font-semibold">Compromised</span>
            </div>
          </div>

          {/* Card 4: Isolated Settlements */}
          <div className="bg-[#1c1b1d] p-3 rounded-md border border-rose-500/30 hover:border-rose-500/60 transition-all flex flex-col justify-between shadow-[0_0_12px_rgba(251,113,133,0.08)]">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider text-rose-300">
                <span className="material-symbols-outlined text-rose-400 text-[16px]">groups_2</span>
                <span>Isolated Villages</span>
              </div>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse font-semibold">
                CRITICAL
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-rose-300">
                {stats.settlements_isolated ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">Villages</span>
              </div>
              <span className="text-[11px] font-mono text-[#e5e1e4] font-semibold">
                {stats.settlements_degraded ? `${stats.settlements_degraded} Degraded` : 'Zero Ground Access'}
              </span>
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
              <span>Air Evac Priority</span>
              <span className="text-rose-400 font-bold">HLZ Reach Ready</span>
            </div>
          </div>
        </div>
      </section>

      {/* ─── MAIN WORKSPACE (SIDEBAR + FULL-BLEED MAP) ─── */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden relative">
        {/* LEFT WORKSPACE SIDEBAR */}
        <aside className="w-full lg:w-[410px] xl:w-[430px] flex-shrink-0 bg-[#0e0e10] border-r border-[#574143]/20 flex flex-col z-20 overflow-hidden">
          {/* Sidebar Tab Header */}
          <div className="flex border-b border-[#574143]/20 bg-[#1c1b1d] p-1.5 gap-1 flex-shrink-0">
            {[
              { id: 'layers', icon: 'layers', label: 'Layers' },
              { id: 'triage', icon: 'emergency', label: `Triage (${settlementsList.length})` },
              { id: 'hlz', icon: 'flight_takeoff', label: `HLZ (${hlzList.length})` },
              { id: 'copilot', icon: 'smart_toy', label: 'Copilot' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSidebarTab(tab.id)}
                className={`flex-1 py-1.5 px-2 rounded-md font-mono text-[11px] tracking-wider uppercase transition-all flex items-center justify-center gap-1 cursor-pointer ${
                  sidebarTab === tab.id
                    ? 'bg-[#2a2a2c] text-rose-300 border border-rose-500/40 shadow-sm font-semibold'
                    : 'text-[#debfc1]/70 hover:text-[#e5e1e4] hover:bg-[#201f22]'
                }`}
              >
                <span className="material-symbols-outlined text-[15px]">{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </div>

          {/* TAB 1: LAYERS & SATELLITE OPS */}
          {sidebarTab === 'layers' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* Basemap Canvas Selector */}
              <div className="bg-[#201f22] p-3 rounded-md border border-[#574143]/30">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-[#debfc1]/70">Basemap Canvas</span>
                  <span className="font-mono text-[11px] text-rose-300">WGS84 / EPSG:4326</span>
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  {Object.values(BASEMAP_CONFIGS).map((b) => (
                    <button
                      key={b.id}
                      onClick={() => switchBasemap(b.id)}
                      className={`px-2 py-1.5 rounded-md font-mono text-[11px] flex flex-col items-center gap-1 text-center transition-colors cursor-pointer ${
                        basemap === b.id
                          ? 'bg-[#2a2a2c] border border-rose-500/50 text-rose-300'
                          : 'bg-[#1c1b1d] border border-zinc-800 text-[#debfc1]/70 hover:border-zinc-600 hover:text-[#e5e1e4]'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[16px]">{b.icon}</span>
                      <span>{b.name}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Vector Feeds & Inundation Toggles */}
              <div className="bg-[#201f22] p-3 rounded-md border border-[#574143]/30">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-[#debfc1]/70">Vector Feeds & Inundation</span>
                  <span className="font-mono text-[10px] text-rose-300">Active Overlays</span>
                </div>
                <div className="space-y-1.5">
                  {[
                    { key: 'flood', label: 'SAR Flood Inundation Extent', color: 'bg-sky-400' },
                    { key: 'roads', label: 'Cut-off Road Network (OSM)', color: 'bg-rose-400' },
                    { key: 'bridges', label: 'Damaged Bridge Crossings', color: 'bg-amber-400' },
                    { key: 'settlements', label: 'Cut-off Settlement Nodes', color: 'bg-rose-300' },
                    { key: 'hlz', label: 'Verified Landing Zones (HLZ)', color: 'bg-purple-400' },
                    { key: 'ponding', label: 'Soil Ponding / Saturated Silt', color: 'bg-pink-400' },
                  ].map((layer) => (
                    <label
                      key={layer.key}
                      className="flex items-center justify-between p-2 rounded-md bg-[#1c1b1d] hover:bg-[#2a2a2c] cursor-pointer transition-colors border border-zinc-800/80"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full ${layer.color} ring-2 ring-white/10`}></span>
                        <span className="text-[12px] text-[#e5e1e4]">{layer.label}</span>
                      </div>
                      <input
                        type="checkbox"
                        checked={activeLayers[layer.key]}
                        onChange={() => toggleLayer(layer.key)}
                        className="rounded border-zinc-700 bg-zinc-900 text-rose-500 focus:ring-rose-500 w-4 h-4 cursor-pointer accent-rose-500"
                      />
                    </label>
                  ))}
                </div>
              </div>

              {/* Satellite Overpass Schedule Card */}
              <div className="bg-[#201f22] p-3 rounded-md border border-[#574143]/30">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-[#debfc1]/70">Satellite Overpass Schedule</span>
                  <span className="font-mono text-[11px] text-rose-300 font-semibold">NORAD SYNC</span>
                </div>
                <div className="space-y-2">
                  <div className="p-2 rounded bg-[#1c1b1d] border border-zinc-800 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded bg-rose-500/10 flex items-center justify-center text-rose-300">
                        <span className="material-symbols-outlined text-[18px]">satellite_alt</span>
                      </div>
                      <div>
                        <div className="text-[12px] font-semibold text-[#e5e1e4]">Sentinel-1C SAR (Radar)</div>
                        <div className="font-mono text-[10px] text-[#debfc1]/60">Cloud Penetrating | 10m Res</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[12px] text-rose-300 font-semibold">01h 42m</div>
                      <div className="text-[10px] text-[#debfc1]/60">0% Cloud Impact</div>
                    </div>
                  </div>

                  <div className="p-2 rounded bg-[#1c1b1d] border border-zinc-800 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded bg-[#201f22] flex items-center justify-center text-zinc-400">
                        <span className="material-symbols-outlined text-[18px]">wb_twilight</span>
                      </div>
                      <div>
                        <div className="text-[12px] font-semibold text-[#e5e1e4]">Sentinel-2B MSI (Optical)</div>
                        <div className="font-mono text-[10px] text-[#debfc1]/60">Multispectral Band B8A</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[12px] text-[#e5e1e4]">07h 15m</div>
                      <div className="text-[10px] text-amber-400">84% Cloud Cover</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button
                  onClick={() => openSmsModal()}
                  className="py-2 px-3 rounded-md bg-[#201f22] hover:bg-[#2a2a2c] border border-rose-500/40 hover:border-rose-400 text-rose-300 font-mono text-[11px] uppercase tracking-wider flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">podcasts</span>
                  <span>LoRa Broadcast</span>
                </button>
                <button
                  onClick={exportSitRep}
                  className="py-2 px-3 rounded-md bg-[#201f22] hover:bg-[#2a2a2c] border border-zinc-700 hover:border-zinc-500 text-[#e5e1e4] font-mono text-[11px] uppercase tracking-wider flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px]">picture_as_pdf</span>
                  <span>Export SitRep</span>
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: TRIAGE QUEUE */}
          {sidebarTab === 'triage' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              <div className="flex items-center justify-between pb-1 border-b border-zinc-800">
                <div>
                  <h3 className="font-mono text-[12px] font-semibold uppercase text-rose-300">🚨 Isolation Triage Queue</h3>
                  <p className="text-[11px] text-[#debfc1]/70">Prioritized by population & cut-off severity</p>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 font-mono text-[10px] border border-rose-500/40">
                  {settlementsList.length} settlements
                </span>
              </div>

              <div className="space-y-2">
                {settlementsList.length === 0 ? (
                  <div className="p-8 text-center text-[#debfc1]/50 text-[12px]">
                    No settlement records found in this analysis run.
                  </div>
                ) : (
                  [...settlementsList]
                    .sort((a, b) => (b.properties?.urgency_score || 0) - (a.properties?.urgency_score || 0))
                    .map((item, idx) => {
                      const p = item.properties || {}
                      const coords = item.geometry?.coordinates
                      const isIso = p.isolation_status === 'isolated'
                      const isDeg = p.isolation_status === 'degraded'

                      return (
                        <div
                          key={p.id || idx}
                          onClick={() => {
                            if (coords && map.current && coords.length >= 2) {
                              map.current.flyTo([coords[1], coords[0]], 14, { duration: 1.2 })
                              showToast(`Map centered on ${p.name || 'Village'}`)
                            }
                          }}
                          className={`p-3 rounded-md bg-[#1c1b1d] border transition-all cursor-pointer hover:border-rose-400 ${
                            isIso ? 'border-rose-500/50 shadow-[0_0_10px_rgba(251,113,133,0.1)]' : 'border-zinc-800'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-[13px] font-semibold text-[#e5e1e4]">{p.name || 'Unnamed Village'}</span>
                            <span
                              className={`font-mono text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                                isIso
                                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                                  : isDeg
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                                  : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                              }`}
                            >
                              {(p.isolation_status || 'CONNECTED').toUpperCase()}
                            </span>
                          </div>

                          <div className="grid grid-cols-2 gap-y-1 text-[11px] text-[#debfc1]/80 mb-2">
                            <div>Pop: <b className="text-[#e5e1e4]">{p.estimated_population?.toLocaleString() ?? '—'}</b></div>
                            <div>
                              Urgency:{' '}
                              <b className="font-mono text-rose-400 font-bold">
                                {typeof p.urgency_score === 'number' ? p.urgency_score.toFixed(2) : '—'}
                              </b>
                            </div>
                            <div>Clinic: {p.has_clinic ? '✅ Available' : '❌ None'}</div>
                            <div>Type: <span className="text-[#debfc1]/60">{p.place_type || 'settlement'}</span></div>
                          </div>

                          <div className="flex items-center justify-between pt-1 border-t border-zinc-800 text-[10px]">
                            <span className="text-purple-300 font-mono">
                              🚁 LZ: <b>{p.nearest_hlz_id ? p.nearest_hlz_id.replace(/^.*-/, '').toUpperCase() : 'SEARCHING'}</b>
                            </span>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                openSmsModal(p.name)
                              }}
                              className="text-rose-400 hover:text-rose-300 font-semibold cursor-pointer underline"
                            >
                              Dispatch Alert →
                            </button>
                          </div>
                        </div>
                      )
                    })
                )}
              </div>
            </div>
          )}

          {/* TAB 3: HELICOPTER LANDING ZONES */}
          {sidebarTab === 'hlz' && (
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              <div className="flex items-center justify-between pb-1 border-b border-zinc-800">
                <div>
                  <h3 className="font-mono text-[12px] font-semibold uppercase text-purple-300">🚁 Helicopter Extraction Sites</h3>
                  <p className="text-[11px] text-[#debfc1]/70">Dry terrain slope &lt; 5°, clearance &gt; 25m</p>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 font-mono text-[10px] border border-purple-500/40">
                  {hlzList.length} sites
                </span>
              </div>

              <div className="space-y-2">
                {hlzList.length === 0 ? (
                  <div className="p-8 text-center text-[#debfc1]/50 text-[12px]">
                    No landing zones identified in this run.
                  </div>
                ) : (
                  hlzList.map((item, idx) => {
                    const p = item.properties || {}
                    const coords =
                      item.geometry?.type === 'Point'
                        ? item.geometry.coordinates
                        : item.geometry?.coordinates?.[0]?.[0]

                    return (
                      <div
                        key={p.id || idx}
                        onClick={() => {
                          if (coords && map.current && coords.length >= 2) {
                            map.current.flyTo([coords[1], coords[0]], 15, { duration: 1.2 })
                            showToast(`Centering map on Landing Zone`)
                          }
                        }}
                        className="p-3 rounded-md bg-[#1c1b1d] border border-purple-500/30 hover:border-purple-400 transition-all cursor-pointer"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono text-[13px] font-bold text-purple-300">
                            {p.id ? p.id.replace(/^.*-/, '').toUpperCase() : `HLZ-${idx + 1}`}
                          </span>
                          <span className="font-mono text-[11px] text-[#debfc1]/70">
                            {p.elevation_m ? `${Math.round(p.elevation_m)}m ASL` : '—'}
                          </span>
                        </div>

                        <div className="grid grid-cols-2 gap-y-1 text-[11px] text-[#debfc1]/80">
                          <div>Slope: <b className="text-[#e5e1e4]">{p.avg_slope_deg ? `${p.avg_slope_deg.toFixed(1)}°` : '—'}</b></div>
                          <div>Clearance: <b className="text-[#e5e1e4]">{p.area_m2 ? `${Math.round(p.area_m2)}m²` : '—'}</b></div>
                          <div>Surface: <span className="text-[#debfc1]/60">{p.surface_estimate ? p.surface_estimate.replace('_', ' ') : 'compact ground'}</span></div>
                          <div>Dist to Village: <b className="text-purple-300">{p.dist_to_settlement_m ? `${Math.round(p.dist_to_settlement_m)}m` : '—'}</b></div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          )}

          {/* TAB 4: COPILOT */}
          {sidebarTab === 'copilot' && (
            <div className="flex-1 overflow-y-auto p-4 flex flex-col justify-between">
              <div className="space-y-3">
                <div className="pb-1 border-b border-zinc-800">
                  <h3 className="font-mono text-[12px] font-semibold uppercase text-rose-300">🤖 Tactical AI Copilot</h3>
                  <p className="text-[11px] text-[#debfc1]/70">Grounded natural language queries with verified PostGIS SQL citations</p>
                </div>

                {/* Prompt suggestions */}
                <div className="space-y-1">
                  <span className="text-[10px] font-mono uppercase text-[#debfc1]/50">Suggested queries:</span>
                  <div className="flex flex-wrap gap-1">
                    {[
                      'How many settlements are isolated?',
                      'Which bridges are destroyed?',
                      'कति बस्ती अलग छन्?',
                    ].map((prompt, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          setCopilotQuery(prompt)
                          handleCopilotQuery(prompt)
                        }}
                        className="text-[11px] bg-[#1c1b1d] hover:bg-[#201f22] text-[#debfc1] px-2 py-1 rounded border border-zinc-800 text-left cursor-pointer transition-colors"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Query Input */}
                <div className="flex gap-1.5 bg-[#1c1b1d] p-1.5 rounded-md border border-zinc-800 focus-within:border-rose-500/50">
                  <input
                    type="text"
                    value={copilotQuery}
                    onChange={(e) => setCopilotQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCopilotQuery()}
                    placeholder="Ask disaster intelligence engine..."
                    className="flex-1 bg-transparent text-[12px] text-[#e5e1e4] outline-none px-2"
                  />
                  <button
                    onClick={() => handleCopilotQuery()}
                    disabled={copilotLoading}
                    className="px-3 py-1 bg-rose-500 hover:bg-rose-600 disabled:opacity-50 text-white rounded font-mono text-[12px] font-semibold transition-colors cursor-pointer"
                  >
                    {copilotLoading ? '...' : 'Ask'}
                  </button>
                </div>

                {/* Response Card */}
                {copilotResponse && (
                  <div className="p-3 rounded-md bg-[#1c1b1d] border border-rose-500/30 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] uppercase text-rose-300 font-semibold">Intelligence Synthesis</span>
                      <span className="font-mono text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                        {copilotResponse.confidence?.toUpperCase() || 'VERIFIED'}
                      </span>
                    </div>
                    <p className="text-[12px] leading-relaxed text-[#e5e1e4]">{copilotResponse.answer}</p>

                    {copilotResponse.citation && (
                      <details className="pt-1 border-t border-zinc-800">
                        <summary className="font-mono text-[10px] text-[#debfc1]/60 cursor-pointer hover:text-[#e5e1e4]">
                          View SQL Citation
                        </summary>
                        <pre className="mt-1 p-2 rounded bg-[#0e0e10] text-[10px] font-mono text-rose-200 overflow-x-auto whitespace-pre-wrap">
                          {copilotResponse.citation.sql}
                        </pre>
                      </details>
                    )}
                  </div>
                )}
              </div>

              <div className="pt-3 border-t border-zinc-800/80 text-[10px] font-mono text-[#debfc1]/40 text-center">
                Modified Copernicus Sentinel data 2026 • OSM Contributors
              </div>
            </div>
          )}
        </aside>

        {/* ─── FULL-BLEED INTERACTIVE GIS MAP ─── */}
        <main className="flex-1 relative w-full h-full bg-[#0e0e10]">
          <div ref={mapContainer} className="w-full h-full z-10" />

          {/* Floating Basemap Selector Tool on Top-Right */}
          <div className="absolute top-3 right-12 z-20 flex bg-[#1c1b1d]/90 backdrop-blur-md p-1 rounded-md border border-zinc-800 shadow-lg gap-1">
            {Object.values(BASEMAP_CONFIGS).map((b) => (
              <button
                key={b.id}
                onClick={() => switchBasemap(b.id)}
                className={`px-2.5 py-1 rounded text-[11px] font-mono flex items-center gap-1 transition-colors cursor-pointer ${
                  basemap === b.id
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 font-semibold'
                    : 'text-[#debfc1]/70 hover:text-[#e5e1e4]'
                }`}
              >
                <span className="material-symbols-outlined text-[14px]">{b.icon}</span>
                <span>{b.name}</span>
              </button>
            ))}
          </div>

          {/* Floating Map Legend */}
          <div className="absolute bottom-6 left-6 z-20 bg-[#1c1b1d]/95 backdrop-blur-md p-3 rounded-md border border-zinc-800/80 shadow-xl text-[11px] font-mono space-y-1.5 hidden md:block">
            <div className="text-[10px] uppercase text-[#debfc1]/60 font-semibold mb-1">GIS Map Legend</div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-emerald-400"></span>
              <span>Intact / Connected</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-amber-400"></span>
              <span>Degraded / Damaged</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-rose-500"></span>
              <span>Severed / Isolated</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-purple-400"></span>
              <span>Helicopter LZ (Slope &lt; 5°)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded bg-sky-400/80"></span>
              <span>SAR Flood Extent</span>
            </div>
          </div>
        </main>
      </div>

      {/* ─── MODAL 1: UPLOAD SAR RADAR DATA ─── */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#1c1b1d] border border-rose-500/40 rounded-lg max-w-lg w-full p-5 shadow-2xl relative">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-rose-400 text-[22px]">radar</span>
                <h3 className="text-[16px] font-semibold text-[#e5e1e4]">Upload SAR Radar Scene</h3>
              </div>
              <button
                onClick={() => setShowUploadModal(false)}
                className="text-zinc-400 hover:text-white text-xl cursor-pointer"
              >
                &times;
              </button>
            </div>

            <p className="text-[12px] text-[#debfc1]/70 mt-2 mb-4">
              Ingest raw synthetic aperture radar imagery (GeoTIFF, PNG, JPEG). The backend executes backscatter calibration, speckle noise reduction, and automated damage assessment.
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-[11px] font-mono uppercase text-[#debfc1]/70 mb-1">Incident / AOI Name</label>
                <input
                  type="text"
                  value={uploadAoiName}
                  onChange={(e) => setUploadAoiName(e.target.value)}
                  className="w-full bg-[#131315] border border-zinc-700 rounded p-2 text-[12px] text-[#e5e1e4] outline-none focus:border-rose-400"
                />
              </div>

              {/* Drag & Drop File Zone */}
              <div
                className="border-2 border-dashed border-zinc-700 hover:border-rose-500/60 rounded-lg p-6 text-center cursor-pointer transition-colors bg-[#131315]"
                onClick={() => document.getElementById('sar-file-input').click()}
              >
                <input
                  id="sar-file-input"
                  type="file"
                  accept=".tif,.tiff,.png,.jpg,.jpeg"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      setUploadFile(e.target.files[0])
                    }
                  }}
                />
                <span className="material-symbols-outlined text-rose-400 text-3xl mb-1">cloud_upload</span>
                {uploadFile ? (
                  <div className="text-[12px]">
                    <p className="font-semibold text-rose-300">{uploadFile.name}</p>
                    <p className="text-[#debfc1]/60 text-[10px] font-mono">{(uploadFile.size / 1024).toFixed(1)} KB</p>
                  </div>
                ) : (
                  <div className="text-[12px] text-[#debfc1]/70">
                    <p className="font-medium text-[#e5e1e4]">Click to browse or drop radar scene</p>
                    <p className="text-[10px] text-[#debfc1]/50 font-mono mt-0.5">Supports Sentinel-1 GRDH GeoTIFF, PNG, or JPEG</p>
                  </div>
                )}
              </div>

              {uploadProgress && (
                <div className="p-2.5 rounded bg-[#201f22] border border-rose-500/30 text-[11px] font-mono text-rose-300 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[16px] animate-spin">sync</span>
                  <span>{uploadProgress}</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2 border-t border-zinc-800">
                <button
                  onClick={() => setShowUploadModal(false)}
                  className="px-4 py-2 rounded bg-[#201f22] text-[12px] text-[#debfc1] hover:bg-zinc-800 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSarUpload}
                  disabled={uploading || !uploadFile}
                  className="px-4 py-2 rounded bg-rose-500 hover:bg-rose-600 disabled:opacity-50 text-white text-[12px] font-semibold flex items-center gap-1.5 cursor-pointer shadow-[0_0_12px_rgba(251,113,133,0.3)]"
                >
                  <span className="material-symbols-outlined text-[16px]">play_arrow</span>
                  <span>{uploading ? 'Processing Scene...' : 'Execute Ingestion Pipeline'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── MODAL 2: SMS / LORA BROADCAST MODAL ─── */}
      {showSmsModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#1c1b1d] border border-rose-500/40 rounded-lg max-w-lg w-full p-5 shadow-2xl relative">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-rose-400 text-[22px]">podcasts</span>
                <h3 className="text-[16px] font-semibold text-[#e5e1e4]">SMS / LoRa Field Broadcast</h3>
              </div>
              <button
                onClick={() => setShowSmsModal(false)}
                className="text-zinc-400 hover:text-white text-xl cursor-pointer"
              >
                &times;
              </button>
            </div>

            <p className="text-[12px] text-[#debfc1]/70 mt-2 mb-3">
              Compact tactical dispatches for satellite-mesh and low-bandwidth emergency links (constrained to &le; 140 chars).
            </p>

            <div className="space-y-3">
              <div>
                <div className="flex justify-between items-center mb-1 text-[11px] font-mono">
                  <span className="text-[#debfc1]/70">Draft Alert Message:</span>
                  <span className={smsText.length > 140 ? 'text-rose-400 font-bold' : 'text-rose-300'}>
                    {smsText.length} / 140 Chars
                  </span>
                </div>
                <textarea
                  value={smsText}
                  onChange={(e) => setSmsText(e.target.value)}
                  rows={3}
                  className="w-full bg-[#131315] border border-zinc-700 rounded p-2 text-[12px] text-[#e5e1e4] outline-none font-mono focus:border-rose-400"
                />
              </div>

              <div className="flex justify-between items-center pt-2 border-t border-zinc-800">
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(smsText)
                    setCopiedSms(true)
                    showToast('Payload copied to clipboard')
                    setTimeout(() => setCopiedSms(false), 2000)
                  }}
                  className="px-3 py-1.5 rounded bg-[#201f22] hover:bg-zinc-800 border border-zinc-700 text-[11px] font-mono text-[#e5e1e4] flex items-center gap-1 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[14px]">content_copy</span>
                  <span>{copiedSms ? 'Copied!' : 'Copy Payload'}</span>
                </button>

                <div className="flex gap-2">
                  <button
                    onClick={() => setShowSmsModal(false)}
                    className="px-3 py-1.5 rounded bg-[#201f22] text-[12px] text-[#debfc1] hover:bg-zinc-800 cursor-pointer"
                  >
                    Close
                  </button>
                  <button
                    onClick={() => {
                      showToast('LoRa packet acknowledged by repeater network!')
                      setShowSmsModal(false)
                    }}
                    className="px-4 py-1.5 rounded bg-rose-500 hover:bg-rose-600 text-white text-[12px] font-semibold flex items-center gap-1 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[15px]">sensors</span>
                    <span>Transmit Packet</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── TOAST NOTIFICATION ─── */}
      {toast.show && (
        <div className="fixed bottom-5 right-5 z-50 bg-[#1c1b1d] border border-rose-500/50 text-[#e5e1e4] px-4 py-2.5 rounded-lg shadow-2xl font-mono text-[12px] flex items-center gap-2 animate-bounce">
          <span className="material-symbols-outlined text-rose-400 text-[18px]">info</span>
          <span>{toast.message}</span>
        </div>
      )}

      {/* ─── LOADING SPINNER OVERLAY ─── */}
      {loading && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-xs z-50 flex items-center justify-center">
          <div className="bg-[#1c1b1d] p-5 rounded-lg border border-rose-500/30 flex items-center gap-3">
            <span className="material-symbols-outlined text-rose-400 text-2xl animate-spin">sync</span>
            <span className="text-[13px] font-mono text-rose-200">Loading analysis datasets...</span>
          </div>
        </div>
      )}
    </div>
  )
}
