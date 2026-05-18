# DeleteBackground

Batch background removal for images — local, free, and fast.

Point the app at an input folder, choose an output folder, click **Start
batch**, and every supported image gets a transparent PNG counterpart in the
destination folder. Uses [rembg](https://github.com/danielgatis/rembg) +
ONNX Runtime under the hood, so it runs entirely on your machine with no API
keys, no uploads, and no usage limits.

---

## Highlights

- **Free & offline** — no external services. Models are downloaded once on
  first use and stay cached locally.
- **Fast** — ONNX-accelerated inference, single warmed-up rembg session,
  throttled WebSocket progress events.
- **Choice of models** — BiRefNet (state of the art), ISNet, U²-Net variants,
  Silueta, and a portrait-specialised model. Picker is grouped by quality
  tier.
- **Configurable** — input/output folders, sub-folder scanning, model,
  Quality preset, worker threads, alpha matting (with foreground / background
  / erode tuning), optional solid-colour background, and PNG compression
  level. Server-side preferences are persisted to `settings.json`.
- **Safe by default** — atomic writes, idempotent re-runs that skip already
  processed files, single failure isolation, cancellable jobs.
- **Polished UI** — dark themed sidebar with Batches / Live processing /
  Output / Settings / Logs screens, native folder picker dialog, real-time
  progress with ETA and throughput, before/after preview, output gallery
  with click-to-zoom lightbox, and a filterable activity log.

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

# Install dependencies
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip.exe

# Start the server
.venv/bin/python -m uvicorn app.main:app --port 8765   # Windows: .venv\Scripts\python.exe
```

Then open <http://127.0.0.1:8765>.

## Using the app

The sidebar exposes five screens:

| Screen      | What it's for                                                                  |
| ----------- | ------------------------------------------------------------------------------ |
| Batches     | Pick folders, choose a model, configure the run, and start a batch.            |
| Live        | Watch progress, ETA, throughput, and recent results while a batch is running.  |
| Output      | Browse the produced PNGs as a grid; click a thumbnail to open the lightbox.    |
| Settings    | Tune alpha matting, PNG compression, and the solid-colour background.          |
| Logs        | Filterable activity log (Info / OK / Warn / Errors) with a Copy button.        |

### Running a batch

1. **Folders** — type the absolute paths, or click the folder icon next to
   each field to open the OS-native picker. The check icon validates the
   path and reports how many supported images were found (recursive or not).
2. **Model** — choose from the dropdown. Entries are grouped by quality
   tier (Premium / High / Balanced / Fast). The **Quality preset** chips
   (Fast / Balanced / Quality) jump the selector to a sensible model in
   that tier. **ISNet General** is the default; **BiRefNet General** is the
   highest-quality option; **U²-Net Lite** is the fastest.
3. **Run** — adjust **Worker threads** if needed, tick **Scan sub-folders**
   to recurse, then click **Start batch**. Progress, ETA, throughput, and
   per-image errors stream live over WebSocket. The job can be **Cancelled**
   at any time; already-processed files are skipped on subsequent runs
   unless **Force re-process** is enabled.

### Tips

- Models are downloaded on first use only — a loading overlay shows while
  the ONNX session warms up.
- Toggle **Scan sub-folders** to mirror the input layout under the output
  folder.
- Enable **Alpha matting** in *Settings* for cleaner hair / fur edges. It is
  slower; foreground / background thresholds and erode size are tunable.
- Set a **Solid background colour** (in *Settings*) to flatten the cutouts
  onto an RGB background instead of producing transparent PNGs. Accepts
  `#RRGGBB` or `#RRGGBBAA`; leave empty to keep transparency.
- Lower **PNG compression** (default 1) gives faster writes; raise it for
  smaller files.

## Configuration

Environment variables (all optional, prefix `DBG_`):

| Variable          | Default       | Purpose                                       |
| ----------------- | ------------- | --------------------------------------------- |
| `DBG_HOST`        | `127.0.0.1`   | Bind address. Use `0.0.0.0` to expose on LAN. |
| `DBG_PORT`        | `8765`        | HTTP port.                                    |
| `DBG_LOG_LEVEL`   | `INFO`        | Python logging level.                         |
| `DBG_MAX_WORKERS` | `min(CPU, 4)` | Hard cap on concurrent inference threads.     |

User preferences (folders, model, alpha matting, PNG compression, background
colour, recursion, skip-existing) are persisted in `settings.json` next to
the app and survive restarts.

## Supported input formats

`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`, `.tiff`

Output is always PNG with an alpha channel, unless a solid background colour
is configured.

## Project layout

```
app/
  main.py                 FastAPI app + lifespan
  config.py               Env settings & persisted preferences
  api/
    routes.py             REST endpoints (incl. native folder picker)
    websocket.py          Live progress channel
  core/
    background_remover.py rembg session wrapper
    batch_processor.py    Job orchestration
    file_manager.py       Filesystem helpers
    exceptions.py         Domain exceptions
  models/
    schemas.py            Pydantic request/response models + model catalog
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
