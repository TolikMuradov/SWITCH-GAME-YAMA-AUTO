"""
Phase 3 & 4 — File discovery and text export.

Recursively scans a RomFS directory, detects text containers
(MSBT, JSON, CSV, XML, TXT, YAML, and binary files with strings),
extracts SARC archives along the way, and exports text to the
text/ directory as JSON manifests ready for translation.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .msbt import read_msbt
from .utils import ensure_executable, run_tool

_LOG = logging.getLogger("switch_translator.scanner")

SARC_MAGIC = b"SARC"
YAZ0_MAGIC = b"Yaz0"


# ---------------------------------------------------------------------------
# Data model for a translatable file
# ---------------------------------------------------------------------------

@dataclass
class TextItem:
    """Represents a single exported text file ready for translation."""
    source_file: str          # relative path inside romfs
    export_file: str          # path of the JSON manifest in text/
    file_format: str          # msbt | json | csv | xml | txt | yaml | binary
    entries: List[Dict]       # [{index, label, text}, …]


# ---------------------------------------------------------------------------
# SARC / Yaz0 extraction
# ---------------------------------------------------------------------------

def _decompress_yaz0(data: bytes) -> bytes:
    """Decompress Yaz0-encoded data (used for .szs files)."""
    if data[:4] != YAZ0_MAGIC:
        return data
    dec_size = struct.unpack_from(">I", data, 4)[0]
    src = 16
    out = bytearray(dec_size)
    dst = 0
    data_len = len(data)
    while dst < dec_size and src < data_len:
        flag = data[src]
        src += 1
        for bit in range(7, -1, -1):
            if dst >= dec_size or src >= data_len:
                break
            if (flag >> bit) & 1:
                out[dst] = data[src]
                src += 1
                dst += 1
            else:
                if src + 1 >= data_len:
                    break
                b1, b2 = data[src], data[src + 1]
                src += 2
                dist = ((b1 & 0x0F) << 8) | b2
                nibble = b1 >> 4
                if nibble == 0:
                    # next byte encodes length
                    if src >= data_len:
                        break
                    n = data[src] + 0x12
                    src += 1
                else:
                    n = nibble + 2
                copy_src = dst - dist - 1
                for _ in range(n):
                    if dst >= dec_size:
                        break
                    if 0 <= copy_src < dst:
                        out[dst] = out[copy_src]
                    copy_src += 1
                    dst += 1
    return bytes(out)


def _extract_sarc_builtin(sarc_path: Path, out_dir: Path) -> bool:
    """Pure-Python SARC extractor (no external tool required)."""
    try:
        raw = sarc_path.read_bytes()
        if raw[:4] == YAZ0_MAGIC:
            raw = _decompress_yaz0(raw)
        if raw[:4] != SARC_MAGIC:
            return False

        bom = struct.unpack_from("<H", raw, 6)[0]
        E = "<" if bom == 0xFEFF else ">"
        header_size = struct.unpack_from(f"{E}H", raw, 4)[0]
        data_offset = struct.unpack_from(f"{E}I", raw, 12)[0]

        sfat_off = header_size
        if raw[sfat_off:sfat_off + 4] != b"SFAT":
            return False
        sfat_hdr_size = struct.unpack_from(f"{E}H", raw, sfat_off + 4)[0]
        node_count = struct.unpack_from(f"{E}H", raw, sfat_off + 6)[0]

        sfnt_off = sfat_off + sfat_hdr_size + node_count * 16
        if raw[sfnt_off:sfnt_off + 4] != b"SFNT":
            return False
        sfnt_hdr_size = struct.unpack_from(f"{E}H", raw, sfnt_off + 4)[0]
        name_table_off = sfnt_off + sfnt_hdr_size

        for i in range(node_count):
            node_off = sfat_off + sfat_hdr_size + i * 16
            attr = struct.unpack_from(f"{E}I", raw, node_off + 4)[0]
            file_start = struct.unpack_from(f"{E}I", raw, node_off + 8)[0]
            file_end = struct.unpack_from(f"{E}I", raw, node_off + 12)[0]

            # Name offset: upper 24 bits of attr, in 4-byte units
            name_off = name_table_off + ((attr >> 8) & 0xFFFFFF) * 4
            end = raw.index(b"\x00", name_off) if b"\x00" in raw[name_off:] else name_off
            file_name = raw[name_off:end].decode("utf-8", errors="replace")
            if not file_name:
                file_name = f"file_{i:04d}"

            file_data = raw[data_offset + file_start: data_offset + file_end]
            out_file = out_dir / file_name
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(file_data)

        _LOG.debug("SARC extracted %d files: %s", node_count, sarc_path.name)
        return True
    except Exception as exc:
        _LOG.error("SARC extract error %s: %s", sarc_path.name, exc)
        return False


def extract_sarc(sarc_path: Path, out_dir: Path, config: dict) -> bool:
    """Extract SARC/SZS archive, trying sarc_tool first then built-in."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sarc_tool_path = Path(config["tools"].get("sarc_tool", ""))
    if sarc_tool_path.name:
        from .utils import ROOT_DIR
        if not sarc_tool_path.is_absolute():
            sarc_tool_path = ROOT_DIR / sarc_tool_path
        if sarc_tool_path.exists():
            ensure_executable(sarc_tool_path)
            rc, _, _ = run_tool(
                [sarc_tool_path, "extract", sarc_path, out_dir],
                timeout=60,
                logger=_LOG,
            )
            if rc == 0:
                return True
    return _extract_sarc_builtin(sarc_path, out_dir)


