#!/usr/bin/env python3
"""
switch-translator — Nintendo Switch Game Translation Pipeline
=============================================================

Usage:
    python pipeline.py [OPTIONS]

Options:
    --input FILE       Path to .nsp or .xci (overrides input/ auto-detect)
    --config FILE      Config file path (default: config/config.json)
    --language LANG    Override translation language
    --skip-translate   Skip translation phase (use existing translated/)
    --skip-extract     Skip extraction phase (use existing work/)
    --zip              Package the final patch as a ZIP archive
    --help             Show this message
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap — add project root to sys.path
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import ROOT_DIR, banner, load_config, setup_logging  # noqa: E402
from src import extractor, scanner, translator, rebuilder, patcher  # noqa: E402


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Nintendo Switch Game Translation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input", metavar="FILE", help="Path to .nsp or .xci game file")
    p.add_argument("--config", metavar="FILE", default="config/config.json")
    p.add_argument("--language", metavar="LANG", help="Override translation language")
    p.add_argument("--skip-translate", action="store_true")
    p.add_argument("--skip-extract", action="store_true")
    p.add_argument("--zip", action="store_true", help="ZIP the output patch")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

INPUT_DIR = ROOT / "input"
WORK_DIR = ROOT / "work"
TEXT_DIR = ROOT / "text"
TRANSLATED_DIR = ROOT / "translated"
BUILD_DIR = ROOT / "build"
LOGS_DIR = ROOT / "logs"

for _d in (INPUT_DIR, WORK_DIR, TEXT_DIR, TRANSLATED_DIR, BUILD_DIR, LOGS_DIR):
    _d.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    """Execute the full pipeline. Returns exit code (0 = success)."""

    # --- Load configuration ---
    config_path = ROOT / args.config
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}")
        return 1
    config = load_config(config_path)

    if args.language:
        config["translation_language"] = args.language

    # --- Logging ---
    log = setup_logging(LOGS_DIR, config.get("log_level", "INFO"))

    banner("Nintendo Switch Translation Pipeline")
    log.info("Config: %s", config_path)
    log.info("Target language: %s", config["translation_language"])

    start_time = time.monotonic()

    # ======================================================================
    # PHASE 1+2 — Extraction
    # ======================================================================
    banner("Phase 1-2 — Extraction")

    game_file: Path | None = None
    game_name: str = "unknown_game"
    title_id: str | None = None
    romfs_dir: Path | None = None

    if not args.skip_extract:
        # Locate game file
        if args.input:
            game_file = Path(args.input).resolve()
            if not game_file.exists():
                log.error("Input file not found: %s", game_file)
                return 1
        else:
            game_file = extractor.detect_input_file(INPUT_DIR)
            if game_file is None:
                log.error("No .nsp or .xci file found in %s", INPUT_DIR)
                log.error("Place a game file in input/ or use --input <path>")
                return 1

        # Move to work dir if needed
        if game_file.parent != WORK_DIR / game_file.stem:
            game_file, game_name = extractor.move_to_work(game_file, WORK_DIR)
        else:
            game_name = game_file.stem

        romfs_dir, game_name, title_id = extractor.extract(
            game_file, WORK_DIR, config, log
        )
        if romfs_dir is None:
            log.error("Extraction failed — aborting")
            return 1
    else:
        # Skip extraction: find existing work dir
        existing_work = sorted(WORK_DIR.iterdir()) if WORK_DIR.exists() else []
        for d in existing_work:
            if d.is_dir() and (d / "romfs").exists():
                game_name = d.name
                romfs_dir = d / "romfs"
                log.info("Using existing extraction: %s", romfs_dir)
                break
        if romfs_dir is None:
            log.error("--skip-extract used but no extracted romfs found in %s", WORK_DIR)
            return 1

    log.info("Game name : %s", game_name)
    log.info("Title ID  : %s", title_id or "(unknown)")
    log.info("RomFS     : %s", romfs_dir)

    # ======================================================================
    # PHASE 3+4 — Scan & Export Text
    # ======================================================================
    banner("Phase 3-4 — File Discovery & Text Export")

    text_items = scanner.scan(romfs_dir, TEXT_DIR, game_name, config, log)
    if not text_items:
        log.warning("No text files found in RomFS — nothing to translate")
        return 0

    log.info("Text files ready for translation: %d", len(text_items))

    # ======================================================================
    # PHASE 5 — Translation
    # ======================================================================
    banner("Phase 5 — Translation")

    if not args.skip_translate:
        translated_count = translator.translate_all(
            TEXT_DIR, TRANSLATED_DIR, game_name, config, log
        )
        if translated_count == 0:
            log.error("Translation produced no output — check server connectivity")
            log.error("Endpoint: %s", config["translation_endpoint"])
            return 1
        log.info("Translated: %d/%d files", translated_count, len(text_items))
    else:
        log.info("--skip-translate: using existing translations in %s", TRANSLATED_DIR)

    # Check translated dir has content
    game_translated_dir = TRANSLATED_DIR / game_name
    if not game_translated_dir.exists() or not any(game_translated_dir.glob("*.json")):
        log.error("No translated files found in %s", game_translated_dir)
        return 1

    # ======================================================================
    # PHASE 6 — Rebuild
    # ======================================================================
    banner("Phase 6 — Rebuild")

    build_romfs_dir = BUILD_DIR / game_name / "romfs"
    build_romfs_dir.mkdir(parents=True, exist_ok=True)

    rebuilt_count = rebuilder.rebuild_all(
        TEXT_DIR,
        TRANSLATED_DIR,
        romfs_dir,
        build_romfs_dir,
        game_name,
        config,
        log,
    )
    log.info("Rebuilt: %d file(s)", rebuilt_count)

    if rebuilt_count == 0:
        log.warning("No files were rebuilt — patch may be empty")

    # ======================================================================
    # PHASE 7 — Patch Creation
    # ======================================================================
    banner("Phase 7 — Patch Creation")

    patch_dir = BUILD_DIR / "game_translation_patch"
    patch_romfs = patcher.create_patch(
        build_romfs_dir=build_romfs_dir,
        title_id=title_id or "0000000000000000",
        patch_dir=patch_dir,
        game_name=game_name,
        logger=log,
    )

    if patch_romfs is None:
        log.error("Patch creation failed")
        return 1

    # Optional ZIP
    if args.zip:
        zip_out = BUILD_DIR / f"{game_name}_patch"
        patcher.package_patch(patch_dir, zip_out)

    # ======================================================================
    # Done
    # ======================================================================
    elapsed = time.monotonic() - start_time
    banner("Pipeline Complete")
    log.info("Elapsed time : %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)
    log.info("Output patch : %s", patch_dir)
    log.info("")
    log.info("To use the patch:")
    log.info("  Copy the 'atmosphere' folder from:")
    log.info("  %s", patch_dir)
    log.info("  to the root of your SD card.")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(run(_parse_args()))
