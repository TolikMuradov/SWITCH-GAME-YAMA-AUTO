"""
Phase 6 — Rebuild translated text back into original file formats.

Supported formats:
  • MSBT  — via msbt_tool subprocess or built-in MSBT writer
  • JSON  — direct key replacement
  • CSV   — cell replacement
  • XML   — element text replacement
  • TXT / YAML / YML — line replacement
  • Binary — not rebuilt (text-only extraction, no rebuild)

Output files are placed in build/<game_name>/romfs/ mirroring the
original RomFS directory structure.
"""

from __future__ import annotations

import csv
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from .msbt import read_msbt, write_msbt
from .utils import ensure_executable, run_tool, safe_copy

_LOG = logging.getLogger("switch_translator.rebuilder")


# ---------------------------------------------------------------------------
# Per-format rebuild functions
# ---------------------------------------------------------------------------

def _rebuild_msbt(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
    config: dict,
) -> bool:
    """Rebuild an MSBT file from translated entries."""
    # Try msbt_tool subprocess first
    msbt_tool_path = Path(config["tools"].get("msbt_tool", ""))
    if msbt_tool_path.name:
        from .utils import ROOT_DIR
        if not msbt_tool_path.is_absolute():
            msbt_tool_path = ROOT_DIR / msbt_tool_path
        if msbt_tool_path.exists():
            ok = _rebuild_msbt_via_tool(original_path, entries, output_path, msbt_tool_path, config)
            if ok:
                return True
            _LOG.warning("msbt_tool rebuild failed; using built-in writer")

    # Built-in writer
    return _rebuild_msbt_builtin(original_path, entries, output_path)


