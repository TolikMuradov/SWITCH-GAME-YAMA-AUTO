"""
Phase 7 — Atmosphere LayeredFS patch creation.

Creates the standard Atmosphere directory structure:
  build/patch/atmosphere/contents/<TitleID>/romfs/

All rebuilt files from build/<game_name>/romfs/ are copied there.
The resulting patch folder can be placed directly on an SD card.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from .utils import safe_copy

_LOG = logging.getLogger("switch_translator.patcher")


def create_patch(
    build_romfs_dir: Path,
    title_id: str,
    patch_dir: Path,
    game_name: str,
    logger: Optional[logging.Logger] = None,
) -> Optional[Path]:
    """
    Copy all files from *build_romfs_dir* into the Atmosphere LayeredFS
    structure under *patch_dir*.

    Returns the path to the atmosphere/contents/<TitleID>/romfs/ directory,
    or None if no files were copied.
    """
    global _LOG
    if logger:
        _LOG = logger.getChild("patcher")

    if not title_id:
        title_id = "0000000000000000"
        _LOG.warning("Title ID unknown — using placeholder: %s", title_id)

    # Normalise title ID to uppercase, 16 hex digits
    title_id = title_id.upper().zfill(16)

    atmos_romfs = patch_dir / "atmosphere" / "contents" / title_id / "romfs"
    atmos_romfs.mkdir(parents=True, exist_ok=True)

    romfs_files = [f for f in build_romfs_dir.rglob("*") if f.is_file()]
    if not romfs_files:
        _LOG.warning("No rebuilt files found in %s — patch will be empty", build_romfs_dir)
        return atmos_romfs

    copied = 0
    for src in romfs_files:
        rel = src.relative_to(build_romfs_dir)
        dst = atmos_romfs / rel
        if safe_copy(src, dst, logger=_LOG):
            copied += 1

    _LOG.info(
        "Patch created: %d file(s) → %s",
        copied,
        patch_dir / "atmosphere" / "contents" / title_id,
    )

    # Write a metadata file
    meta_path = patch_dir / "patch_info.txt"
    meta_path.write_text(
        f"Game:        {game_name}\n"
        f"Title ID:    {title_id}\n"
        f"Files:       {copied}\n"
        f"Language:    (see config)\n"
        f"Tool:        switch-translator\n",
        encoding="utf-8",
    )

    return atmos_romfs


def package_patch(patch_dir: Path, output_path: Path) -> bool:
    """
    Optionally ZIP the patch directory for easy distribution.
    Returns True on success.
    """
    try:
        shutil.make_archive(
            base_name=str(output_path.with_suffix("")),
            format="zip",
            root_dir=str(patch_dir.parent),
            base_dir=patch_dir.name,
        )
        _LOG.info("Patch zipped: %s.zip", output_path.with_suffix(""))
        return True
    except Exception as exc:
        _LOG.error("Failed to create patch ZIP: %s", exc)
        return False
