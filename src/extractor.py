"""
Phase 1 & 2 — Input file detection and filesystem extraction.

Responsibilities:
  • Detect .nsp / .xci in input/
  • Move game file into work/<game_name>/
  • Call hactool to extract NCAs from NSP / XCI
  • Identify the Program NCA by content type
  • Extract RomFS (and ExeFS) from the Program NCA
  • Return (romfs_dir, game_name, title_id)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from .utils import ensure_executable, run_tool, safe_move

_LOG = logging.getLogger("switch_translator.extractor")


# ---------------------------------------------------------------------------
# Phase 1 — File detection
# ---------------------------------------------------------------------------

def detect_input_file(input_dir: Path) -> Optional[Path]:
    """Return the first .nsp or .xci found in *input_dir*, or None."""
    for pattern in ("*.nsp", "*.NSP", "*.xci", "*.XCI"):
        found = sorted(input_dir.glob(pattern))
        if found:
            _LOG.info("Detected input file: %s", found[0].name)
            return found[0]
    return None


def move_to_work(game_file: Path, work_dir: Path) -> Tuple[Path, str]:
    """
    Move *game_file* into work/<game_stem>/<filename>.
    Returns (new_path, game_name).
    """
    game_name = game_file.stem
    dest_dir = work_dir / game_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / game_file.name
    if not dest.exists():
        safe_move(game_file, dest)
        _LOG.info("Moved '%s' → '%s'", game_file.name, dest)
    else:
        _LOG.info("Game file already in work dir: %s", dest)
    return dest, game_name


# ---------------------------------------------------------------------------
# hactool wrapper
# ---------------------------------------------------------------------------

def _resolve_path(p: str, default: str) -> Path:
    resolved = Path(p).expanduser()
    if not resolved.is_absolute():
        from .utils import ROOT_DIR as _R
        resolved = _R / resolved
    return resolved


def _lookup_title_key(title_id: Optional[str], config: dict) -> Optional[str]:
    """Search title.keys for a matching rights ID and return the hex key."""
    if not title_id:
        return None
    title_keys_file = _resolve_path(
        config.get("title_keys_file", "~/.switch/title.keys"),
        "~/.switch/title.keys",
    )
    if not title_keys_file.exists():
        return None
    tid_lower = title_id.lower()
    for line in title_keys_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        rights_id, _, key = line.partition("=")
        rights_id = rights_id.strip().lower()
        key = key.strip()
        # rights_id starts with title_id (16 hex chars)
        if rights_id.startswith(tid_lower):
            _LOG.debug("Title key found for %s (rights_id=%s)", title_id, rights_id)
            return key
    return None


def _hactool(config: dict, *args, title_id: Optional[str] = None) -> Tuple[int, str, str]:
    hactool_path = _resolve_path(config["tools"]["hactool"], "hactool/hactool")
    ensure_executable(hactool_path)

    keys_file = _resolve_path(
        config.get("keys_file", "~/.switch/prod.keys"),
        "~/.switch/prod.keys",
    )
    cmd = [str(hactool_path)]
    if keys_file.exists():
        cmd += ["--keyset", str(keys_file)]
    title_key = _lookup_title_key(title_id, config)
    if title_key:
        cmd += [f"--titlekey={title_key}"]
    cmd += [str(a) for a in args]
    return run_tool(cmd, timeout=600, logger=_LOG)


# ---------------------------------------------------------------------------
# Phase 2a — NCA extraction from NSP / XCI
# ---------------------------------------------------------------------------

def _extract_nsp(nsp_path: Path, nca_dir: Path, config: dict) -> bool:
    """Extract NCA files from an NSP (PFS0) archive."""
    nca_dir.mkdir(parents=True, exist_ok=True)
    # Try -t nsp first, then -t pfs0 for older hactool versions
    for type_flag in ("nsp", "pfs0"):
        dir_flag = f"--{type_flag}dir={nca_dir}"
        rc, stdout, stderr = _hactool(config, "-t", type_flag, dir_flag, nsp_path)
        if rc == 0:
            _LOG.info("Extracted NSP (type=%s) → %s", type_flag, nca_dir)
            return True
        _LOG.debug("hactool -t %s failed: %s", type_flag, stderr[:120])
    _LOG.error("Failed to extract NSP: %s", nsp_path)
    return False


def _extract_xci(xci_path: Path, nca_dir: Path, config: dict) -> bool:
    """Extract NCA files from an XCI cart image (secure partition)."""
    nca_dir.mkdir(parents=True, exist_ok=True)
    rc, stdout, stderr = _hactool(
        config, "-t", "xci", f"--securedir={nca_dir}", xci_path
    )
    if rc == 0:
        _LOG.info("Extracted XCI → %s", nca_dir)
        return True
    _LOG.error("Failed to extract XCI '%s': %s", xci_path, stderr[:200])
    return False


# ---------------------------------------------------------------------------
# Phase 2b — Program NCA identification
# ---------------------------------------------------------------------------

_TITLE_ID_RE = re.compile(r"Title\s*ID\s*:\s*([0-9a-fA-F]{16})", re.IGNORECASE)
_CONTENT_TYPE_RE = re.compile(r"Content\s*Type\s*:\s*(\w+)", re.IGNORECASE)


def _probe_nca(nca_path: Path, config: dict) -> Tuple[Optional[str], Optional[str]]:
    """Return (content_type, title_id) by parsing hactool output."""
    rc, stdout, _ = _hactool(config, "-t", "nca", nca_path)
    content_type: Optional[str] = None
    title_id: Optional[str] = None
    for line in stdout.splitlines():
        m = _CONTENT_TYPE_RE.search(line)
        if m:
            content_type = m.group(1).strip()
        m2 = _TITLE_ID_RE.search(line)
        if m2:
            title_id = m2.group(1).strip().upper()
    return content_type, title_id


def find_program_nca(nca_dir: Path, config: dict) -> Tuple[Optional[Path], Optional[str]]:
    """
    Scan *nca_dir* for NCA files and return (program_nca_path, title_id).
    The program NCA has Content Type == Program.
    Falls back to the largest NCA if no Program-type NCA is found.
    """
    nca_files = sorted(nca_dir.glob("*.nca"), key=lambda p: p.stat().st_size, reverse=True)
    if not nca_files:
        _LOG.error("No NCA files found in %s", nca_dir)
        return None, None

    _LOG.info("Scanning %d NCA(s) for program NCA …", len(nca_files))
    for nca in nca_files:
        content_type, title_id = _probe_nca(nca, config)
        _LOG.debug("  %s → type=%s, tid=%s", nca.name, content_type, title_id)
        if content_type and content_type.lower() == "program":
            _LOG.info("Program NCA: %s  (title ID: %s)", nca.name, title_id)
            return nca, title_id

    # Fallback
    fallback = nca_files[0]
    _LOG.warning("No Program-type NCA found; using largest: %s", fallback.name)
    _, title_id = _probe_nca(fallback, config)
    return fallback, title_id


# ---------------------------------------------------------------------------
# Phase 2c — RomFS extraction
# ---------------------------------------------------------------------------

def extract_romfs(
    nca_path: Path,
    romfs_dir: Path,
    exefs_dir: Path,
    config: dict,
    title_id: Optional[str] = None,
) -> bool:
    """Extract RomFS and ExeFS from the program NCA."""
    romfs_dir.mkdir(parents=True, exist_ok=True)
    exefs_dir.mkdir(parents=True, exist_ok=True)
    rc, stdout, stderr = _hactool(
        config,
        "-t", "nca",
        f"--romfsdir={romfs_dir}",
        f"--exefsdir={exefs_dir}",
        nca_path,
        title_id=title_id,
    )
    if rc == 0:
        file_count = sum(1 for f in romfs_dir.rglob("*") if f.is_file())
        _LOG.info("RomFS extracted: %d files → %s", file_count, romfs_dir)
        return True
    _LOG.error("Failed to extract RomFS from '%s': %s", nca_path.name, stderr[:400])
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract(
    game_file: Path,
    work_dir: Path,
    config: dict,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Optional[Path], str, Optional[str]]:
    """
    Full Phase 1+2 pipeline.

    Returns (romfs_dir, game_name, title_id).
    romfs_dir is None on failure.
    """
    global _LOG
    if logger:
        _LOG = logger.getChild("extractor")

    suffix = game_file.suffix.lower()
    game_name = game_file.stem
    game_dir = work_dir / game_name
    nca_dir = game_dir / "nca"
    romfs_dir = game_dir / "romfs"
    exefs_dir = game_dir / "exefs"

    # If romfs already exists (re-run), skip extraction
    if romfs_dir.exists() and any(romfs_dir.rglob("*")):
        _LOG.info("RomFS already extracted at %s — skipping extraction", romfs_dir)
        # Try to recover title_id from a previous probe
        nca_files = sorted(nca_dir.glob("*.nca"), key=lambda p: p.stat().st_size, reverse=True) if nca_dir.exists() else []
        title_id = None
        if nca_files:
            _, title_id = _probe_nca(nca_files[0], config)
        return romfs_dir, game_name, title_id

    # Step 1 — extract NCAs
    if suffix in (".nsp",):
        ok = _extract_nsp(game_file, nca_dir, config)
    elif suffix in (".xci",):
        ok = _extract_xci(game_file, nca_dir, config)
    else:
        _LOG.error("Unsupported file type: %s", suffix)
        return None, game_name, None

    if not ok:
        return None, game_name, None

    # Step 2 — find program NCA
    program_nca, title_id = find_program_nca(nca_dir, config)
    if program_nca is None:
        return None, game_name, None

    # Step 3 — extract RomFS
    ok = extract_romfs(program_nca, romfs_dir, exefs_dir, config, title_id=title_id)
    if not ok:
        return None, game_name, title_id

    return romfs_dir, game_name, title_id
