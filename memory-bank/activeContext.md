# Active Context — switch-translator

## Current Work Focus
Initial Memory Bank setup. Project source code is complete as written; no active feature development in progress.

## Recent Changes
- AGENTS.md populated with Cline Memory Bank framework (2026-03-13)
- `memory-bank/` directory created with all six core files

## Environment State (as of 2026-03-13)
- OS: Windows (user's machine)
- Python venv: **not yet created** — run setup commands below
- Ollama server: expected at `http://192.168.1.115:11434` (remote LAN PC)
- Nintendo Switch keys: expected at `~/hactool/keys/`
- hactool binary: expected at `~/hactool/hactool`

## Setup Commands (Windows)
```powershell
cd "c:\Users\User\Downloads\switch-translator"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Next Steps
1. Verify Python is installed (`python --version` — needs 3.11+)
2. Create and activate venv, install `requests`
3. Confirm hactool binary exists at configured path
4. Confirm Nintendo Switch keys are present
5. Confirm Ollama server is reachable at configured IP
6. Place a `.nsp` or `.xci` in `input/` and run `python pipeline.py`
7. Use `python _check.py` to monitor progress during translation

## Active Decisions & Considerations
- `threads` is set to `1` in config — translation is single-threaded to avoid hammering the remote Ollama server
- `max_chunk_size: 2000` chars — adjust down if Ollama times out frequently
- `request_timeout: 120` seconds — increase if the 14B model is slow on the remote machine
- The pipeline is idempotent: safe to re-run; cache prevents re-translation

## Known Patterns
- Always activate venv before running scripts
- Use `--skip-extract` to resume after a failed translation run without re-extracting
- Use `python _reset.py` to start completely fresh (clears work/, text/, translated/, build/)
