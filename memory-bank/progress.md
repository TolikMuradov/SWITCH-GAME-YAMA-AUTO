# Progress — switch-translator

## What Works (Implemented)
- **Full pipeline orchestration** — `pipeline.py` with argparse CLI (`--input`, `--config`, `--language`, `--skip-extract`, `--skip-translate`, `--zip`)
- **Phase 1+2 — Extraction** (`src/extractor.py`)
  - Auto-detects `.nsp`/`.xci` in `input/`
  - Calls hactool to extract NCAs, identifies Program NCA, extracts RomFS
- **Phase 3+4 — Scanning** (`src/scanner.py`)
  - Recursive RomFS walk
  - Yaz0 decompression (`.szs`)
  - SARC archive extraction
  - Parsers for MSBT, JSON, CSV, XML, TXT, YAML, binary strings
  - Exports to JSON manifests in `text/`
- **Phase 5 — Translation** (`src/translator.py`)
  - Ollama HTTP API integration
  - Placeholder preservation & restoration
  - SQLite cache (`translated/.cache.db`)
  - Retry with configurable back-off
  - Text chunking for large files
- **Phase 6 — Rebuilding** (`src/rebuilder.py`)
  - Reconstructs MSBT and SARC files with translated text
- **Phase 7 — Patching** (`src/patcher.py`)
  - Assembles Atmosphere LayeredFS patch in `build/`
- **MSBT codec** (`src/msbt.py`) — binary read/write
- **Utility layer** (`src/utils.py`) — config loading, logging, SHA hashing, subprocess wrapper
- **Diagnostic tools** — `_check.py` (status report), `monitor.py` (live progress), `_reset.py` (clean slate)

## What's Left / Potential Improvements
- [ ] Python venv not yet created on current machine — needs initial setup
- [ ] Ollama server connectivity not verified
- [ ] Nintendo Switch keys not confirmed at configured path
- [ ] `--zip` output packaging not tested end-to-end
- [ ] Multi-threading support exists in config (`threads`) but translator uses single thread
- [ ] No automated tests (unit or integration)
- [ ] Windows path handling in shell scripts (`scripts/setup.sh` is bash-only)

## Current Status
**Code complete.** Pipeline is fully written. Pending: environment setup and first successful end-to-end run.

## Known Issues
- README documents macOS setup; Windows users must adapt (`venv\Scripts\activate` instead of `source venv/bin/activate`)
- `scripts/setup.sh` is a bash script — not directly usable on Windows without WSL or Git Bash
- hactool must be the correct platform build (Linux/macOS binary won't work on bare Windows)

## Evolution of Key Decisions
| Decision | Reason |
|----------|--------|
| Ollama (local LLM) instead of cloud API | Privacy, no cost per token, works offline |
| SQLite cache | Survives process crashes; makes reruns cheap |
| Placeholder tokenisation | Game variables must survive LLM translation intact |
| Single-threaded translation | Prevents overwhelming a single remote GPU |
| JSON manifest intermediary format | Decouples extraction from translation; human-readable |
