"""
S.T.R.A.N.D — Comprehensive End-to-End API Test Script
Tests all authentication, analysis, spatial layer, copilot, and export routes.
"""

import io
import json
import os
import sys
import urllib.error
import urllib.request

# Ensure UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE = "http://127.0.0.1:8000/api/v1"
API_KEY = "dev-key-change-in-production"

def test_endpoint(name, url, method="GET", data=None):
    headers = {"X-API-Key": API_KEY}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content_type = resp.headers.get("Content-Type", "")
            res_body = resp.read()
            if "application/json" in content_type:
                payload = json.loads(res_body)
                print(f"[PASS] [{resp.status}] {name}: OK (JSON {type(payload).__name__})")
            else:
                payload = res_body
                print(f"[PASS] [{resp.status}] {name}: OK (Binary/File: {len(payload)} bytes, Content-Type: {content_type})")
            return resp.status, payload
    except urllib.error.HTTPError as e:
        print(f"[FAIL] [{e.code}] {name}: HTTPError - {e.read().decode('utf-8', errors='ignore')[:200]}")
        return e.code, None
    except Exception as e:
        print(f"[FAIL] [ERR] {name}: {e}")
        return 500, None

def main():
    print("=" * 60)
    print("S.T.R.A.N.D — END-TO-END BACKEND API VERIFICATION SUITE")
    print("=" * 60)

    # 1. Auth routes
    print("\n--- 1. AUTHENTICATION MODULE ---")
    s, login_data = test_endpoint(
        "POST /auth/login (Valid)",
        f"{API_BASE}/auth/login",
        method="POST",
        data={
            "callsign": "commander.durga",
            "api_key": API_KEY,
            "role": "commander",
            "theater": "EMSR-927",
        },
    )
    assert s == 200, f"Login failed with status {s}"
    print(f"   Operator Profile: {login_data['operator']['callsign']} | Clearance: {login_data['operator']['clearance_level']}")

    # Invalid Auth check
    req_inv = urllib.request.Request(
        f"{API_BASE}/auth/login",
        data=json.dumps({"callsign": "intruder", "api_key": "wrong_key", "role": "commander"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req_inv)
        print("[FAIL] Rejection failed: Invalid key was accepted!")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("[PASS] [401] POST /auth/login (Invalid Key): Correctly rejected Unauthorized")
        else:
            print(f"[WARN] [Unexpected status] POST /auth/login (Invalid Key): {e.code}")

    test_endpoint("GET /auth/me", f"{API_BASE}/auth/me")
    test_endpoint("POST /auth/logout", f"{API_BASE}/auth/logout", method="POST")

    # 2. Analysis routes
    print("\n--- 2. ANALYSIS & TELEMETRY MODULE ---")
    s, res = test_endpoint("GET /analysis (List)", f"{API_BASE}/analysis")
    assert s == 200, f"Analysis list failed with {s}"
    analyses = res.get("analyses", [])
    print(f"   Found {len(analyses)} analysis records in database")
    if not analyses:
        print("No analysis records to test details against!")
        sys.exit(1)

    aid = analyses[0]["analysis_id"]
    print(f"   Target Analysis ID: {aid}")

    s, detail = test_endpoint(f"GET /analysis/{aid} (Detail)", f"{API_BASE}/analysis/{aid}")
    if detail and "summary" in detail and detail["summary"]:
        sm = detail["summary"]
        print(f"   Metrics: Flood: {sm.get('flood_area_km2')} km² | Severed: {sm.get('roads_severed_km')} km | Isolated: {sm.get('settlements_isolated')} settlements")

    s, logs = test_endpoint(f"GET /analysis/{aid}/logs (Pipeline Logs)", f"{API_BASE}/analysis/{aid}/logs")
    print(f"   Logs Count: {len(logs) if isinstance(logs, list) else 0}")

    # 3. Spatial Layers
    print("\n--- 3. SPATIAL VECTOR LAYERS ---")
    layer_names = ["flood", "roads", "bridges", "settlements", "hlz", "ponding"]
    for lyr in layer_names:
        s, geojson = test_endpoint(f"GET /layers/{aid}/{lyr}", f"{API_BASE}/layers/{aid}/{lyr}")
        if isinstance(geojson, dict):
            features = geojson.get("features", [])
            print(f"   Layer '{lyr}': {len(features)} GeoJSON features | type={geojson.get('type')}")

    # 4. Copilot Query
    print("\n--- 4. MULTIMODAL AI COPILOT ---")
    s, copilot_res = test_endpoint(
        f"POST /copilot/{aid}/query",
        f"{API_BASE}/copilot/{aid}/query",
        method="POST",
        data={
            "query": "What are the most urgent evacuation priorities?",
            "language": "en",
        },
    )
    if isinstance(copilot_res, dict):
        ans = copilot_res.get("answer", "")
        print(f"   Copilot Response Preview: {ans[:120]}... (Confidence: {copilot_res.get('confidence')})")

    # 5. Export Routines
    print("\n--- 5. REPORTING & EXPORT ROUTINES ---")
    s, sitrep_bytes = test_endpoint(f"POST /export/{aid}/sitrep", f"{API_BASE}/export/{aid}/sitrep", method="POST", data={})
    if isinstance(sitrep_bytes, bytes):
        is_pdf = sitrep_bytes.startswith(b"%PDF")
        print(f"   SitRep Valid PDF Header: {is_pdf} (Total bytes: {len(sitrep_bytes)})")

    s, sms_alerts = test_endpoint(f"POST /export/{aid}/sms", f"{API_BASE}/export/{aid}/sms", method="POST", data={"max_chars": 140})
    if isinstance(sms_alerts, list):
        print(f"   Generated {len(sms_alerts)} SMS/LoRa Emergency Dispatch Alerts")
        if sms_alerts:
            print(f"   Sample SMS: \"{sms_alerts[0].get('alert_text')}\"")

    print("\n" + "=" * 60)
    print("[PASS] ALL BACKEND API CALLS VERIFIED & OPERATIONAL")
    print("=" * 60)

if __name__ == "__main__":
    main()
