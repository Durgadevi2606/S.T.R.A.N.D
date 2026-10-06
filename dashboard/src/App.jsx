import { useState, useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

const API_BASE = 'http://localhost:8000/api/v1'
const API_KEY = 'dev-key-change-in-production'

const LAYER_COLORS = {
  flood: { fill: '#1f6feb', stroke: '#1f6feb' },
  roads_intact: '#3fb950',
  roads_partial: '#d29922',
  roads_severed: '#f85149',
  bridges_intact: '#3fb950',
  bridges_damaged: '#d29922',
  bridges_destroyed: '#f85149',
  settlements_connected: '#3fb950',
  settlements_degraded: '#d29922',
  settlements_isolated: '#f85149',
  hlz: '#a371f7',
  ponding: '#f778ba',
}

const BASEMAP_CONFIGS = {
  satellite: {
    id: 'satellite',
    name: 'Satellite',
    icon: '🛰️',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics',
    maxZoom: 19,
  },
  dark: {
    id: 'dark',
    name: 'Dark Canvas',
    icon: '🌑',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
    maxZoom: 16,
  },
  osm: {
    id: 'osm',
    name: 'Streets',
    icon: '🗺️',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  },
}

// Nepal center coordinates [lat, lon] for Leaflet
const NEPAL_CENTER = [27.88, 85.92]
const NEPAL_ZOOM = 11

function App() {
  const mapContainer = useRef(null)
  const map = useRef(null)
  const layerGroups = useRef({})
  const baseTileLayer = useRef(null)
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
  const [copilotQuery, setCopilotQuery] = useState('')
  const [copilotResponse, setCopilotResponse] = useState(null)
  const [copilotLoading, setCopilotLoading] = useState(false)
  const [sidebarTab, setSidebarTab] = useState('layers')
  const [loading, setLoading] = useState(false)
  const [settlementsList, setSettlementsList] = useState([])
  const [hlzList, setHlzList] = useState([])
  const [smsAlerts, setSmsAlerts] = useState([])
  const [showSmsModal, setShowSmsModal] = useState(false)
  const [smsLoading, setSmsLoading] = useState(false)
  const [copiedIdx, setCopiedIdx] = useState(null)

  // Initialize Leaflet map
  useEffect(() => {
    if (map.current || !mapContainer.current) return

    const m = L.map(mapContainer.current, {
      center: NEPAL_CENTER,
      zoom: NEPAL_ZOOM,
      zoomControl: false,
    })

    L.control.zoom({ position: 'topright' }).addTo(m)
    L.control.scale({ imperial: false, position: 'bottomright' }).addTo(m)

    // High-resolution satellite basemap (100% free, no token/API key required!)
    const initialCfg = BASEMAP_CONFIGS.satellite
    const initialTile = L.tileLayer(initialCfg.url, {
      attribution: initialCfg.attribution,
      maxZoom: initialCfg.maxZoom,
    }).addTo(m)

    baseTileLayer.current = initialTile
    map.current = m

    // Fetch analyses on load
    fetchAnalyses()

    return () => {
      m.remove()
      map.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Switch active basemap tile layer
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
  }

  // Select and load an analysis
  const selectAnalysis = async (analysisId) => {
    setSelectedAnalysis(analysisId)
    setLoading(true)

    try {
      // Fetch analysis details
      const detailRes = await fetch(`${API_BASE}/analysis/${analysisId}`, {
        headers: { 'X-API-Key': API_KEY },
      })
      if (detailRes.ok) {
        const detail = await detailRes.json()
        setAnalysisData(detail)
      }

      // Load all layers
      await loadAllLayers(analysisId)
    } catch (e) {
      console.error('Failed to load analysis:', e)
    } finally {
      setLoading(false)
    }
  }

  // Fetch list of analyses
  const fetchAnalyses = async () => {
    try {
      const res = await fetch(`${API_BASE}/analysis`, {
        headers: { 'X-API-Key': API_KEY },
      })
      if (res.ok) {
        const data = await res.json()
        setAnalyses(data.analyses || [])
        if (data.analyses?.length > 0) {
          selectAnalysis(data.analyses[0].analysis_id)
        }
      }
    } catch (e) {
      console.error('Failed to fetch analyses:', e)
    }
  }

  // Create styled Leaflet layer from GeoJSON
  const createLeafletLayer = (layerName, geojson) => {
    switch (layerName) {
      case 'flood':
        return L.geoJSON(geojson, {
          style: {
            color: '#1f6feb',
            weight: 2,
            fillColor: '#1f6feb',
            fillOpacity: 0.45,
          },
          onEachFeature: (feature, layer) => {
            const area = feature.properties?.area_km2 || (feature.properties?.area_m2 ? (feature.properties.area_m2 / 1e6).toFixed(2) : '—')
            const conf = feature.properties?.confidence ? `${(feature.properties.confidence * 100).toFixed(0)}%` : 'Verified'
            layer.bindPopup(`<div class="leaflet-popup-card"><strong>🌊 Flood Inundation Extent</strong><br/>Area: <b>${area} km²</b><br/>Confidence: <b>${conf}</b><br/>Method: ${feature.properties?.detection_method || 'Ensemble'}</div>`)
          }
        })

      case 'roads':
        return L.geoJSON(geojson, {
          style: (feature) => {
            const dmg = feature.properties?.damage_class
            const color = dmg === 'severed' ? LAYER_COLORS.roads_severed : dmg === 'partially_flooded' ? LAYER_COLORS.roads_partial : LAYER_COLORS.roads_intact
            const weight = dmg === 'severed' ? 3.5 : dmg === 'partially_flooded' ? 2.5 : 1.5
            return { color, weight, opacity: 0.95 }
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`<div class="leaflet-popup-card"><strong>🛣️ ${p.name || 'Road Segment'}</strong><br/>Damage: <span class="badge-${p.damage_class}">${p.damage_class?.toUpperCase()}</span><br/>Length: ${Math.round(p.length_m || 0)}m<br/>Flood Overlap: ${p.flood_intersection_ratio ? `${(p.flood_intersection_ratio * 100).toFixed(0)}%` : '0%'}</div>`)
          }
        })

      case 'bridges':
        return L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => {
            const dmg = feature.properties?.damage_class
            const color = dmg === 'destroyed' ? LAYER_COLORS.bridges_destroyed : dmg === 'damaged' ? LAYER_COLORS.bridges_damaged : LAYER_COLORS.bridges_intact
            return L.circleMarker(latlng, {
              radius: 7,
              fillColor: color,
              color: '#0d1117',
              weight: 2,
              fillOpacity: 0.95,
            })
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`<div class="leaflet-popup-card"><strong>🌉 ${p.name || 'Bridge'}</strong><br/>Damage: <span class="badge-${p.damage_class}">${p.damage_class?.toUpperCase()}</span><br/>Buffer Flood Overlap: ${p.buffer_flood_ratio ? `${(p.buffer_flood_ratio * 100).toFixed(0)}%` : '0%'}</div>`)
          }
        })

      case 'settlements':
        return L.geoJSON(geojson, {
          pointToLayer: (feature, latlng) => {
            const iso = feature.properties?.isolation_status
            const color = iso === 'isolated' ? LAYER_COLORS.settlements_isolated : iso === 'degraded' ? LAYER_COLORS.settlements_degraded : LAYER_COLORS.settlements_connected
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
                <strong>🏘️ ${p.name || 'Village'}</strong><br/>
                Status: <span class="badge-${p.isolation_status}">${p.isolation_status?.toUpperCase()}</span><br/>
                Population: <b>${p.estimated_population?.toLocaleString() ?? '—'}</b><br/>
                Urgency Score: <b style="color: #f85149;">${typeof p.urgency_score === 'number' ? p.urgency_score.toFixed(2) : '—'}</b><br/>
                Clinic: ${p.has_clinic ? '✅ Available' : '❌ None'}<br/>
                ${p.nearest_hlz_id ? `Target LZ: <b>${p.nearest_hlz_id.replace(/^.*-/, '').toUpperCase()}</b>` : ''}
              </div>
            `)
          }
        })

      case 'hlz':
        return L.geoJSON(geojson, {
          style: {
            color: LAYER_COLORS.hlz,
            weight: 2,
            fillColor: LAYER_COLORS.hlz,
            fillOpacity: 0.45,
          },
          pointToLayer: (feature, latlng) => {
            return L.circleMarker(latlng, {
              radius: 8,
              fillColor: LAYER_COLORS.hlz,
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95,
            })
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>🚁 Helicopter Landing Zone (${p.id ? p.id.replace(/^.*-/, '').toUpperCase() : 'HLZ'})</strong><br/>
                Slope: <b>${p.avg_slope_deg ? `${p.avg_slope_deg.toFixed(1)}°` : '—'}</b><br/>
                Clearance: <b>${p.area_m2 ? `${Math.round(p.area_m2)} m²` : '—'}</b><br/>
                Elevation: <b>${p.elevation_m ? `${Math.round(p.elevation_m)} m ASL` : '—'}</b><br/>
                Surface: ${p.surface_estimate ? p.surface_estimate.replace('_', ' ') : 'natural terrace'}<br/>
                Dist to Settlement: <b>${p.dist_to_settlement_m ? `${Math.round(p.dist_to_settlement_m)} m` : '—'}</b>
              </div>
            `)
          }
        })

      case 'ponding':
        return L.geoJSON(geojson, {
          style: {
            color: LAYER_COLORS.ponding,
            weight: 2,
            fillColor: LAYER_COLORS.ponding,
            fillOpacity: 0.45,
          },
          onEachFeature: (feature, layer) => {
            const p = feature.properties || {}
            layer.bindPopup(`
              <div class="leaflet-popup-card">
                <strong>⚠️ Debris Dam Ponding Hazard</strong><br/>
                Risk Level: <span class="badge-${p.risk_level}">${p.risk_level?.toUpperCase()}</span><br/>
                Volume: <b>${p.estimated_volume_m3 ? p.estimated_volume_m3.toLocaleString() : '—'} m³</b><br/>
                Dam Elevation: <b>${p.dam_elevation_m} m</b>
              </div>
            `)
          }
        })

      default:
        return L.geoJSON(geojson)
    }
  }

  // Load all GeoJSON layers
  const loadAllLayers = async (analysisId) => {
    const m = map.current
    if (!m) return

    // Clear existing layer groups
    Object.values(layerGroups.current).forEach(lg => {
      if (m.hasLayer(lg)) m.removeLayer(lg)
    })
    layerGroups.current = {}

    const layers = ['flood', 'roads', 'bridges', 'settlements', 'hlz', 'ponding']
    for (const layer of layers) {
      try {
        const res = await fetch(`${API_BASE}/layers/${analysisId}/${layer}`, {
          headers: { 'X-API-Key': API_KEY },
        })
        if (!res.ok) continue
        const geojson = await res.json()
        if (!geojson.features?.length) continue

        const leafletLayer = createLeafletLayer(layer, geojson)
        layerGroups.current[layer] = leafletLayer

        if (activeLayers[layer]) {
          leafletLayer.addTo(m)
        }

        if (layer === 'settlements') {
          setSettlementsList(geojson.features || [])
        } else if (layer === 'hlz') {
          setHlzList(geojson.features || [])
        }
      } catch (e) {
        console.warn(`Failed to load ${layer} layer:`, e)
      }
    }
  }

  // Toggle layer visibility
  const toggleLayer = (layerName) => {
    setActiveLayers(prev => {
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
  }

  // Copilot query
  const handleCopilotQuery = async () => {
    if (!copilotQuery.trim() || !selectedAnalysis) return
    setCopilotLoading(true)
    setCopilotResponse(null)

    try {
      const res = await fetch(`${API_BASE}/copilot/${selectedAnalysis}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({
          query: copilotQuery,
          language: 'en',
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setCopilotResponse(data)
      } else {
        setCopilotResponse({ answer: 'Query failed. Please try again.', confidence: 'low' })
      }
    } catch (e) {
      setCopilotResponse({ answer: `Error: ${e.message}`, confidence: 'low' })
    } finally {
      setCopilotLoading(false)
    }
  }

  // Export SitRep
  const exportSitRep = async () => {
    if (!selectedAnalysis) return
    try {
      const res = await fetch(`${API_BASE}/export/${selectedAnalysis}/sitrep`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `sitrep_${selectedAnalysis.slice(0, 8)}.pdf`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (e) {
      console.error('Export failed:', e)
    }
  }

  const stats = analysisData?.summary || {}

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <header className="sidebar-header">
          <h1 className="logo">
            <span className="logo-icon">🛰️</span>
            <span className="logo-text">S.T.R.A.N.D</span>
          </h1>
          <p className="logo-subtitle">Satellite Terrain Response & Network Damage</p>
          {analyses.length > 0 && (
            <div className="analysis-selector-wrapper">
              <select
                className="analysis-dropdown"
                value={selectedAnalysis || ''}
                onChange={(e) => selectAnalysis(e.target.value)}
              >
                {analyses.map(a => (
                  <option key={a.analysis_id} value={a.analysis_id}>
                    {a.analysis_id.slice(0, 18)} — {a.status}
                  </option>
                ))}
              </select>
            </div>
          )}
        </header>

        {/* Tabs */}
        <nav className="sidebar-tabs">
          {[
            { id: 'layers', icon: '🗺️', label: 'Layers' },
            { id: 'triage', icon: '🚨', label: 'Triage' },
            { id: 'hlz', icon: '🚁', label: 'HLZ' },
            { id: 'copilot', icon: '🤖', label: 'Copilot' },
          ].map(tab => (
            <button
              key={tab.id}
              className={`tab-btn ${sidebarTab === tab.id ? 'active' : ''}`}
              onClick={() => setSidebarTab(tab.id)}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-content">
          {/* Stats Banner */}
          {analysisData && (
            <div className="stats-banner">
              <div className="stat-card flood">
                <span className="stat-value">{stats.flood_area_km2 ?? '—'}</span>
                <span className="stat-label">Flood km²</span>
              </div>
              <div className="stat-card danger">
                <span className="stat-value">{stats.settlements_isolated ?? '—'}</span>
                <span className="stat-label">Isolated</span>
              </div>
              <div className="stat-card warning">
                <span className="stat-value">{stats.roads_severed_km ?? '—'}</span>
                <span className="stat-label">Roads Severed km</span>
              </div>
              <div className="stat-card info">
                <span className="stat-value">{stats.bridges_destroyed ?? '—'}</span>
                <span className="stat-label">Bridges Lost</span>
              </div>
            </div>
          )}

          {/* Layers Tab */}
          {sidebarTab === 'layers' && (
            <div className="layers-panel">
              <div className="section-title-row">
                <h3>Basemap Style</h3>
              </div>
              <div className="basemap-selector-grid">
                {Object.values(BASEMAP_CONFIGS).map(b => (
                  <button
                    key={b.id}
                    className={`basemap-pill-btn ${basemap === b.id ? 'active' : ''}`}
                    onClick={() => switchBasemap(b.id)}
                  >
                    <span>{b.icon}</span>
                    <span>{b.name}</span>
                  </button>
                ))}
              </div>

              <div className="section-title-row" style={{ marginTop: '16px' }}>
                <h3>Disaster Layers</h3>
              </div>
              {Object.entries(activeLayers).map(([name, active]) => (
                <label key={name} className="layer-toggle">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleLayer(name)}
                  />
                  <span className={`layer-dot ${name}`}></span>
                  <span className="layer-name">{name.charAt(0).toUpperCase() + name.slice(1)}</span>
                </label>
              ))}

              <div className="layer-legend">
                <h4>Legend</h4>
                <div className="legend-row"><span className="legend-swatch" style={{background: '#3fb950'}}></span> Intact</div>
                <div className="legend-row"><span className="legend-swatch" style={{background: '#d29922'}}></span> Degraded / Damaged</div>
                <div className="legend-row"><span className="legend-swatch" style={{background: '#f85149'}}></span> Severed / Destroyed / Isolated</div>
                <div className="legend-row"><span className="legend-swatch" style={{background: '#a371f7'}}></span> HLZ Candidate</div>
                <div className="legend-row"><span className="legend-swatch" style={{background: '#1f6feb'}}></span> Flood Extent</div>
              </div>

              <div className="satellite-revisit-card">
                <h4>🛰️ Satellite Pass Tracker</h4>
                <div className="revisit-item">
                  <span className="sat-name">Sentinel-1 (SAR)</span>
                  <span className="sat-time">Pass in ~14h 20m</span>
                </div>
                <div className="revisit-sub">Orbit 121 • Descending • 10m C-band</div>
                <div className="revisit-item" style={{ marginTop: '6px' }}>
                  <span className="sat-name">Sentinel-2 (Optical)</span>
                  <span className="sat-time">Pass in ~28h 15m</span>
                </div>
                <div className="revisit-sub">Tile 45RUL • Cloud cover est. 72%</div>
              </div>

              <div className="export-actions">
                <button className="export-btn" onClick={exportSitRep}>
                  📄 Export PDF SitRep
                </button>
                <button
                  className="export-btn sms"
                  onClick={async () => {
                    if (!selectedAnalysis) return
                    setSmsLoading(true)
                    try {
                      const res = await fetch(`${API_BASE}/export/${selectedAnalysis}/sms`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
                        body: JSON.stringify({ max_chars: 140 }),
                      })
                      if (res.ok) {
                        const data = await res.json()
                        setSmsAlerts(data)
                        setShowSmsModal(true)
                      }
                    } catch (e) {
                      console.error('Failed to get SMS alerts:', e)
                    } finally {
                      setSmsLoading(false)
                    }
                  }}
                  disabled={smsLoading}
                >
                  {smsLoading ? '...' : '📱 Compose SMS/LoRa Alerts'}
                </button>
              </div>
            </div>
          )}

          {/* Triage Tab */}
          {sidebarTab === 'triage' && (
            <div className="triage-panel">
              <div className="panel-title-row">
                <h3>🚨 Isolation Triage</h3>
                <span className="count-pill">{settlementsList.length} settlements</span>
              </div>
              <p className="triage-desc">Ranked by urgency score (population, flood proximity, clinic access)</p>

              <div className="triage-list">
                {settlementsList.length === 0 ? (
                  <div className="triage-empty">Select or run an analysis to view triage queue</div>
                ) : (
                  [...settlementsList]
                    .sort((a, b) => (b.properties?.urgency_score || 0) - (a.properties?.urgency_score || 0))
                    .map((item, idx) => {
                      const p = item.properties || {}
                      const coords = item.geometry?.coordinates
                      const isIso = p.isolation_status === 'isolated'
                      const isDeg = p.isolation_status === 'degraded'
                      const badgeClass = isIso ? 'isolated' : isDeg ? 'degraded' : 'connected'

                      return (
                        <div
                          key={p.id || idx}
                          className={`triage-card ${isIso ? 'border-isolated' : ''}`}
                          onClick={() => {
                            if (coords && map.current && coords.length >= 2) {
                              map.current.flyTo([coords[1], coords[0]], 14, { duration: 1.2 })
                            }
                          }}
                        >
                          <div className="triage-card-header">
                            <span className="settlement-name">{p.name || 'Unnamed Village'}</span>
                            <span className={`status-badge ${badgeClass}`}>
                              {p.isolation_status?.toUpperCase() || 'UNKNOWN'}
                            </span>
                          </div>
                          <div className="triage-card-grid">
                            <div><span className="lbl">Pop:</span> <strong>{p.estimated_population?.toLocaleString() ?? '—'}</strong></div>
                            <div><span className="lbl">Urgency:</span> <strong className="urgency-num">{typeof p.urgency_score === 'number' ? p.urgency_score.toFixed(2) : '—'}</strong></div>
                            <div><span className="lbl">Clinic:</span> {p.has_clinic ? '✅ Available' : '❌ None'}</div>
                            <div><span className="lbl">Type:</span> {p.place_type || 'settlement'}</div>
                          </div>
                          {p.nearest_hlz_id && (
                            <div className="nearest-hlz-tag">
                              🚁 Target LZ: <strong>{p.nearest_hlz_id.replace(/^.*-/, '').toUpperCase()}</strong>
                            </div>
                          )}
                        </div>
                      )
                    })
                )}
              </div>
            </div>
          )}

          {/* HLZ Tab */}
          {sidebarTab === 'hlz' && (
            <div className="hlz-panel">
              <div className="panel-title-row">
                <h3>🚁 Landing Zones</h3>
                <span className="count-pill">{hlzList.length} sites</span>
              </div>
              <p className="triage-desc">DEM slope analysis &lt; 5°, flood exclusion zones applied</p>

              <div className="hlz-list">
                {hlzList.length === 0 ? (
                  <div className="triage-empty">No helicopter landing zones detected</div>
                ) : (
                  hlzList.map((item, idx) => {
                    const p = item.properties || {}
                    const coords = item.geometry?.type === 'Point'
                      ? item.geometry.coordinates
                      : item.geometry?.coordinates?.[0]?.[0]

                    return (
                      <div
                        key={p.id || idx}
                        className="hlz-card"
                        onClick={() => {
                          if (coords && map.current && coords.length >= 2) {
                            map.current.flyTo([coords[1], coords[0]], 15, { duration: 1.2 })
                          }
                        }}
                      >
                        <div className="hlz-card-header">
                          <span className="hlz-id">{p.id ? p.id.replace(/^.*-/, '').toUpperCase() : `HLZ-${idx + 1}`}</span>
                          <span className="hlz-elev">{p.elevation_m ? `${Math.round(p.elevation_m)}m ASL` : '—'}</span>
                        </div>
                        <div className="hlz-card-grid">
                          <div><span className="lbl">Slope:</span> <strong>{p.avg_slope_deg ? `${p.avg_slope_deg.toFixed(1)}°` : '—'}</strong></div>
                          <div><span className="lbl">Clearance:</span> <strong>{p.area_m2 ? `${Math.round(p.area_m2)}m²` : '—'}</strong></div>
                          <div><span className="lbl">Surface:</span> {p.surface_estimate ? p.surface_estimate.replace('_', ' ') : 'natural'}</div>
                          <div><span className="lbl">Dist to Vill:</span> {p.dist_to_settlement_m ? `${Math.round(p.dist_to_settlement_m)}m` : '—'}</div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          )}

          {/* Copilot Tab */}
          {sidebarTab === 'copilot' && (
            <div className="copilot-panel">
              <h3>🤖 Emergency AI Copilot</h3>
              <p className="copilot-desc">Grounded natural language queries in English or Nepali with verified SQL citations</p>
              <div className="copilot-input">
                <input
                  type="text"
                  placeholder="e.g., How many settlements are isolated? / कति बस्ती अलग छन्?"
                  value={copilotQuery}
                  onChange={(e) => setCopilotQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCopilotQuery()}
                />
                <button onClick={handleCopilotQuery} disabled={copilotLoading}>
                  {copilotLoading ? '...' : '→'}
                </button>
              </div>
              {copilotResponse && (
                <div className={`copilot-response ${copilotResponse.confidence}`}>
                  <div className="copilot-answer">{copilotResponse.answer}</div>
                  {copilotResponse.citation && (
                    <details className="copilot-citation">
                      <summary>SQL Citation</summary>
                      <code>{copilotResponse.citation.sql}</code>
                    </details>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer with attributions */}
        <footer className="sidebar-footer">
          <p>Contains modified Copernicus Sentinel data 2026.</p>
          <p>© OpenStreetMap contributors.</p>
          <p>S.T.R.A.N.D v1.0 — Multimodal AI Hackathon 2026</p>
        </footer>
      </aside>

      {/* Map */}
      <main className="map-container" ref={mapContainer}>
        {/* Floating Basemap Selector */}
        <div className="floating-basemap-bar">
          {Object.values(BASEMAP_CONFIGS).map(b => (
            <button
              key={b.id}
              className={`float-btn ${basemap === b.id ? 'active' : ''}`}
              onClick={() => switchBasemap(b.id)}
              title={`${b.name} Basemap (Free, No Key)`}
            >
              <span className="float-icon">{b.icon}</span>
              <span className="float-name">{b.name}</span>
            </button>
          ))}
        </div>
      </main>

      {/* Loading overlay */}
      {loading && (
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
          <p>Loading analysis data...</p>
        </div>
      )}

      {/* SMS/LoRa Alerts Modal */}
      {showSmsModal && (
        <div className="modal-backdrop" onClick={() => setShowSmsModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📱 SMS / LoRa Field Alerts (&le; 140 Chars)</h3>
              <button className="modal-close" onClick={() => setShowSmsModal(false)}>&times;</button>
            </div>
            <p className="modal-subtitle">Compact tactical dispatches for satellite-mesh and low-bandwidth emergency links</p>
            <div className="sms-list">
              {smsAlerts.length === 0 ? (
                <div className="sms-empty">No alerts generated for this incident</div>
              ) : (
                smsAlerts.map((alert, idx) => (
                  <div key={idx} className="sms-card">
                    <div className="sms-meta">
                      <span className="sms-tag">Template: {alert.template || 'alert'}</span>
                      <span className={`sms-chars ${alert.char_count > 140 ? 'overflow' : ''}`}>
                        {alert.char_count} / 140 chars {alert.truncated && '⚠️ Truncated'}
                      </span>
                    </div>
                    <pre className="sms-text">{alert.alert_text}</pre>
                    <button
                      className="copy-btn"
                      onClick={() => {
                        navigator.clipboard.writeText(alert.alert_text)
                        setCopiedIdx(idx)
                        setTimeout(() => setCopiedIdx(null), 2000)
                      }}
                    >
                      {copiedIdx === idx ? '✅ Copied!' : '📋 Copy to Clipboard'}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
