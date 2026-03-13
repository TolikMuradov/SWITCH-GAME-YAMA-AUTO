# Tech Context — switch-translator

## Language & Runtime
- Python 3.11+
- No framework — plain stdlib + `requests`

## Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| `requests` | ≥2.31.0 | Ollama HTTP API calls |

Install: `pip install -r requirements.txt`

## External Binaries (place in `tools/`)
| Binary | Purpose | Source |
|--------|---------|--------|
| `hactool` | NSP/XCI/NCA/RomFS extraction | [SciresM/hactool](https://github.com/SciresM/hactool/releases) |
| `msbt_tool` *(optional)* | MSBT export/import | various Switch tools |
| `sarc_tool` *(optional)* | SARC archive extract/repack | [aboood40091/SARC-Tool](https://github.com/aboood40091/SARC-Tool) |

**Windows note:** README says macOS but the project runs on Windows too. Make sure binaries are `.exe` or the correct platform build.

## Configuration (`config/config.json`)
```json
{
  "translation_language": "Turkish",
  "source_language": "en",
  "translation_endpoint": "http://192.168.1.115:11434/api/generate",
  "translation_model": "qwen2.5:14b",
  "max_chunk_size": 2000,
  "threads": 1,
  "log_level": "INFO",
  "retry_count": 3,
  "retry_delay": 5,
  "request_timeout": 120,
  "keys_file": "~/hactool/keys/prod.keys",
  "title_keys_file": "~/hactool/keys/title.keys",
  "tools": {
    "hactool": "~/hactool/hactool",
    "hactoolnet": "tools/hactoolnet",
    "msbt_tool": "tools/msbt_tool",
    "sarc_tool": "tools/sarc_tool"
  }
}
```

## Ollama Server
- Expected at `http://192.168.1.115:11434` (remote LAN PC)
- Model: `qwen2.5:14b` (must be pulled on the server)
- Endpoint: `/api/generate` (non-streaming POST)

## Nintendo Switch Keys
- `prod.keys` → decrypts NCA content
- `title.keys` → decrypts title-specific encryption
- Default path: `~/hactool/keys/` (configurable in `config.json`)
- Keys are NOT included in the repo (user must supply)

## Development Setup (Windows)
```powershell
cd switch-translator
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Diagnostic Scripts
| Script | Purpose |
|--------|---------|
| `_check.py` | Status report: cache %, log errors, file counts |
| `monitor.py` | Live monitoring of translation progress |
| `_reset.py` | Reset work/text/translated/build directories |

## Source Code Layout
```
src/
  __init__.py
  extractor.py    — Phase 1+2
  scanner.py      — Phase 3+4
  translator.py   — Phase 5
  rebuilder.py    — Phase 6
  patcher.py      — Phase 7
  msbt.py         — MSBT binary codec
  utils.py        — Config, logging, hashing, subprocess wrapper
```
