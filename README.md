# DeleteBackground

Batch background removal for images — local, free, and fast.

Point the app at an input folder, choose an output folder, click **Start**, and
every supported image gets a transparent PNG counterpart in the destination
folder. Uses [rembg](https://github.com/danielgatis/rembg) + ONNX Runtime
under the hood, so it runs entirely on your machine with no API keys, no
uploads, and no usage limits.

![architecture](static/img/favicon.svg)

---

## Highlights

- **Free & offline** — no external services. Models download once and stay
  cached locally.
- **Fast** — ONNX-accelerated inference, parallel worker pool, model warm-up,
  throttled progress events.
- **High quality** — choose between BiRefNet (state of the art), ISNet, U²-Net
  variants, and a portrait-specialised model.
- **Configurable** — input/output folders, recursion, model, alpha matting,
  optional solid-color background, PNG compression level — all persisted
  between sessions.
- **Safe by default** — atomic writes, idempotent re-runs, skip-if-newer, single
  failure isolation, cancellable jobs.
- **Polished UI** — real-time WebSocket progress, ETA, dark theme, fully
  keyboard-accessible.

## Requirements

- Python 3.10 or newer
- ~1 GB of free disk for the first model download (varies by model)
- Windows, macOS, or Linux

## Quick start

### Windows

Double-click `run.bat`, or from a terminal:

```bat
run.bat
```

### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

The launcher creates a virtual environment in `.venv`, installs dependencies,
starts the server on <http://127.0.0.1:8765>, and opens your default browser.

### Manual setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/python -m uvicorn app.main:app --port 8765
```

## Using the app

1. **Folders**: paste the absolute path to the folder containing your images,
   and the destination folder for the cutouts. Click **Check** to validate
   each path and see how many supported images were found.
2. **Model**: pick a tile. `BiRefNet General` is the highest quality; `U²-Net
   Lite` is the fastest. Models are downloaded the first time they're used.
3. **Run**: click **Start**. Progress, ETA, and per-image errors stream live.
   The job can be **Cancelled** at any time and resumed later — already
   processed files are skipped on subsequent runs.

### Tips

- Toggle **Scan subdirectories** to mirror the input layout under the output
  folder.
- Enable **Alpha matting** under *Advanced* for cleaner hair / fur edges (it is
  slower).
- Set a **Solid background color** to flatten the cutouts onto an RGB
  background instead of producing transparent PNGs.

## Configuration

Environment variables (all optional, prefix `DBG_`):

| Variable           | Default     | Purpose                                       |
| ------------------ | ----------- | --------------------------------------------- |
| `DBG_HOST`         | `127.0.0.1` | Bind address. Use `0.0.0.0` to expose on LAN. |
| `DBG_PORT`         | `8765`      | HTTP port.                                    |
| `DBG_LOG_LEVEL`    | `INFO`      | Python logging level.                         |
| `DBG_MAX_WORKERS`  | `min(CPU, 4)` | Concurrent inference workers.               |

User preferences (folders, model, options) are persisted in `settings.json`
next to the app and survive restarts.

## Supported input formats

`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`, `.tiff`

Output is always PNG with an alpha channel (unless a solid background color is
configured).

## Project layout

```
app/
  main.py                 FastAPI app + lifespan
  config.py               Env settings & persisted preferences
  api/
    routes.py             REST endpoints
    websocket.py          Live progress channel
  core/
    background_remover.py rembg session wrapper
    batch_processor.py    Job orchestration
    file_manager.py       Filesystem helpers
    exceptions.py         Domain exceptions
  models/
    schemas.py            Pydantic request/response models
  utils/
    logger.py             Logging setup
static/                   CSS, JS, icons
templates/                Single Jinja2 template
CLAUDE.md                 Engineering rules for contributors
requirements.txt
run.bat / run.sh          Convenience launchers
```

## License

MIT. rembg and the segmentation model weights are distributed under their own
licenses; please review them if you intend to redistribute.
