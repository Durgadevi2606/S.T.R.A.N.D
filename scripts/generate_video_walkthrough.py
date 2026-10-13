import os
import sys
import wave
import time
import shutil
import pathlib
import subprocess
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

BASE_URL = "http://127.0.0.1:5173"
WORKDIR = pathlib.Path("data/video_walkthrough")
DOWNLOADS_DIR = pathlib.Path(r"C:\Users\Durga\Downloads")
PUBLIC_DEMO_DIR = pathlib.Path("dashboard/public/demo")

SCENES = [
    {
        "id": "01_login_clearance",
        "title": "MISSION CONTROL CLEARANCE & OPERATOR ACCESS",
        "subtitle": "Role-Based Tactical Authentication • AES-256 Command Gateway",
        "url": f"{BASE_URL}/?login=true",
        "narration": "Welcome to S T R A N D, the Satellite Tactical Reconnaissance and Autonomous Navigation in Disaster system. Mission control begins at the clearance authentication portal. Incident commanders, radar analysts, and logistics coordinators authenticate with role-based cryptographic credentials to unlock command theater operations."
    },
    {
        "id": "02_tactical_layers",
        "title": "TACTICAL OVERVIEW • LIVE SAR GIS SATELLITE THEATER",
        "subtitle": "Sentinel-1 SAR Inundation • Damaged Crossings • Severed Highway Corridors",
        "url": f"{BASE_URL}/?module=tactical&tab=layers",
        "narration": "Entering the Tactical Overview. S T R A N D renders a high-definition GIS operational theater over the Bhote Koshi corridor in Nepal. Top impact metrics immediately display 178 square kilometers of SAR flood inundation extent, 26 kilometers of severed roads, damaged bridge crossings, and isolated villages. On the map, synthetic aperture radar flood polygons are rendered alongside cut-off road networks, damaged bridges, and verified landing zones."
    },
    {
        "id": "03_tactical_triage",
        "title": "TACTICAL VILLAGE TRIAGE & COMPOSITE URGENCY RANKING",
        "subtitle": "Multi-Factor Isolation Index • Clinic Availability • Ground Access Severance",
        "url": f"{BASE_URL}/?module=tactical&tab=triage",
        "narration": "Switching to the Triage inspector. S T R A N D runs a composite multi-factor urgency algorithm. Isolated settlements are ranked by population density, absence of medical clinics, and road network severance. Barahkshetra Village leads the priority queue with an urgency score of 0.94 and 2,140 residents cut off without medical care, allowing rescue coordinators to instantly dispatch priority relief."
    },
    {
        "id": "04_tactical_hlz",
        "title": "HELICOPTER LANDING ZONES (HLZ) EVACUATION PLANNER",
        "subtitle": "Autonomous Terrain Slope Filtering (< 5°) • Rotor Clearance (≥ 25m) • Elevation ASL",
        "url": f"{BASE_URL}/?module=tactical&tab=hlz",
        "narration": "Reviewing Helicopter Landing Zones. Using digital elevation models, S T R A N D autonomously locates flat, dry terrain outside the flood extent with ground slope under 5 degrees and rotor clearance exceeding 25 meters. Each site details elevation above sea level and obstacle clearance, enabling tactical pilots to conduct zero-risk air evacuation missions."
    },
    {
        "id": "05_tactical_copilot",
        "title": "TACTICAL COPILOT MULTIMODAL AI AGENT",
        "subtitle": "Grounded Gemini AI & Offline Spatial SQL Engine • Bilingual English & Nepali",
        "url": f"{BASE_URL}/?module=tactical&tab=copilot",
        "narration": "The Tactical Copilot provides grounded conversational intelligence powered by Google Gemini and a local offline spatial SQL engine. Commanders can query bridge integrity, road cut-offs, or village triage in both English and Nepali. Natural language questions receive precise, deterministic answers backed by executed database queries."
    },
    {
        "id": "06_sar_analytics",
        "title": "SAR FLOOD ANALYTICS • RADAR SCIENCE & SENSING ENGINE",
        "subtitle": "Sentinel-1 IW Mode C-Band SAR • Backscatter dB Distribution • Otsu Thresholding",
        "url": f"{BASE_URL}/?module=sar-analytics",
        "narration": "In the SAR Flood Analytics module, operators inspect the radar science pipeline. Using Sentinel-1 C-band Synthetic Aperture Radar in Interferometric Wide mode, the engine performs radiometric calibration, Lee speckle filtering, and dual-threshold Otsu segmentation on backscatter histograms to isolate water pixels through heavy cloud cover and torrential rain."
    },
    {
        "id": "07_infrastructure_grid",
        "title": "CRITICAL INFRASTRUCTURE GRID & SEVERED CORRIDORS",
        "subtitle": "OSM Highway Network Breakdown • Submerged Spans • Structural Transit Penalties",
        "url": f"{BASE_URL}/?module=infrastructure",
        "narration": "The Infrastructure Grid provides a detailed structural assessment of transportation arteries. Severed highway segments along the Araniko corridor are cataloged with distance penalties, while damaged and submerged bridge crossings are flagged with structural failure ratings, helping logistics commanders establish safe supply convoys."
    },
    {
        "id": "08_extraction_hlz",
        "title": "AIR EXTRACTION COMMAND & EVACUATION OPERATIONS",
        "subtitle": "Landing Zone Clearance Radii • Relief Distribution Corridors • Critical Triage",
        "url": f"{BASE_URL}/?module=mesh-hlz",
        "narration": "The Air Extraction Command module details flight ingress corridors and surface composition estimates for all helicopter landing sites. Evacuation flight paths are computed avoiding mountain ridges and flood zones, connecting high-priority isolated communities to regional trauma hospitals."
    },
    {
        "id": "09_telemetry_logs",
        "title": "SYSTEM TELEMETRY & POSTGIS AUDIT LOGS",
        "subtitle": "Neon PostGIS 24ms Real-Time Latency • Pipeline Step Latencies • NORAD Satellite Sync",
        "url": f"{BASE_URL}/?module=telemetry-logs",
        "narration": "Under Telemetry and Logs, system operators monitor infrastructure health. Active PostGIS and Neon database connections maintain a 24 millisecond query response latency. Detailed pipeline logs track the exact execution duration of SAR ingestion, ensemble segmentation, digital elevation filtering, and network reachability algorithms."
    },
    {
        "id": "10_modal_sar_upload",
        "title": "RAW SAR RADAR INGESTION PIPELINE MODAL",
        "subtitle": "Drag & Drop Sentinel-1 GeoTIFF / PNG / JPEG • Autonomous Flood Extent Pipeline",
        "url": f"{BASE_URL}/?modal=upload",
        "narration": "The Radar Scene Upload modal enables operators to ingest fresh satellite imagery on demand. Incident teams can drag and drop Sentinel-1 GRDH GeoTIFF, PNG, or JPEG scenes, or download the pre-packaged sample dataset to trigger end-to-end automated disaster intelligence extraction."
    },
    {
        "id": "11_modal_lora_sms",
        "title": "SMS & LORA SATELLITE MESH FIELD BROADCAST",
        "subtitle": "Ultra-Low-Bandwidth Dispatch (≤ 140 Chars) • Satellite Relay & Field Transceiver Link",
        "url": f"{BASE_URL}/?modal=sms",
        "narration": "Finally, the SMS and LoRa Field Broadcast modal formats mission-critical alerts into ultra-compact, 140-character tactical dispatches. These messages are broadcast across satellite links, handheld transceivers, and emergency LoRa mesh radios to guide ground survivors directly to designated helicopter extraction zones."
    }
]

