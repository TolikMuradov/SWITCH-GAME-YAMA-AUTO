# Product Context — switch-translator

## Why This Project Exists
Nintendo Switch games ship with text assets locked inside proprietary container formats (NSP/XCI → NCA → RomFS → SARC → MSBT). There are no official localisation tools. This project automates the entire pipeline so that Turkish-speaking (or other language) users can play games that were never officially translated.

## Problems It Solves
| Problem | Solution |
|---------|----------|
| Game text buried in binary NCA archives | hactool extracts NCAs and RomFS automatically |
| Multiple text formats (MSBT, JSON, CSV, XML, binary) | Scanner detects and normalises all formats into JSON manifests |
| Translation is slow and repetitive | SQLite cache avoids re-translating identical strings across multiple runs |
| AI models mangle game placeholders (`{player}`, `%s`, `\n`) | Placeholder preservation: tokens replaced before translation, restored after |
| Patching requires exact binary rebuild | Rebuilder reconstructs MSBT/SARC bit-for-bit compatible with the Switch runtime |

## How It Should Work
1. User places a `.nsp` or `.xci` file in `input/`
2. Runs `python pipeline.py`
3. Pipeline auto-detects the file, extracts, translates, and builds the patch
4. User copies `build/.../atmosphere/` to SD card root — done

## User Experience Goals
- **Zero friction**: single command, sensible defaults
- **Transparency**: progress logged to `logs/pipeline_<timestamp>.log`; `_check.py` gives a status report at any time
- **Resumability**: long translation runs can be resumed with `--skip-extract` or `--skip-translate`
- **Correctness**: placeholder logic ensures game variables survive translation intact

## Primary User
A technically capable hobby user who owns a modded Nintendo Switch and wants to play untranslated games in Turkish (or another language).
