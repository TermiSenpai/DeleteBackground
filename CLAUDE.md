# CLAUDE.md — DeleteBackground

All code,comments, identifiers, log messages, and user-facing strings MUST be written
in English.

## 1. Project overview

DeleteBackground is a local web application that performs batch background
removal on images. The user points the app at an input folder, the app
processes every supported image with an ONNX-accelerated segmentation model
(via [rembg](https://github.com/danielgatis/rembg)), and writes the
transparent results to a configurable output folder.

Goals, in priority order:

1. **Free** — no paid APIs, no subscription, no telemetry.
2. **Fast** — ONNX Runtime, parallel workers, model warm-up, optional GPU.
3. **High quality** — BiRefNet / ISNet models for best edge quality.
4. **Professional UX** — drag-and-drop, live progress over WebSocket,
   before/after preview, persisted settings.
5. **Robust** — never lose work; skip already-processed files by default;
   never crash on a single bad image.

## 2. Tech stack

- **Backend**: Python 3.10+, FastAPI, Uvicorn, Pydantic v2.
- **ML**: `rembg` with ONNX Runtime (CPU by default, GPU if available).
- **Image I/O**: Pillow, NumPy.
- **Concurrency**: `asyncio` for I/O + `concurrent.futures.ThreadPoolExecutor`
  for CPU-bound model inference.
- **Frontend**: Vanilla HTML/CSS/JS — no build step, no framework lock-in.
- **Persistence**: Single JSON file for user settings.

## 3. Architecture

```
DeleteBackground/
├── app/
│   ├── main.py              # FastAPI entrypoint + lifespan
│   ├── config.py            # Settings (Pydantic Settings)
│   ├── api/
│   │   ├── routes.py        # REST endpoints
│   │   └── websocket.py     # Live progress channel
│   ├── core/
│   │   ├── background_remover.py  # rembg session wrapper
│   │   ├── batch_processor.py     # Job orchestration
│   │   └── file_manager.py        # Filesystem helpers
│   ├── models/
│   │   └── schemas.py       # Pydantic request/response models
│   └── utils/
│       └── logger.py        # Structured logging
├── static/                  # CSS, JS, icons
├── templates/               # Jinja2 templates (single page)
├── settings.json            # Persisted user preferences (gitignored)
├── requirements.txt
├── run.bat / run.sh         # Convenience launchers
└── README.md
```

Layering rule: `api` → `core` → `models`/`utils`. Lower layers must never
import from higher ones.

## 4. Coding standards

### Python

- **Style**: PEP 8, 100-column lines, double quotes, trailing commas where
  multi-line.
- **Types**: Every public function and method has full type hints. Run
  `mypy --strict` clean on `app/`.
- **Docstrings**: Google style. One-line summary, then blank line, then
  details. Document `Args`, `Returns`, `Raises` when non-trivial.
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes,
  `SCREAMING_SNAKE_CASE` for module-level constants.
- **Imports**: Standard library, third-party, local — separated by a blank
  line. Use absolute imports inside `app.*`.
- **Errors**: Define domain exceptions in `app/core/exceptions.py`. Never
  raise bare `Exception`. Never `except:` without a type. Never silently
  swallow errors — at minimum log them with context.
- **Async**: I/O paths are `async`. CPU-bound work (model inference, PNG
  encode) runs inside a thread pool via `asyncio.to_thread` or
  `loop.run_in_executor`.
- **Logging**: Use the module logger (`logger = logging.getLogger(__name__)`).
  Never `print` in production code paths.

### JavaScript / HTML / CSS

- **JS**: ES2020+, no transpilation. Strict mode. `const` by default, `let`
  only when reassignment is needed. Never `var`.
- **DOM**: Cache lookups; never query in a loop. Use event delegation.
- **CSS**: Mobile-first. Custom properties for theme tokens. BEM-ish naming
  (`block__element--modifier`). No `!important` unless overriding a third
  party.
- **A11y**: Semantic HTML. Every interactive element is keyboard-reachable
  and labelled. Color contrast ≥ WCAG AA.

### Comments

- Default to **no comment**. Names should carry the meaning.
- Add a comment only when _why_ is non-obvious (constraint, workaround,
  surprising invariant). Never restate _what_ the code does.
- All comments in English. No TODO without an owner and a date.

## 5. Behavioral rules

1. **Idempotent batches** — re-running on the same folder must be cheap.
   Already-processed images (output exists, newer mtime than input) are
   skipped unless `force=true`.
2. **Atomic writes** — write to `<name>.tmp.png`, then rename. No half-
   written PNGs on a crash.
3. **Bounded memory** — never load the whole folder in memory. Stream the
   file list and process in worker batches.
4. **Single failure isolation** — one bad image must not abort the job. Log
   the error, increment the failure counter, continue.
5. **Cancellable** — every long-running job must respect a cancel signal
   and stop at the next image boundary.
6. **Path safety** — resolve and validate input/output paths. Reject paths
   that escape user-configured roots. Never follow symlinks outside roots.

## 6. Performance guidance

- Create the `rembg` session **once** per process, reuse it. Sessions cache
  the ONNX model.
- Pick worker count = `min(os.cpu_count(), 4)` by default — the ONNX session
  is already multi-threaded internally, so more workers can hurt.
- Default model is `birefnet-general` for top quality. Offer `isnet-general-use`
  as a balanced default and `u2netp` as the fast path.
- Encode PNG with `optimize=False, compress_level=1` during batch — disk is
  cheap, latency is not. Offer `compress_level=6` as a "smaller files" option.
- Send WebSocket progress events at most every 100 ms or every 5 images,
  whichever comes first.

## 7. Testing

- `pytest` for unit tests. Tests live in `tests/`, mirroring `app/`.
- Mock the model session in unit tests; never download weights in CI.
- One integration test that runs end-to-end on three tiny fixture PNGs.
- Coverage target: 80% for `app/core/`.

## 8. Security & privacy

- The server binds to `127.0.0.1` by default. Exposing on `0.0.0.0` requires
  an explicit env var `DBG_HOST=0.0.0.0`.
- No outbound network calls except the first-run model download from the
  official `rembg` source.
- No analytics, no telemetry, no auto-update pings.
- User-provided paths are validated against a configurable root allow-list.

## 9. Definition of done

A change is done when:

- [ ] Code is typed and passes `mypy --strict`.
- [ ] `ruff check` is clean.
- [ ] Relevant tests are added/updated and pass.
- [ ] The dev server starts and the UI exercise (drop folder → run → open
      output) works end-to-end.
- [ ] No new TODOs without an owner+date.
- [ ] README updated if behavior or setup changed.