def synthesize_voice(text, wav_output_path):
    vbs_path = wav_output_path.with_suffix(".vbs")
    # Clean text for VBScript
    clean_text = text.replace('"', '""').replace("'", " ")
    vbs_code = f'''Set voice = CreateObject("SAPI.SpVoice")
Set stream = CreateObject("SAPI.SpFileStream")
stream.Open "{wav_output_path.resolve()}", 3
Set voice.AudioOutputStream = stream
voice.Speak "{clean_text}"
stream.Close
'''
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs_code)
    
    subprocess.run(["cscript", "//nologo", str(vbs_path)], check=True)
    if vbs_path.exists():
        vbs_path.unlink()

def capture_screenshot(url, png_output_path):
    cmd = [
        CHROME_BIN,
        "--headless=new",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--hide-scrollbars",
        "--virtual-time-budget=4000",
        f"--screenshot={png_output_path.resolve()}",
        url
    ]
    subprocess.run(cmd, check=True)

def add_title_overlay(img_path, scene_idx, title, subtitle):
    im = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    
    # Dimensions
    w, h = im.size
    banner_h = 70
    
    # Draw frosted dark banner at bottom
    # semi-transparent overlay
    overlay = Image.new("RGBA", (w, banner_h), (14, 14, 16, 235))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # Pulse status dot
    overlay_draw.ellipse([25, 26, 37, 38], fill=(251, 113, 133)) # rose dot
    
    # Scene indicator
    badge_text = f"SCENE {scene_idx+1}/11"
    overlay_draw.text((48, 14), badge_text, fill=(251, 113, 133))
    
    # Title
    overlay_draw.text((160, 14), title, fill=(245, 245, 247))
    # Subtitle
    overlay_draw.text((160, 38), subtitle, fill=(180, 175, 185))
    
    # Paste overlay onto bottom of image
    im.paste(overlay.convert("RGB"), (0, h - banner_h))
    
    # Top progress bar
    progress_w = int((w * (scene_idx + 1)) / len(SCENES))
    draw.rectangle([0, 0, progress_w, 4], fill=(251, 113, 133))
    
    im.save(img_path)

