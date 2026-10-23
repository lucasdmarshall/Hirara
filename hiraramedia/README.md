<div align="center">

# HiraraMedia

**Video, image and barcode tools for AI agents.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). FFmpeg, Pillow,
NumPy, zbar and segno; no ML models, no API keys.

</div>

---

## Tools

| Tool | What it gives an agent |
|---|---|
| **`video_profile`** | Duration, size, frame rate, codecs; scene cuts (shots); black and frozen stretches; a keyframe per scene on one labelled **contact sheet** (JPEG) a vision model can look at; the soundtrack's speech / music / silence timeline (with `hiraraaudio`) |
| **`image_compare`** | Pixel diff of two images: identical or not, changed share, each changed region as a box with a plain position ("top right"), PSNR, and an annotated PNG |
| **`barcode_read`** | QR codes and barcodes (EAN / UPC, Code 128 / 39, ITF, DataBar, ...) decoded exactly, with position; retries greyscale and upscaled |
| **`qr_generate`** | QR code to PNG or SVG, any error-correction level |

A model cannot play a video and misreads QR codes. `video_profile` gives it a
timeline plus one picture of every scene; `barcode_read` decodes the pattern
instead of guessing at it. `image_compare` is the way to check that a UI change
or a re-rendered chart changed what it should and nothing else.

---

## Quick start

```bash
apt-get install ffmpeg libzbar0
pip install -e ../hirara-core -e ../hiraraaudio -e ".[service,mcp,audio]"
uvicorn hiraramedia.service:app --host 127.0.0.1 --port 9500
```

```bash
curl -X POST localhost:9500/video_profile -H 'content-type: application/json' \
  -d '{"file_path":"/data/demo.mp4","max_keyframes":12}'

curl -X POST localhost:9500/image_compare -H 'content-type: application/json' \
  -d '{"a_path":"/data/before.png","b_path":"/data/after.png"}'

curl -X POST localhost:9500/qr_generate -H 'content-type: application/json' \
  -d '{"data":"https://example.com"}'
```

Uploads: `POST /video_profile/upload` and `POST /barcode_read/upload`.
MCP: `python -m hiraramedia.mcp_server`. Docker: `docker compose up -d --build`
(build context is the repo root).

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HM_ALLOW_LOCAL_PATH` | `true` | Read files by path. Set `false` on a network-exposed service |
| `HM_ALLOW_OUTPUT_PATH` | `true` | Write `output_path` / `output_dir`. Set `false` on a network-exposed service |
| `HM_ALLOW_URL_FETCH` | `false` | Allow `*_url` (through the SSRF guard) |
| `HM_MAX_BYTES` | `1073741824` | Largest input file |
| `HM_MAX_PIXELS` | `60000000` | Largest image (decompression-bomb guard) |
| `HM_MAX_KEYFRAMES` | `48` | Ceiling for `max_keyframes` |
| `HM_MAX_OUTPUT_BYTES` | `26214400` | Largest image returned inline |
| `HM_TIMEOUT` | `900` | Seconds per FFmpeg process |
| `HM_FFMPEG` / `HM_FFPROBE` | `ffmpeg` / `ffprobe` | Binaries |
| `HM_PORT` | `9500` | Compose host port |

Every FFmpeg input is limited to local protocols, so a crafted playlist cannot
make it fetch URLs.

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