# ---------------------------------------------------------------------------
# Text extraction helpers per format
# ---------------------------------------------------------------------------

def _entries_from_msbt(file_path: Path) -> Tuple[str, List[Dict]]:
    try:
        msbt = read_msbt(file_path)
        entries = [
            {"index": e.index, "label": e.label, "text": e.text}
            for e in msbt.entries
            if e.text.strip()
        ]
        return "msbt", entries
    except Exception as exc:
        _LOG.warning("MSBT parse error %s: %s", file_path.name, exc)
        return "msbt", []


def _entries_from_json(file_path: Path) -> Tuple[str, List[Dict]]:
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        entries = []

        def _walk(node, path=""):
            if isinstance(node, str) and node.strip():
                entries.append({"index": len(entries), "label": path, "text": node})
            elif isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _walk(v, f"{path}[{i}]")

        _walk(obj)
        return "json", entries
    except Exception as exc:
        _LOG.warning("JSON parse error %s: %s", file_path.name, exc)
        return "json", []


def _entries_from_csv(file_path: Path) -> Tuple[str, List[Dict]]:
    try:
        entries = []
        with open(file_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            for row_idx, row in enumerate(reader):
                for col_idx, cell in enumerate(row):
                    if cell.strip():
                        entries.append({
                            "index": len(entries),
                            "label": f"r{row_idx}c{col_idx}",
                            "text": cell,
                        })
        return "csv", entries
    except Exception as exc:
        _LOG.warning("CSV parse error %s: %s", file_path.name, exc)
        return "csv", []


def _entries_from_xml(file_path: Path) -> Tuple[str, List[Dict]]:
    try:
        tree = ET.parse(file_path)
        entries = []
        for elem in tree.iter():
            if elem.text and elem.text.strip():
                tag_path = elem.tag
                entries.append({
                    "index": len(entries),
                    "label": tag_path,
                    "text": elem.text.strip(),
                })
        return "xml", entries
    except Exception as exc:
        _LOG.warning("XML parse error %s: %s", file_path.name, exc)
        return "xml", []


def _entries_from_text(file_path: Path) -> Tuple[str, List[Dict]]:
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        entries = [
            {"index": i, "label": f"line_{i}", "text": line.rstrip("\n\r")}
            for i, line in enumerate(lines)
            if line.strip()
        ]
        return "txt", entries
    except Exception as exc:
        _LOG.warning("TXT read error %s: %s", file_path.name, exc)
        return "txt", []


def _entries_from_binary(file_path: Path, min_len: int = 4) -> Tuple[str, List[Dict]]:
    """Extract printable ASCII strings from a binary file."""
    try:
        data = file_path.read_bytes()
        pattern = re.compile(rb"[ -~]{" + str(min_len).encode() + rb",}")
        matches = pattern.findall(data)
        entries = []
        seen = set()
        for m in matches:
            text = m.decode("ascii", errors="replace")
            if text not in seen:
                seen.add(text)
                entries.append({"index": len(entries), "label": f"str_{len(entries)}", "text": text})
        return "binary", entries
    except Exception as exc:
        _LOG.warning("Binary string extract error %s: %s", file_path.name, exc)
        return "binary", []


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def _is_sarc(path: Path) -> bool:
    try:
        magic = path.read_bytes()[:4]
        return magic in (SARC_MAGIC, YAZ0_MAGIC)
    except OSError:
        return False


# Alias kept for internal use
_is_sarc_file = _is_sarc


# Extensions that are known to be audio, video, image, or other binary-only formats.
# Files with these extensions will never be scanned for text.
_BINARY_ONLY_EXTENSIONS = {
    # Audio
    ".bank", ".fsb", ".mp3", ".ogg", ".wav", ".aac", ".flac", ".wem", ".bnk",
    # Video
    ".mp4", ".webm", ".bik", ".bk2", ".usm",
    # Images
    ".png", ".jpg", ".jpeg", ".dds", ".tga", ".bmp", ".ktx", ".astc", ".webp",
    # Nintendo Switch packed formats (handled by SARC extractor, not binary scan)
    ".nca", ".nso", ".nro", ".nacp", ".npdm",
    # Compiled shaders / binaries
    ".frag", ".vert", ".glsl", ".hlsl", ".shader", ".spirv",
    ".dll", ".pdb", ".exe", ".so", ".dylib",
    # Fonts (binary)
    ".otf", ".ttf", ".woff", ".woff2",
    # Other binary
    ".bin", ".dat", ".pak", ".atlas", ".nrr",
}


def _should_skip_path(rel_path: Path, config: dict) -> bool:
    """
    Return True if this file should be skipped entirely (metadata, junk,
    binary-only format, wrong-language subtitle).
    """
    rel_str = str(rel_path).replace("\\", "/")
    name = rel_path.name
    suffix = rel_path.suffix.lower()

    # macOS / Synology junk
    if name == ".DS_Store":
        return True
    if name.startswith("._"):           # macOS resource fork
        return True
    if "@eaDir" in rel_str:             # Synology extended attributes dir
        return True
    if "@SynoResource" in name:         # Synology resource file
        return True
    if "@ea" in name:                   # any other Synology ea metadata
        return True

    # Known binary-only extensions
    if suffix in _BINARY_ONLY_EXTENSIONS:
        return True

    # Skip known binary/non-text directories
    _BINARY_DIRS = (
        "/Audio/", "/audio/",
        "/EffectsForge", "/Effects/",
        "/Movies/", "/movies/",
        "/Fonts/", "/fonts/",
    )
    for bd in _BINARY_DIRS:
        if bd in rel_str:
            return True

    # Skip subtitle files for non-source languages.
    # Hades: Content/Subtitles/<lang>/<name>.csv
    source_lang = config.get("source_language", "en").lower()
    _SUBTITLE_DIR = re.compile(r"[/\\]Subtitles[/\\]([a-z]{2})[/\\]", re.IGNORECASE)
    m = _SUBTITLE_DIR.search(rel_str)
    if m:
        file_lang = m.group(1).lower()
        if file_lang != source_lang:
            return True

    return False


def scan_romfs(romfs_dir: Path, text_dir: Path, config: dict) -> List[TextItem]:
    """
    Recursively walk *romfs_dir*, extract SARCs and export text.
    Returns a list of TextItem objects (one per exported file).
    """
    text_extensions = set(config.get("text_extensions", []))
    sarc_extensions = set(config.get("sarc_extensions", []))
    skip_filenames = set(config.get("skip_filenames", []))
    min_bin_len = config.get("min_binary_string_length", 4)

    items: List[TextItem] = []
    all_files: List[Tuple[Path, Path]] = []  # (abs_path, rel_path)

    # work_dir is the project root's work/ directory (two levels up from text/<game>/)
    work_dir = text_dir.parent.parent / "work"
    # Collect files including inside extracted SARCs
    _collect_files(romfs_dir, romfs_dir, all_files, sarc_extensions, text_dir, config, work_dir)

    total = len(all_files)
    _LOG.info("Found %d candidate files to inspect", total)

    for idx, (abs_path, rel_path) in enumerate(all_files):
        if abs_path.name.lower() in skip_filenames:
            continue
        if _should_skip_path(rel_path, config):
            continue

        suffix = abs_path.suffix.lower()
        rel_str = str(rel_path).replace("\\", "/")

        fmt: Optional[str] = None
        entries: List[Dict] = []

        try:
            if suffix == ".msbt":
                fmt, entries = _entries_from_msbt(abs_path)
            elif suffix == ".json":
                fmt, entries = _entries_from_json(abs_path)
            elif suffix in (".csv",):
                fmt, entries = _entries_from_csv(abs_path)
            elif suffix == ".xml":
                fmt, entries = _entries_from_xml(abs_path)
            elif suffix in (".txt", ".yaml", ".yml", ".bmg"):
                fmt, entries = _entries_from_text(abs_path)
            # Binary fallback intentionally removed — it produces millions of
            # useless entries from audio banks, shader files, etc.
        except Exception as exc:
            _LOG.error("Error processing %s: %s", rel_str, exc)
            continue

        if not fmt or not entries:
            continue

        # Build safe export filename
        safe_name = rel_str.replace("/", "__").replace("\\", "__")
        export_path = text_dir / f"{safe_name}.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)

        manifest = {
            "source_file": rel_str,
            "file_format": fmt,
            "entries": entries,
        }
        export_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        item = TextItem(
            source_file=rel_str,
            export_file=str(export_path),
            file_format=fmt,
            entries=entries,
        )
        items.append(item)
        _LOG.debug("[%d/%d] Exported %d entries: %s", idx + 1, total, len(entries), rel_str)

    _LOG.info("Exported %d text files to %s", len(items), text_dir)
    return items


def _collect_files(
    base_dir: Path,
    scan_dir: Path,
    result: List[Tuple[Path, Path]],
    sarc_extensions: set,
    text_dir: Path,
    config: dict,
    work_dir: Optional[Path] = None,
) -> None:
    """Recursively collect files, extracting SARCs in-place."""
    # sarc_extracted lives next to text/ under the project root
    sarc_work = (work_dir or text_dir.parent) / "work" / "sarc_extracted"
    for path in sorted(scan_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base_dir)
        suffix = path.suffix.lower()

        if suffix in sarc_extensions or _is_sarc_file(path):
            # Extract and recurse
            extract_out = sarc_work / str(rel)
            if not extract_out.exists() or not any(extract_out.rglob("*")):
                extract_sarc(path, extract_out, config)
            if extract_out.exists():
                _collect_files(extract_out, extract_out, result, sarc_extensions, text_dir, config, work_dir)
        else:
            result.append((path, rel))





# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scan(
    romfs_dir: Path,
    text_dir: Path,
    game_name: str,
    config: dict,
    logger: Optional[logging.Logger] = None,
) -> List[TextItem]:
    """Phase 3+4 entry point. Returns list of exported TextItems."""
    global _LOG
    if logger:
        _LOG = logger.getChild("scanner")

    game_text_dir = text_dir / game_name
    game_text_dir.mkdir(parents=True, exist_ok=True)

    # Check if already exported
    existing = list(game_text_dir.glob("*.json"))
    if existing:
        _LOG.info("Text already exported (%d files) — skipping scan", len(existing))
        items = []
        for ep in existing:
            try:
                data = json.loads(ep.read_text(encoding="utf-8"))
                items.append(TextItem(
                    source_file=data["source_file"],
                    export_file=str(ep),
                    file_format=data["file_format"],
                    entries=data["entries"],
                ))
            except Exception:
                pass
        return items

    return scan_romfs(romfs_dir, game_text_dir, config)
