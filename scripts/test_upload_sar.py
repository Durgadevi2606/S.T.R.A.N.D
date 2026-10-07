import io
import json
import urllib.request
import numpy as np
from PIL import Image

# Create synthetic SAR radar image with dark river channel
arr = (np.random.normal(120, 25, (256, 256))).clip(0, 255).astype(np.uint8)
for x in range(256):
    center_y = int(128 + 40 * np.sin(x / 30.0))
    arr[max(0, center_y-15) : min(256, center_y+15), x] = np.random.normal(25, 10, (min(256, center_y+15) - max(0, center_y-15))).clip(5, 50).astype(np.uint8)

buf = io.BytesIO()
Image.fromarray(arr).save(buf, format="PNG")
img_bytes = buf.getvalue()

boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
parts = []
parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"radar_test.png\"\r\nContent-Type: image/png\r\n\r\n".encode("utf-8"))
parts.append(img_bytes)
parts.append(f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"aoi_name\"\r\n\r\nKoshi Sector Radar\r\n--{boundary}--\r\n".encode("utf-8"))

body = b"".join(parts)

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/analysis/upload-sar",
    data=body,
    headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-API-Key": "dev-key-change-in-production"
    }
)

with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    print("HTTP Status:", resp.status)
    print("Result:", json.dumps(data, indent=2))
