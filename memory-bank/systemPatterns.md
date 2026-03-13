# System Patterns — switch-translator

## Architecture Overview

```
pipeline.py  (orchestrator)
│
├── src/extractor.py    Phase 1+2  — File detection & RomFS extraction
├── src/scanner.py      Phase 3+4  — Text discovery & JSON manifest export
├── src/translator.py   Phase 5    — Ollama translation with cache
├── src/rebuilder.py    Phase 6    — MSBT/SARC reconstruction
├── src/patcher.py      Phase 7    — LayeredFS patch assembly
├── src/msbt.py                    — MSBT binary read/write
└── src/utils.py                   — Shared helpers (config, logging, hashing)
```

## Pipeline Phases

| Phase | Module | Description |
|-------|--------|-------------|
| 1 | extractor | Detect `.nsp`/`.xci` in `input/` |
| 2 | extractor | hactool: extract NCAs → identify Program NCA → extract RomFS |
| 3 | scanner | Recurse RomFS: extract SARC/Yaz0 archives inline |
| 4 | scanner | Parse MSBT/JSON/CSV/XML/TXT/YAML/binary → JSON manifests in `text/` |
| 5 | translator | Translate each manifest entry via Ollama; cache in SQLite |
| 6 | rebuilder | Re-encode translated text back into MSBT/SARC |
| 7 | patcher | Copy rebuilt files into `build/.../atmosphere/contents/<TitleID>/romfs/` |

## Key Design Patterns

### Placeholder Preservation
Before sending text to Ollama, all game-specific tokens are replaced with `@@PHn@@` markers:
- `{variable}` / `{0}` format strings
- `%s`, `%02d` printf specifiers
- `<color=red>` XML-like tags
- `\n`, `\t` escape sequences
- `[[code]]` double-bracket codes
- `^A` control characters
- `~N` Nintendo line-break codes

After translation the markers are restored to their originals.

### SQLite Translation Cache
Path: `translated/.cache.db`  
Table: `cache(id, source_hash, source, translation, created_at)`  
Hash: SHA-256 of (source_text + language + model).  
This makes re-runs instant for already-translated strings.

### JSON Manifest Format (text/ directory)
```json
{
  "source_file": "romfs/UI/menu.msbt",
  "file_format": "msbt",
  "entries": [
    {"index": 0, "label": "btn_ok", "text": "OK"}
  ]
}
```

### Directory Layout
```
input/          ← place .nsp/.xci here
work/           ← extracted NCA/RomFS (intermediate)
text/           ← JSON manifests (source text)
translated/     ← JSON manifests (translated text) + .cache.db
build/          ← final Atmosphere patch
logs/           ← pipeline_<timestamp>.log files
tools/          ← hactool, msbt_tool, sarc_tool binaries
config/         ← config.json
```

### External Tool Invocation Pattern
All external binaries (hactool, sarc_tool, msbt_tool) are called through `src/utils.run_tool()`, which:
- Checks the binary is executable (`ensure_executable`)
- Captures stdout/stderr
- Returns `(returncode, stdout, stderr)`

## Component Relationships
- `pipeline.py` is the sole orchestrator; modules are stateless functions
- Config dict is loaded once and passed down to every module
- All I/O paths derived from `ROOT_DIR` (project root) — no hardcoded absolute paths
- `monitor.py` and `_check.py` are read-only diagnostic scripts; they never modify state
