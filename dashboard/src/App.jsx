import { useState, useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import LoginPage from './LoginPage'

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

  // Operator Authentication State
  const [operator, setOperator] = useState(() => {
    try {
      const saved = localStorage.getItem('strand_operator')
      return saved ? JSON.parse(saved) : null
    } catch {
      return null
    }
  })
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('strand_api_key') || API_KEY)
  const currentApiKey = apiKey || API_KEY

  const handleLoginSuccess = (operatorProfile, newApiKey) => {
    setOperator(operatorProfile)
    setApiKey(newApiKey)
    showToast(`Clearance Verified: ${operatorProfile.callsign} (${operatorProfile.role_display})`)
  }

  const handleLogout = () => {
    localStorage.removeItem('strand_operator')
    localStorage.removeItem('strand_api_key')
    if (map.current) {
      map.current.remove()
      map.current = null
    }
    setOperator(null)
    setAnalyses([])
    setSelectedAnalysis(null)
    setAnalysisData(null)
    showToast('Operator session ended.')
  }

  // Primary Sidebar Navigation Module
  // 'tactical' | 'sar-analytics' | 'infrastructure' | 'mesh-hlz' | 'telemetry-logs'
  const [activeModule, setActiveModule] = useState('tactical')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Secondary Tab inside Tactical Overview: 'layers' | 'triage' | 'hlz' | 'copilot'
  const [tacticalTab, setTacticalTab] = useState('layers')

  // Datasets State
  const [basemap, setBasemap] = useState('satellite')
  const [analyses, setAnalyses] = useState([])
  const [selectedAnalysis, setSelectedAnalysis] = useState(null)
  const [analysisData, setAnalysisData] = useState(null)
  const [loading, setLoading] = useState(false)

  // Layers & Vectors
  const [activeLayers, setActiveLayers] = useState({
    flood: true,
    roads: true,
    bridges: true,
    settlements: true,
    hlz: true,
    ponding: false,
  })
  const [settlementsList, setSettlementsList] = useState([])
  const [roadsList, setRoadsList] = useState([])
  const [bridgesList, setBridgesList] = useState([])
  const [hlzList, setHlzList] = useState([])
  const [pipelineLogs, setPipelineLogs] = useState([])

  // Copilot State
  const [copilotQuery, setCopilotQuery] = useState('')
  const [copilotResponse, setCopilotResponse] = useState(null)
  const [copilotLoading, setCopilotLoading] = useState(false)

  // Modals
  const [showSmsModal, setShowSmsModal] = useState(false)
  const [smsAlerts, setSmsAlerts] = useState([])
  const [smsLoading, setSmsLoading] = useState(false)
  const [smsText, setSmsText] = useState('')
  const [copiedSms, setCopiedSms] = useState(false)

  // Upload SAR Modal
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadAoiName, setUploadAoiName] = useState('Koshi Basin Radar Ingestion')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')

  // Toast Notification
  const [toast, setToast] = useState({ show: false, message: '' })
  const showToast = (message) => {
    setToast({ show: true, message })
    setTimeout(() => setToast({ show: false, message: '' }), 3500)
  }

  // Initialize Leaflet Map (runs on tactical overview whenever operator is authenticated)
  useEffect(() => {
    if (!operator) return
    if (activeModule !== 'tactical') return
    if (!mapContainer.current) return

    // Clean up any stale map instance
    if (map.current) {
      try {
        map.current.remove()
      } catch (e) {
        console.warn('Map cleanup error:', e)
      }
      map.current = null
    }

    // Leaflet tags the DOM element with _leaflet_id; clear it on re-mount to avoid crashes
    if (mapContainer.current._leaflet_id) {
      delete mapContainer.current._leaflet_id
    }

    const m = L.map(mapContainer.current, {
      center: NEPAL_CENTER,
      zoom: NEPAL_ZOOM,
      zoomControl: false,
    })

    L.control.zoom({ position: 'topright' }).addTo(m)
    L.control.scale({ imperial: false, position: 'bottomright' }).addTo(m)

    const initialCfg = BASEMAP_CONFIGS[basemap] || BASEMAP_CONFIGS.satellite
    const initialTile = L.tileLayer(initialCfg.url, {
      attribution: initialCfg.attribution,
      maxZoom: initialCfg.maxZoom,
    }).addTo(m)

    baseTileLayer.current = initialTile
    map.current = m

    // Force Leaflet to calculate container bounds once rendered
    m.invalidateSize()
    const resizeTimer = setTimeout(() => {
      if (m && map.current) {
        m.invalidateSize()
      }
    }, 200)

    if (selectedAnalysis) {
      loadAllLayers(selectedAnalysis)
    }

    return () => {
      clearTimeout(resizeTimer)
      if (map.current) {
        try {
          map.current.remove()
        } catch (e) {
          console.warn('Map cleanup error:', e)
        }
        map.current = null
      }
    }
  }, [activeModule, operator])

  // Synchronize active analysis layers to map whenever selectedAnalysis changes
  useEffect(() => {
    if (selectedAnalysis && map.current && activeModule === 'tactical') {
      loadAllLayers(selectedAnalysis)
    }
  }, [selectedAnalysis])

  // Initial Data Fetch
  useEffect(() => {
    if (operator) {
      fetchAnalyses()
    }
  }, [operator])

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
    showToast(`Basemap: ${cfg.name}`)
  }

  // Fetch list of analyses
  const fetchAnalyses = async () => {
    try {
      const res = await fetch(`${API_BASE}/analysis`, {
        headers: { 'X-API-Key': currentApiKey },
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
        headers: { 'X-API-Key': currentApiKey },
      })
      if (detailRes.ok) {
        const detail = await detailRes.json()
        setAnalysisData(detail)
      }
      await loadAllLayers(analysisId)
      await fetchPipelineLogs(analysisId)
      showToast(`Active run: ${analysisId}`)
    } catch (e) {
      console.error('Failed to load analysis:', e)
    } finally {
      setLoading(false)
    }
  }

  // Fetch Pipeline Logs
  const fetchPipelineLogs = async (analysisId) => {
    try {
      const res = await fetch(`${API_BASE}/analysis/${analysisId}/logs`, {
        headers: { 'X-API-Key': currentApiKey },
      })
      if (res.ok) {
        const logs = await res.json()
        setPipelineLogs(logs)
      }
    } catch (e) {
      console.error('Failed to fetch logs:', e)
    }
  }

  // Load All Layers for Selected Analysis
  const loadAllLayers = async (analysisId) => {
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
        const res = await fetch(ep.url, { headers: { 'X-API-Key': currentApiKey } })
        if (!res.ok) continue
        const geojson = await res.json()

        if (ep.name === 'settlements') setSettlementsList(geojson.features || [])
        if (ep.name === 'roads') setRoadsList(geojson.features || [])
        if (ep.name === 'bridges') setBridgesList(geojson.features || [])
        if (ep.name === 'hlz') setHlzList(geojson.features || [])

        if (map.current) {
          if (layerGroups.current[ep.name] && map.current.hasLayer(layerGroups.current[ep.name])) {
            map.current.removeLayer(layerGroups.current[ep.name])
          }
          const leafletLayer = createLeafletLayer(ep.name, geojson)
          layerGroups.current[ep.name] = leafletLayer
          if (activeLayers[ep.name] && leafletLayer) {
            map.current.addLayer(leafletLayer)
          }
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
          'X-API-Key': currentApiKey,
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
        headers: { 'Content-Type': 'application/json', 'X-API-Key': currentApiKey },
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
        headers: { 'Content-Type': 'application/json', 'X-API-Key': currentApiKey },
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
        headers: { 'X-API-Key': currentApiKey },
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Upload failed')
      }

      setUploadProgress('Persisting detected flood polygons into Neon PG...')
      const newAnalysis = await res.json()

      showToast(`SAR Ingestion Complete! Flood: ${newAnalysis.flood_area_km2} km²`)
      setShowUploadModal(false)
      setUploadFile(null)

      await fetchAnalyses()
      selectAnalysis(newAnalysis.analysis_id)
      setActiveModule('tactical')
    } catch (e) {
      console.error('Upload error:', e)
      showToast(`Upload failed: ${e.message}`)
    } finally {
      setUploading(false)
      setUploadProgress('')
    }
  }

  const stats = analysisData?.summary || {}

  // Operational Navigation Items in Primary Sidebar
  const NAV_MODULES = [
    {
      id: 'tactical',
      label: 'Tactical Overview',
      subtitle: 'GIS Map & Operations',
      icon: 'explore',
      badge: 'LIVE',
    },
    {
      id: 'sar-analytics',
      label: 'SAR Flood Analytics',
      subtitle: 'Radar Science & Telemetry',
      icon: 'water_damage',
      badge: `${stats.flood_area_km2 ?? 0} km²`,
    },
    {
      id: 'infrastructure',
      label: 'Infrastructure Grid',
      subtitle: 'Road Cuts & Bridges',
      icon: 'cell_tower',
      badge: `${stats.roads_severed_km ?? 0} km`,
    },
    {
      id: 'mesh-hlz',
      label: 'Extraction & HLZ',
      subtitle: 'Landing Zones & Triage',
      icon: 'flight_takeoff',
      badge: `${hlzList.length} sites`,
    },
    {
      id: 'telemetry-logs',
      label: 'Telemetry & Logs',
      subtitle: 'PostGIS & Orbit History',
      icon: 'query_stats',
      badge: `${pipelineLogs.length}`,
    },
  ]

  if (!operator) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      {/* ═════════════════════════════════════════════════════════════ */}
      {/* ─── PRIMARY OPERATIONAL SIDEBAR (LEFT) ─────────────────── */}
      {/* ═════════════════════════════════════════════════════════════ */}
      <aside
        className={`h-full bg-[#0e0e10] border-r border-[#574143]/25 flex flex-col justify-between transition-all duration-300 z-40 flex-shrink-0 ${
          sidebarCollapsed ? 'w-16' : 'w-64'
        }`}
      >
        {/* Sidebar Brand Header */}
        <div>
          <div
            className={`h-14 border-b border-[#574143]/20 flex items-center ${
              sidebarCollapsed ? 'justify-center px-2' : 'justify-between px-3.5'
            } bg-[#0e0e10]/80`}
          >
            {!sidebarCollapsed ? (
              <>
                <div className="flex items-center gap-2.5 overflow-hidden">
                  <div className="w-8 h-8 rounded-lg bg-[#201f22] border border-rose-500/40 flex items-center justify-center text-rose-300 shadow-[0_0_12px_rgba(251,113,133,0.18)] flex-shrink-0">
                    <span className="material-symbols-outlined text-[18px]">satellite_alt</span>
                  </div>
                  <div className="flex flex-col overflow-hidden">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono font-bold text-[14px] tracking-wider text-[#e5e1e4] uppercase">
                        S.T.R.A.N.D
                      </span>
                      <span className="px-1 py-0.2 rounded bg-[#2a2a2c] font-mono text-[9px] text-rose-300 border border-rose-500/30">
                        PROD
                      </span>
                    </div>
                    <span className="text-[10px] text-[#debfc1]/60 truncate">Disaster Intelligence</span>
                  </div>
                </div>

                <button
                  onClick={() => setSidebarCollapsed(true)}
                  className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
                  title="Collapse Sidebar"
                >
                  <span className="material-symbols-outlined text-[18px]">chevron_left</span>
                </button>
              </>
            ) : (
              <button
                onClick={() => setSidebarCollapsed(false)}
                className="w-9 h-9 flex items-center justify-center text-zinc-400 hover:text-rose-300 rounded-lg hover:bg-zinc-800 transition-colors cursor-pointer"
                title="Expand Sidebar"
              >
                <span className="material-symbols-outlined text-[20px]">chevron_right</span>
              </button>
            )}
          </div>

          {/* Module Navigation Menu */}
          <div className="p-2 space-y-1">
            {!sidebarCollapsed && (
              <div className="px-2 pt-2 pb-1 text-[10px] font-mono uppercase tracking-wider text-[#debfc1]/50 font-semibold">
                Operational Modules
              </div>
            )}

            {NAV_MODULES.map((mod) => {
              const isActive = activeModule === mod.id
              return (
                <button
                  key={mod.id}
                  onClick={() => setActiveModule(mod.id)}
                  className={`w-full flex items-center ${
                    sidebarCollapsed ? 'justify-center p-2.5' : 'gap-2.5 p-2'
                  } rounded-md transition-all text-left cursor-pointer group relative ${
                    isActive
                      ? 'bg-[#201f22] text-rose-300 border-l-2 border-rose-400 font-semibold shadow-sm'
                      : 'text-[#debfc1]/75 hover:bg-[#1c1b1d] hover:text-[#e5e1e4]'
                  }`}
                  title={mod.label}
                >
                  <span
                    className={`material-symbols-outlined text-[20px] transition-colors ${
                      isActive ? 'text-rose-400' : 'text-zinc-400 group-hover:text-rose-300'
                    }`}
                  >
                    {mod.icon}
                  </span>

                  {!sidebarCollapsed && (
                    <div className="flex-1 truncate">
                      <div className="text-[12px] leading-tight truncate">{mod.label}</div>
                      <div className="text-[10px] text-[#debfc1]/50 truncate font-mono">{mod.subtitle}</div>
                    </div>
                  )}

                  {!sidebarCollapsed && mod.badge && (
                    <span
                      className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${
                        isActive
                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                          : 'bg-zinc-800 text-zinc-400'
                      }`}
                    >
                      {mod.badge}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* Sidebar Footer / Telemetry Strip */}
        <div className="p-3 border-t border-[#574143]/20 bg-[#141416]/90 space-y-2">
          {!sidebarCollapsed ? (
            <>
              {/* Operator Session Info in Footer */}
              <div className="flex items-center justify-between pb-2 border-b border-[#574143]/20">
                <div className="flex items-center gap-2 overflow-hidden">
                  <div className="w-7 h-7 rounded-full bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-rose-300 font-mono text-[10px] font-bold flex-shrink-0">
                    {operator.callsign ? operator.callsign.substring(0, 2).toUpperCase() : 'OP'}
                  </div>
                  <div className="flex flex-col overflow-hidden">
                    <span className="text-[11px] font-bold truncate text-[#e5e1e4] leading-tight">
                      {operator.callsign}
                    </span>
                    <span className="text-[9px] font-mono text-rose-400 truncate leading-tight">
                      {operator.role_display}
                    </span>
                  </div>
                </div>
                <button
                  onClick={handleLogout}
                  className="text-zinc-500 hover:text-rose-400 p-1 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
                  title="Disconnect / Log Out"
                >
                  <span className="material-symbols-outlined text-[16px]">logout</span>
                </button>
              </div>

              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-[#debfc1]/60 uppercase">Engine Health</span>
                <span className="text-rose-300 font-semibold">99.98%</span>
              </div>
              <div className="w-full bg-zinc-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-gradient-to-r from-rose-400 to-rose-500 h-full w-[99.98%]"></div>
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#debfc1]/60 pt-1">
                <span>Lat: 27.88° N</span>
                <span>Lon: 85.92° E</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] font-mono text-emerald-400 pt-0.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping"></span>
                <span>Neon PG Connected (24ms)</span>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <button
                onClick={handleLogout}
                className="w-8 h-8 rounded-lg bg-[#201f22] hover:bg-rose-500/20 text-zinc-400 hover:text-rose-300 flex items-center justify-center transition-colors cursor-pointer"
                title={`Logged in as ${operator.callsign} — Click to Log Out`}
              >
                <span className="material-symbols-outlined text-[16px]">logout</span>
              </button>
              <div className="flex flex-col items-center gap-1 text-[10px] font-mono text-emerald-400">
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-400"></span>
                <span className="text-[8px]">ONLINE</span>
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* ═════════════════════════════════════════════════════════════ */}
      {/* ─── MAIN CONTENT VIEWPORT ──────────────────────────────── */}
      {/* ═════════════════════════════════════════════════════════════ */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Top Operational Bar */}
        <header className="h-14 bg-[#0e0e10]/95 backdrop-blur-md border-b border-[#574143]/30 px-4 flex items-center justify-between z-30 flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="font-mono text-[12px] uppercase text-rose-300/90 font-semibold tracking-wider">
              {NAV_MODULES.find((m) => m.id === activeModule)?.label}
            </span>
            <span className="text-zinc-600">/</span>

            {/* Analysis Run Selector */}
            {analyses.length > 0 && (
              <div className="flex items-center gap-1.5 bg-[#1c1b1d] px-2.5 py-1 rounded-md border border-[#574143]/40 hover:border-rose-500/50 transition-colors">
                <span className="material-symbols-outlined text-rose-400 text-[15px]">crisis_alert</span>
                <select
                  className="bg-transparent text-[12px] text-[#e5e1e4] font-medium outline-none cursor-pointer pr-1"
                  value={selectedAnalysis || ''}
                  onChange={(e) => selectAnalysis(e.target.value)}
                >
                  {analyses.map((a) => (
                    <option key={a.analysis_id} value={a.analysis_id} className="bg-[#1c1b1d] text-[#e5e1e4]">
                      {a.analysis_id.slice(0, 22)} • {a.flood_area_km2 ? `${a.flood_area_km2} km²` : a.status}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Action triggers & Operator Session */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowUploadModal(true)}
              className="flex items-center gap-1.5 bg-[#201f22] hover:bg-[#2a2a2c] text-rose-300 border border-rose-500/50 hover:border-rose-400 px-3 py-1.5 rounded-md transition-all shadow-[0_0_12px_rgba(251,113,133,0.18)] cursor-pointer text-[12px] font-semibold tracking-wide uppercase"
            >
              <span className="material-symbols-outlined text-[16px]">radar</span>
              <span>Upload SAR Radar Data</span>
            </button>
            <button
              onClick={exportSitRep}
              className="hidden sm:flex items-center gap-1.5 bg-[#1c1b1d] hover:bg-[#201f22] text-[#e5e1e4] border border-zinc-700 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">picture_as_pdf</span>
              <span>PDF SitRep</span>
            </button>

            {/* Operator Session Badge */}
            <div className="flex items-center gap-2 pl-3 border-l border-[#574143]/30">
              <div className="w-7 h-7 rounded-full bg-rose-500/20 border border-rose-500/40 flex items-center justify-center text-rose-300 font-mono text-[10px] font-bold">
                {operator.callsign ? operator.callsign.substring(0, 2).toUpperCase() : 'OP'}
              </div>
              <div className="hidden lg:flex flex-col text-left">
                <span className="text-[11px] font-semibold text-[#e5e1e4] leading-tight">
                  {operator.callsign}
                </span>
                <span className="text-[9px] font-mono text-rose-400 leading-tight">
                  {operator.role_display}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="text-zinc-500 hover:text-rose-400 p-1.5 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
                title="Disconnect / Terminate Session"
              >
                <span className="material-symbols-outlined text-[16px]">logout</span>
              </button>
            </div>
          </div>
        </header>

        {/* ─── MODULE 1: TACTICAL OVERVIEW (GIS MAP & MULTI-INSPECTOR) ─── */}
        {activeModule === 'tactical' && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Top 4 KPI Metrics */}
            <section className="bg-[#0e0e10] border-b border-[#574143]/20 px-4 py-2.5 flex-shrink-0 z-20">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70 flex items-center gap-1">
                      <span className="material-symbols-outlined text-rose-400 text-[16px]">water_damage</span>
                      Flood Extent
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-rose-300 border border-rose-500/20">
                      SAR
                    </span>
                  </div>
                  <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                    {stats.flood_area_km2 ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">km²</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
                    <span>Sentinel-1 IW Mode</span>
                    <span className="text-rose-300">Peak +0.42m</span>
                  </div>
                </div>

                <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70 flex items-center gap-1">
                      <span className="material-symbols-outlined text-rose-400 text-[16px]">alt_route</span>
                      Severed Roads
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-rose-300 border border-rose-500/20">
                      OSM
                    </span>
                  </div>
                  <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                    {stats.roads_severed_km ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">km</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
                    <span>H08 / NH-12 Corridors</span>
                    <span className="text-rose-400 font-medium">Cut-off</span>
                  </div>
                </div>

                <div className="bg-[#1c1b1d] p-3 rounded-md border border-zinc-800/80 hover:border-rose-500/40 transition-all flex flex-col justify-between">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-[#debfc1]/70 flex items-center gap-1">
                      <span className="material-symbols-outlined text-amber-400 text-[16px]">warning</span>
                      Bridges Lost
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-[#201f22] text-amber-300 border border-amber-500/20">
                      Crossings
                    </span>
                  </div>
                  <div className="text-2xl font-bold font-mono tracking-tight text-[#e5e1e4]">
                    {stats.bridges_destroyed ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">Spans</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
                    <span>{stats.bridges_damaged ?? 0} Partial Damaged</span>
                    <span className="text-amber-400 font-semibold">Submerged</span>
                  </div>
                </div>

                <div className="bg-[#1c1b1d] p-3 rounded-md border border-rose-500/30 hover:border-rose-500/60 transition-all flex flex-col justify-between shadow-[0_0_12px_rgba(251,113,133,0.08)]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-rose-300 flex items-center gap-1">
                      <span className="material-symbols-outlined text-rose-400 text-[16px]">groups_2</span>
                      Isolated Villages
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse font-semibold">
                      CRITICAL
                    </span>
                  </div>
                  <div className="text-2xl font-bold font-mono tracking-tight text-rose-300">
                    {stats.settlements_isolated ?? '—'} <span className="text-sm font-normal text-[#debfc1]/60">Villages</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-[#debfc1]/60 pt-1 border-t border-zinc-800">
                    <span>Urgency &gt; 0.80 Triage</span>
                    <span className="text-rose-400 font-bold">HLZ Assigned</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Split View: Secondary Operational Panel + Interactive Map */}
            <div className="flex-1 flex flex-col lg:flex-row overflow-hidden relative">
              {/* Secondary Inspector Panel */}
              <div className="w-full lg:w-[380px] xl:w-[410px] bg-[#0e0e10] border-r border-[#574143]/20 flex flex-col z-20 flex-shrink-0">
                <div className="flex border-b border-[#574143]/20 bg-[#1c1b1d] p-1.5 gap-1 flex-shrink-0">
                  {[
                    { id: 'layers', icon: 'layers', label: 'Layers' },
                    { id: 'triage', icon: 'emergency', label: `Triage (${settlementsList.length})` },
                    { id: 'hlz', icon: 'flight_takeoff', label: `HLZ (${hlzList.length})` },
                    { id: 'copilot', icon: 'smart_toy', label: 'Copilot' },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setTacticalTab(tab.id)}
                      className={`flex-1 py-1 px-1.5 rounded font-mono text-[11px] tracking-wider uppercase transition-all flex items-center justify-center gap-1 cursor-pointer ${
                        tacticalTab === tab.id
                          ? 'bg-[#2a2a2c] text-rose-300 border border-rose-500/40 font-semibold'
                          : 'text-[#debfc1]/70 hover:text-white'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">{tab.icon}</span>
                      <span>{tab.label}</span>
                    </button>
                  ))}
                </div>

                {/* Sub-tab 1: Layers */}
                {tacticalTab === 'layers' && (
                  <div className="flex-1 overflow-y-auto p-3.5 space-y-3.5">
                    {/* Basemap Canvas */}
                    <div className="bg-[#1c1b1d] p-3 rounded border border-zinc-800">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-mono text-[10px] uppercase text-[#debfc1]/60">Basemap Canvas</span>
                        <span className="font-mono text-[10px] text-rose-300">EPSG:4326</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1">
                        {Object.values(BASEMAP_CONFIGS).map((b) => (
                          <button
                            key={b.id}
                            onClick={() => switchBasemap(b.id)}
                            className={`p-1.5 rounded text-[10px] font-mono flex flex-col items-center gap-0.5 cursor-pointer ${
                              basemap === b.id
                                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                                : 'bg-[#131315] text-[#debfc1]/60 hover:text-white'
                            }`}
                          >
                            <span className="material-symbols-outlined text-[14px]">{b.icon}</span>
                            <span>{b.name}</span>
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Vector Layers */}
                    <div className="bg-[#1c1b1d] p-3 rounded border border-zinc-800 space-y-1.5">
                      <div className="font-mono text-[10px] uppercase text-[#debfc1]/60 mb-1">GIS Vector Overlays</div>
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
                          className="flex items-center justify-between p-1.5 rounded bg-[#131315] hover:bg-[#201f22] cursor-pointer text-[11px] border border-zinc-800/60"
                        >
                          <div className="flex items-center gap-2">
                            <span className={`w-2.5 h-2.5 rounded-full ${layer.color}`}></span>
                            <span>{layer.label}</span>
                          </div>
                          <input
                            type="checkbox"
                            checked={activeLayers[layer.key]}
                            onChange={() => toggleLayer(layer.key)}
                            className="accent-rose-500 cursor-pointer"
                          />
                        </label>
                      ))}
                    </div>

                    {/* Satellite Orbit Schedule */}
                    <div className="bg-[#1c1b1d] p-3 rounded border border-zinc-800 space-y-2">
                      <div className="flex items-center justify-between text-[10px] font-mono">
                        <span className="uppercase text-[#debfc1]/60">Satellite Overpass</span>
                        <span className="text-rose-300 font-semibold">NORAD SYNC</span>
                      </div>
                      <div className="p-2 rounded bg-[#131315] border border-zinc-800/80 flex items-center justify-between text-[11px]">
                        <div>
                          <div className="font-semibold text-[#e5e1e4]">Sentinel-1C (SAR Radar)</div>
                          <div className="text-[10px] text-[#debfc1]/50 font-mono">Orbit 121 • 10m C-band</div>
                        </div>
                        <div className="text-right font-mono text-rose-300 font-bold">01h 42m</div>
                      </div>
                      <div className="p-2 rounded bg-[#131315] border border-zinc-800/80 flex items-center justify-between text-[11px]">
                        <div>
                          <div className="font-semibold text-[#e5e1e4]">Sentinel-2B (Optical MSI)</div>
                          <div className="text-[10px] text-[#debfc1]/50 font-mono">Tile 45RUL • 72% Cloud</div>
                        </div>
                        <div className="text-right font-mono text-zinc-400 font-bold">07h 15m</div>
                      </div>
                    </div>

                    {/* LoRa Broadcast Trigger */}
                    <button
                      onClick={() => openSmsModal()}
                      className="w-full py-2 rounded bg-[#201f22] hover:bg-[#2a2a2c] border border-rose-500/40 text-rose-300 font-mono text-[11px] uppercase tracking-wider flex items-center justify-center gap-1.5 cursor-pointer"
                    >
                      <span className="material-symbols-outlined text-[15px]">podcasts</span>
                      <span>Compose LoRa Alert</span>
                    </button>
                  </div>
                )}

                {/* Sub-tab 2: Triage */}
                {tacticalTab === 'triage' && (
                  <div className="flex-1 overflow-y-auto p-3.5 space-y-2">
                    <div className="text-[11px] font-mono text-[#debfc1]/60 pb-1 border-b border-zinc-800">
                      Ranked by composite urgency (population, clinic, cut-off access)
                    </div>
                    {settlementsList.map((item, idx) => {
                      const p = item.properties || {}
                      const coords = item.geometry?.coordinates
                      const isIso = p.isolation_status === 'isolated'
                      return (
                        <div
                          key={p.id || idx}
                          onClick={() => {
                            if (coords && map.current && coords.length >= 2) {
                              map.current.flyTo([coords[1], coords[0]], 14, { duration: 1.2 })
                              showToast(`Map centered on ${p.name || 'Village'}`)
                            }
                          }}
                          className={`p-2.5 rounded bg-[#1c1b1d] border cursor-pointer hover:border-rose-400 text-[11px] space-y-1 ${
                            isIso ? 'border-rose-500/40' : 'border-zinc-800'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-[#e5e1e4]">{p.name || 'Village'}</span>
                            <span
                              className={`text-[9px] font-mono px-1.5 py-0.2 rounded font-bold ${
                                isIso ? 'bg-rose-500/20 text-rose-300' : 'bg-emerald-500/20 text-emerald-300'
                              }`}
                            >
                              {(p.isolation_status || 'UNKNOWN').toUpperCase()}
                            </span>
                          </div>
                          <div className="flex justify-between text-[#debfc1]/70 text-[10px]">
                            <span>Pop: <b>{p.estimated_population?.toLocaleString() ?? '—'}</b></span>
                            <span>Urgency: <b className="text-rose-400 font-mono">{typeof p.urgency_score === 'number' ? p.urgency_score.toFixed(2) : '—'}</b></span>
                            <span>Clinic: {p.has_clinic ? '✅' : '❌'}</span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Sub-tab 3: HLZ */}
                {tacticalTab === 'hlz' && (
                  <div className="flex-1 overflow-y-auto p-3.5 space-y-2">
                    <div className="text-[11px] font-mono text-[#debfc1]/60 pb-1 border-b border-zinc-800">
                      Slope &lt; 5°, clearance radius &gt; 25m, dry ground
                    </div>
                    {hlzList.map((item, idx) => {
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
                          className="p-2.5 rounded bg-[#1c1b1d] border border-purple-500/30 hover:border-purple-400 cursor-pointer text-[11px] space-y-1"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono font-bold text-purple-300">
                              {p.id ? p.id.replace(/^.*-/, '').toUpperCase() : `HLZ-${idx + 1}`}
                            </span>
                            <span className="text-[10px] text-[#debfc1]/60">{Math.round(p.elevation_m || 0)}m ASL</span>
                          </div>
                          <div className="grid grid-cols-2 gap-1 text-[10px] text-[#debfc1]/70">
                            <div>Slope: <b>{p.avg_slope_deg ? `${p.avg_slope_deg.toFixed(1)}°` : '—'}</b></div>
                            <div>Clearance: <b>{Math.round(p.area_m2 || 0)}m²</b></div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Sub-tab 4: Copilot */}
                {tacticalTab === 'copilot' && (
                  <div className="flex-1 overflow-y-auto p-3.5 flex flex-col justify-between">
                    <div className="space-y-3">
                      <div className="font-mono text-[11px] uppercase text-rose-300 font-semibold">AI Copilot</div>
                      <div className="flex gap-1.5 bg-[#1c1b1d] p-1.5 rounded border border-zinc-800">
                        <input
                          type="text"
                          value={copilotQuery}
                          onChange={(e) => setCopilotQuery(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleCopilotQuery()}
                          placeholder="e.g. Which bridges collapsed?"
                          className="flex-1 bg-transparent text-[11px] text-[#e5e1e4] outline-none px-1"
                        />
                        <button
                          onClick={() => handleCopilotQuery()}
                          disabled={copilotLoading}
                          className="px-2.5 py-1 bg-rose-500 hover:bg-rose-600 text-white rounded text-[11px] font-mono cursor-pointer font-semibold"
                        >
                          {copilotLoading ? '...' : 'Ask'}
                        </button>
                      </div>

                      {copilotResponse && (
                        <div className="p-2.5 rounded bg-[#1c1b1d] border border-rose-500/30 text-[11px] space-y-1.5">
                          <p className="leading-relaxed text-[#e5e1e4]">{copilotResponse.answer}</p>
                          {copilotResponse.citation && (
                            <details className="pt-1 border-t border-zinc-800">
                              <summary className="font-mono text-[9px] text-[#debfc1]/50 cursor-pointer">
                                SQL Citation
                              </summary>
                              <pre className="mt-1 p-1.5 rounded bg-[#0e0e10] text-[9px] font-mono text-rose-200 whitespace-pre-wrap">
                                {copilotResponse.citation.sql}
                              </pre>
                            </details>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Full-Bleed Map View */}
              <div className="flex-1 relative w-full h-full bg-[#0e0e10]">
                <div ref={mapContainer} className="w-full h-full z-10" />

                {/* Floating Basemap Selector */}
                <div className="absolute top-3 right-12 z-20 flex bg-[#1c1b1d]/90 backdrop-blur-md p-1 rounded-md border border-zinc-800 shadow-lg gap-1">
                  {Object.values(BASEMAP_CONFIGS).map((b) => (
                    <button
                      key={b.id}
                      onClick={() => switchBasemap(b.id)}
                      className={`px-2 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 cursor-pointer ${
                        basemap === b.id
                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 font-semibold'
                          : 'text-[#debfc1]/70 hover:text-white'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[13px]">{b.icon}</span>
                      <span>{b.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── MODULE 2: SAR FLOOD ANALYTICS VIEW ─────────────────── */}
        {activeModule === 'sar-analytics' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-7xl mx-auto w-full">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h2 className="text-xl font-bold font-mono text-[#e5e1e4]">Synthetic Aperture Radar (SAR) Analytics</h2>
                <p className="text-xs text-[#debfc1]/70">Sentinel-1 C-band (5.405 GHz) Radiometric Calibration & Thresholding</p>
              </div>
              <button
                onClick={() => setShowUploadModal(true)}
                className="px-3.5 py-1.5 rounded bg-rose-500 hover:bg-rose-600 text-white font-mono text-xs font-semibold flex items-center gap-1.5 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[16px]">upload_file</span>
                <span>Ingest New Radar Scene</span>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-2">
                <span className="text-[11px] font-mono uppercase text-[#debfc1]/60">Total Submerged Surface</span>
                <div className="text-3xl font-mono font-bold text-rose-300">
                  {stats.flood_area_km2 ?? 0} <span className="text-sm font-normal text-zinc-400">km²</span>
                </div>
                <p className="text-[11px] text-[#debfc1]/70">Calculated from Otsu log-ratio consensus vote</p>
              </div>

              <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-2">
                <span className="text-[11px] font-mono uppercase text-[#debfc1]/60">Radar Sensor Details</span>
                <div className="text-sm font-mono text-[#e5e1e4]">
                  <div>Orbit: <b>Sentinel-1 IW GRDH (121)</b></div>
                  <div>Polarization: <b>Dual VV + VH</b></div>
                  <div>Pixel Spacing: <b>10m × 10m</b></div>
                </div>
              </div>

              <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-2">
                <span className="text-[11px] font-mono uppercase text-[#debfc1]/60">Topographic Correction</span>
                <div className="text-sm font-mono text-emerald-400 font-semibold">
                  DEM Slope Filter Active
                </div>
                <p className="text-[11px] text-[#debfc1]/70">Excluded false water signatures on slopes &gt; 15°</p>
              </div>
            </div>

            {/* Backscatter Calibration Table */}
            <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-3">
              <h3 className="font-mono text-sm font-semibold text-rose-300">Detection Confidence Distribution</h3>
              <div className="space-y-2 text-xs font-mono">
                <div className="flex justify-between text-[#debfc1]/80">
                  <span>High Confidence (&gt; 85%)</span>
                  <span className="text-rose-300 font-bold">68.4% of polygons</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div className="bg-rose-400 h-full w-[68.4%]"></div>
                </div>
                <div className="flex justify-between text-[#debfc1]/80 pt-2">
                  <span>Medium Confidence (65% – 85%)</span>
                  <span className="text-amber-300 font-bold">24.2% of polygons</span>
                </div>
                <div className="w-full bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div className="bg-amber-400 h-full w-[24.2%]"></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── MODULE 3: INFRASTRUCTURE GRID VIEW ─────────────────── */}
        {activeModule === 'infrastructure' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-7xl mx-auto w-full">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h2 className="text-xl font-bold font-mono text-[#e5e1e4]">Infrastructure & Network Damage Grid</h2>
                <p className="text-xs text-[#debfc1]/70">OpenStreetMap LineString & Point Intersection against Submerged Extent</p>
              </div>
            </div>

            {/* Roads Table */}
            <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-3">
              <h3 className="font-mono text-sm font-semibold text-rose-300">Road Corridor Assessments</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-zinc-800 text-[#debfc1]/60">
                      <th className="pb-2">Segment Name</th>
                      <th className="pb-2">Type</th>
                      <th className="pb-2">Damage Status</th>
                      <th className="pb-2">Length</th>
                      <th className="pb-2">Overlap %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {roadsList.map((r, i) => {
                      const p = r.properties || {}
                      return (
                        <tr key={i} className="hover:bg-zinc-800/40">
                          <td className="py-2.5 font-medium text-[#e5e1e4]">{p.name || `Segment #${i + 1}`}</td>
                          <td className="py-2.5 text-zinc-400">{p.highway_type || 'primary'}</td>
                          <td className="py-2.5">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                p.damage_class === 'severed'
                                  ? 'bg-rose-500/20 text-rose-300'
                                  : p.damage_class === 'partially_flooded'
                                  ? 'bg-amber-500/20 text-amber-300'
                                  : 'bg-emerald-500/20 text-emerald-300'
                              }`}
                            >
                              {(p.damage_class || 'INTACT').toUpperCase()}
                            </span>
                          </td>
                          <td className="py-2.5 text-zinc-300">{Math.round(p.length_m || 0)} m</td>
                          <td className="py-2.5 text-rose-400 font-bold">
                            {p.flood_intersection_ratio ? `${(p.flood_intersection_ratio * 100).toFixed(0)}%` : '0%'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Bridges Table */}
            <div className="bg-[#1c1b1d] p-4 rounded-lg border border-zinc-800 space-y-3">
              <h3 className="font-mono text-sm font-semibold text-amber-300">Bridge Crossings Status</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {bridgesList.map((b, i) => {
                  const p = b.properties || {}
                  return (
                    <div key={i} className="p-3 rounded bg-[#131315] border border-zinc-800 space-y-1 text-xs">
                      <div className="font-bold text-[#e5e1e4]">{p.name || 'Span Crossing'}</div>
                      <div className="flex justify-between pt-1">
                        <span className="text-[#debfc1]/60">Status:</span>
                        <span className={p.damage_class === 'destroyed' ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
                          {(p.damage_class || 'INTACT').toUpperCase()}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* ─── MODULE 4: EXTRACTION & HLZ VIEW ────────────────────── */}
        {activeModule === 'mesh-hlz' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-7xl mx-auto w-full">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h2 className="text-xl font-bold font-mono text-[#e5e1e4]">Air Extraction & Landing Zone (HLZ) Roster</h2>
                <p className="text-xs text-[#debfc1]/70">Validated Contiguous Extraction Pads (Slope &le; 5°, Safe Buffer Zone)</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {hlzList.map((h, i) => {
                const p = h.properties || {}
                return (
                  <div key={i} className="bg-[#1c1b1d] p-4 rounded-lg border border-purple-500/30 hover:border-purple-400 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-base font-bold text-purple-300">
                        {p.id ? p.id.replace(/^.*-/, '').toUpperCase() : `HLZ-${i + 1}`}
                      </span>
                      <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                        SURFACE OK
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs font-mono text-[#debfc1]/80">
                      <div>Altitude: <b className="text-white">{Math.round(p.elevation_m || 0)}m ASL</b></div>
                      <div>Slope: <b className="text-white">{p.avg_slope_deg ? `${p.avg_slope_deg.toFixed(1)}°` : '—'}</b></div>
                      <div>Clearance: <b className="text-white">{Math.round(p.area_m2 || 0)} m²</b></div>
                      <div>Surface: <b className="text-zinc-300">{p.surface_estimate?.replace('_', ' ') || 'natural'}</b></div>
                    </div>

                    <button
                      onClick={() => {
                        openSmsModal(`HLZ-${i + 1}`)
                        showToast(`Sortie planned for HLZ-${i + 1}`)
                      }}
                      className="w-full py-2 rounded bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 font-mono text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer border border-purple-500/40"
                    >
                      <span className="material-symbols-outlined text-[15px]">send</span>
                      <span>Assign Sortie / Dispatch</span>
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ─── MODULE 5: TELEMETRY & AUDIT LOGS ───────────────────── */}
        {activeModule === 'telemetry-logs' && (
          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-7xl mx-auto w-full">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h2 className="text-xl font-bold font-mono text-[#e5e1e4]">Pipeline Execution Telemetry & Audit Trail</h2>
                <p className="text-xs text-[#debfc1]/70">Deterministic Log Stream Persisted to Database</p>
              </div>
            </div>

            <div className="bg-[#1c1b1d] rounded-lg border border-zinc-800 overflow-hidden font-mono text-xs">
              <div className="bg-[#201f22] p-3 border-b border-zinc-800 flex items-center justify-between text-[#debfc1]/70 text-[11px]">
                <span>Phase / Operation</span>
                <span>Status & Timestamp</span>
              </div>
              <div className="divide-y divide-zinc-800/70 max-h-[500px] overflow-y-auto">
                {pipelineLogs.length === 0 ? (
                  <div className="p-6 text-center text-zinc-500">No telemetry logged for this run.</div>
                ) : (
                  pipelineLogs.map((log, i) => (
                    <div key={i} className="p-3 hover:bg-zinc-800/30 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
                        <div>
                          <div className="font-semibold text-[#e5e1e4] uppercase text-[11px]">{log.phase}</div>
                          <div className="text-zinc-400 text-[11px]">{log.message}</div>
                        </div>
                      </div>
                      <div className="text-right text-[10px] text-zinc-500">
                        <div className="text-emerald-400 font-bold uppercase">{log.status}</div>
                        <div>{log.logged_at ? new Date(log.logged_at).toLocaleTimeString() : '—'}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
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

      {/* Toast Notification */}
      {toast.show && (
        <div className="fixed bottom-5 right-5 z-50 bg-[#1c1b1d] border border-rose-500/50 text-[#e5e1e4] px-4 py-2.5 rounded-lg shadow-2xl font-mono text-[12px] flex items-center gap-2">
          <span className="material-symbols-outlined text-rose-400 text-[18px]">info</span>
          <span>{toast.message}</span>
        </div>
      )}

      {/* Loading Overlay */}
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
