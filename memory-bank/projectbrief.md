# Project Brief — switch-translator

## Project Name
switch-translator

## Summary
Automated Nintendo Switch game translation pipeline. Extracts game text from NSP/XCI files, translates it using a locally-hosted AI model (Ollama), and produces an Atmosphere LayeredFS patch ready to deploy on a modded console.

## Core Requirements
- Accept Nintendo Switch game files (`.nsp`, `.xci`) as input
- Extract RomFS content using hactool
- Detect and parse all translatable text formats (MSBT, JSON, CSV, XML, TXT, YAML, binary strings)
- Translate extracted text using Ollama HTTP API
- Cache translations in SQLite to avoid re-work
- Rebuild patched game assets (SARC/MSBT)
- Output a drop-in Atmosphere LayeredFS patch directory

## Goals
- Full automation: one command (`python pipeline.py`) runs the entire pipeline
- Language-configurable: default target is Turkish, overridable via CLI or config
- Resumable: `--skip-extract` and `--skip-translate` flags allow re-running from mid-pipeline
- Reliable: placeholder preservation, retry logic, SQLite cache

## Scope
- Input: `.nsp` / `.xci` game files placed in `input/`
- Output: `build/game_translation_patch/atmosphere/contents/<TitleID>/romfs/`
- The user copies the `atmosphere/` folder to the SD card root

## Out of Scope
- Online translation services (no Google Translate, DeepL, etc.)
- GUI interface
- Cloud deployment