def get_wav_duration(wav_path):
    with wave.open(str(wav_path), "r") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)

def main():
    WORKDIR.mkdir(parents=True, exist_ok=True)
    print("=== S.T.R.A.N.D. Video Walkthrough & AI Voiceover Generator ===")
    print(f"Total scenes to capture and narrate: {len(SCENES)}")
    
    segment_files = []
    
    for idx, scene in enumerate(SCENES):
        print(f"\n[{idx+1}/{len(SCENES)}] Processing: {scene['title']}")
        
        png_path = WORKDIR / f"{scene['id']}.png"
        wav_path = WORKDIR / f"{scene['id']}.wav"
        mp4_path = WORKDIR / f"{scene['id']}.mp4"
        
        # 1. Capture Screenshot
        print("  - Capturing 1920x1080 screenshot via headless Chrome...")
        capture_screenshot(scene["url"], png_path)
        
        # 2. Add Title Overlay
        print("  - Applying tactical title overlay and scene banner...")
        add_title_overlay(png_path, idx, scene["title"], scene["subtitle"])
        
        # 3. Synthesize AI Voiceover
        print("  - Synthesizing AI voice-over narration track...")
        synthesize_voice(scene["narration"], wav_path)
        
        duration = get_wav_duration(wav_path)
        # Add 0.8s padding for natural breathing pause between scenes
        padded_duration = duration + 0.8
        print(f"  - Narration duration: {duration:.2f}s (Segment total: {padded_duration:.2f}s)")
        
        # 4. Render Video Segment
        print("  - Encoding segment video with synced audio track...")
        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1",
            "-framerate", "25",
            "-i", str(png_path.resolve()),
            "-i", str(wav_path.resolve()),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", f"{padded_duration:.2f}",
            str(mp4_path.resolve())
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        segment_files.append(mp4_path)
        print(f"  - Completed segment {mp4_path.name} ({mp4_path.stat().st_size / 1024:.1f} KB)")
    
    # 5. Concatenate all segments into Master Walkthrough Video
    print("\n=== Concatenating all scenes into Master Walkthrough Video ===")
    concat_list_path = WORKDIR / "concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for seg in segment_files:
            # Format: file 'path' with escaped backslashes for FFmpeg
            f.write(f"file '{seg.resolve().as_posix()}'\n")
            
    final_output_name = "STRAND_Complete_System_Walkthrough_AI_Voiceover.mp4"
    master_video_path = WORKDIR / final_output_name
    downloads_video_path = DOWNLOADS_DIR / final_output_name
    public_video_path = PUBLIC_DEMO_DIR / final_output_name
    
    cmd_concat = [
        FFMPEG_BIN, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path.resolve()),
        "-c", "copy",
        str(master_video_path.resolve())
    ]
    subprocess.run(cmd_concat, check=True, capture_output=True)
    
    master_size_mb = master_video_path.stat().st_size / (1024 * 1024)
    print(f"Master Video Generated Successfully! Size: {master_size_mb:.2f} MB")
    
    # Copy to user's Windows Downloads directory
    shutil.copy(master_video_path, downloads_video_path)
    print(f"Saved to User's Downloads Folder: {downloads_video_path}")
    
    # Copy to dashboard public demo directory for in-app video playback
    PUBLIC_DEMO_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(master_video_path, public_video_path)
    print(f"Saved to Web Dashboard Demo Folder: {public_video_path}")

if __name__ == "__main__":
    main()