def _rebuild_msbt_via_tool(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
    tool_path: Path,
    config: dict,
) -> bool:
    """Use external msbt_tool to rebuild the MSBT."""
    ensure_executable(tool_path)
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Write translated entries to a yaml-like file expected by tool
        entry_data = {e["label"]: e["text"] for e in entries}
        yaml_path = tmp / "translated.json"
        yaml_path.write_text(json.dumps(entry_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # Try common msbt_tool invocation patterns
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for cmd in [
            [tool_path, "import", original_path, yaml_path, output_path],
            [tool_path, original_path, yaml_path, output_path],
        ]:
            rc, _, stderr = run_tool(cmd, timeout=60, logger=_LOG)
            if rc == 0 and output_path.exists():
                return True
            _LOG.debug("msbt_tool attempt failed: %s", stderr[:100])

    return False


def _rebuild_msbt_builtin(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
) -> bool:
    """Rebuild MSBT using the built-in Python writer."""
    try:
        msbt = read_msbt(original_path)
        translations = {e["label"]: e["text"] for e in entries}
        msbt.apply_dict(translations)
        write_msbt(msbt, output_path)
        return True
    except Exception as exc:
        _LOG.error("Built-in MSBT rebuild failed for %s: %s", original_path.name, exc)
        return False


def _rebuild_json(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
) -> bool:
    """Rebuild JSON file by patching string values at recorded key paths."""
    try:
        with open(original_path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)

        label_map = {e["label"]: e["text"] for e in entries}

        def _apply(node, path=""):
            if isinstance(node, str):
                return label_map.get(path, node)
            elif isinstance(node, dict):
                return {k: _apply(v, f"{path}.{k}" if path else k) for k, v in node.items()}
            elif isinstance(node, list):
                return [_apply(v, f"{path}[{i}]") for i, v in enumerate(node)]
            return node

        patched = _apply(obj)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(patched, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        _LOG.error("JSON rebuild failed for %s: %s", original_path.name, exc)
        return False


def _rebuild_csv(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
) -> bool:
    """Rebuild CSV by replacing cell text."""
    try:
        entry_map: Dict[str, str] = {e["label"]: e["text"] for e in entries}
        rows = []
        with open(original_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            for row_idx, row in enumerate(reader):
                new_row = []
                for col_idx, cell in enumerate(row):
                    key = f"r{row_idx}c{col_idx}"
                    new_row.append(entry_map.get(key, cell))
                rows.append(new_row)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows)
        return True
    except Exception as exc:
        _LOG.error("CSV rebuild failed for %s: %s", original_path.name, exc)
        return False


def _rebuild_xml(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
) -> bool:
    """Rebuild XML by patching element text."""
    try:
        tree = ET.parse(original_path)
        label_map = {e["label"]: e["text"] for e in entries}

        for elem in tree.iter():
            tag = elem.tag
            if tag in label_map and elem.text and elem.text.strip():
                elem.text = label_map[tag]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(str(output_path), encoding="unicode", xml_declaration=True)
        return True
    except Exception as exc:
        _LOG.error("XML rebuild failed for %s: %s", original_path.name, exc)
        return False


def _rebuild_text(
    original_path: Path,
    entries: List[Dict],
    output_path: Path,
) -> bool:
    """Rebuild plain-text / YAML files line by line."""
    try:
        original_lines = original_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        label_map = {e["label"]: e["text"] for e in entries}
        new_lines = []
        for i, line in enumerate(original_lines):
            key = f"line_{i}"
            if key in label_map:
                # Preserve the original line ending
                ending = ""
                if line.endswith("\r\n"):
                    ending = "\r\n"
                elif line.endswith("\n"):
                    ending = "\n"
                new_lines.append(label_map[key] + ending)
            else:
                new_lines.append(line)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(new_lines), encoding="utf-8")
        return True
    except Exception as exc:
        _LOG.error("Text rebuild failed for %s: %s", original_path.name, exc)
        return False


# ---------------------------------------------------------------------------
# SARC repacking
# ---------------------------------------------------------------------------

def _repack_sarc(
    sarc_extracted_dir: Path,
    original_sarc: Path,
    output_sarc: Path,
    config: dict,
) -> bool:
    """Repack a SARC archive using sarc_tool."""
    sarc_tool_path = Path(config["tools"].get("sarc_tool", ""))
    if sarc_tool_path.name:
        from .utils import ROOT_DIR
        if not sarc_tool_path.is_absolute():
            sarc_tool_path = ROOT_DIR / sarc_tool_path
        if sarc_tool_path.exists():
            ensure_executable(sarc_tool_path)
            output_sarc.parent.mkdir(parents=True, exist_ok=True)
            rc, _, stderr = run_tool(
                [sarc_tool_path, "create", sarc_extracted_dir, output_sarc],
                timeout=120,
                logger=_LOG,
            )
            if rc == 0:
                return True
            _LOG.warning("sarc_tool repack failed: %s", stderr[:100])

    # Without sarc_tool, copy the original SARC as-is (best effort)
    _LOG.warning("Cannot repack SARC %s (sarc_tool unavailable); copying original", original_sarc.name)
    return safe_copy(original_sarc, output_sarc, logger=_LOG)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def rebuild_all(
    text_dir: Path,
    translated_dir: Path,
    romfs_dir: Path,
    build_romfs_dir: Path,
    game_name: str,
    config: dict,
    logger: Optional[logging.Logger] = None,
) -> int:
    """
    Phase 6 entry point.

    For each translated manifest in translated/<game_name>/:
      1. Find the original source file in romfs/
      2. Rebuild the translated version
      3. Write to build/<game_name>/romfs/ (mirroring original path)

    Returns count of successfully rebuilt files.
    """
    global _LOG
    if logger:
        _LOG = logger.getChild("rebuilder")

    game_translated_dir = translated_dir / game_name
    manifests = sorted(game_translated_dir.glob("*.json"))
    if not manifests:
        _LOG.warning("No translated manifests in %s", game_translated_dir)
        return 0

    _LOG.info("Rebuilding %d translated file(s) …", len(manifests))
    success = 0

    for mpath in manifests:
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.error("Cannot read manifest %s: %s", mpath.name, exc)
            continue

        source_rel = manifest.get("source_file", "")
        fmt = manifest.get("file_format", "")
        entries = manifest.get("entries", [])

        original_path = romfs_dir / source_rel
        output_path = build_romfs_dir / source_rel

        if not original_path.exists():
            _LOG.warning("Original file not found: %s", original_path)
            # Still try to write translated output for non-romfs sources
        elif fmt == "binary":
            # Binary files are not rebuilt — skip
            continue

        ok = False
        try:
            if fmt == "msbt":
                ok = _rebuild_msbt(original_path, entries, output_path, config)
            elif fmt == "json":
                ok = _rebuild_json(original_path, entries, output_path)
            elif fmt == "csv":
                ok = _rebuild_csv(original_path, entries, output_path)
            elif fmt == "xml":
                ok = _rebuild_xml(original_path, entries, output_path)
            elif fmt in ("txt", "yaml", "yml", "bmg"):
                ok = _rebuild_text(original_path, entries, output_path)
            else:
                _LOG.debug("No rebuilder for format '%s', skipping: %s", fmt, source_rel)
                continue
        except Exception as exc:
            _LOG.error("Rebuild error for %s: %s", source_rel, exc)
            continue

        if ok:
            success += 1
            _LOG.debug("Rebuilt: %s", source_rel)
        else:
            _LOG.warning("Rebuild failed: %s", source_rel)

    _LOG.info("Rebuild complete: %d/%d files", success, len(manifests))
    return success
