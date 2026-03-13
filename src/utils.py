"""
Shared utilities: logging, config loading, subprocess helpers,
file operations, and display helpers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Configure file + console logging and return the root logger."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"pipeline_{timestamp}.log"

    logger = logging.getLogger("switch_translator")
    logger.setLevel(logging.DEBUG)

    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(console_fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("Log file: %s", log_file)
    return logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    """Load and return the JSON config file."""
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_text(text: str) -> str:
    """Return the full SHA-256 hex digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def safe_copy(src: Path, dst: Path, logger: Optional[logging.Logger] = None) -> bool:
    """Copy *src* → *dst*, creating parent directories as needed."""
    log = logger or logging.getLogger("switch_translator")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return True
    except OSError as exc:
        log.error("copy %s → %s: %s", src, dst, exc)
        return False


def safe_move(src: Path, dst: Path, logger: Optional[logging.Logger] = None) -> bool:
    """Move *src* → *dst*, creating parent directories as needed."""
    log = logger or logging.getLogger("switch_translator")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return True
    except OSError as exc:
        log.error("move %s → %s: %s", src, dst, exc)
        return False


def ensure_executable(tool_path: Path) -> None:
    """Set the executable bit on *tool_path* if not already set."""
    try:
        mode = os.stat(tool_path).st_mode
        os.chmod(tool_path, mode | 0o111)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def run_tool(
    cmd: List,
    cwd: Optional[Path] = None,
    timeout: int = 300,
    logger: Optional[logging.Logger] = None,
) -> Tuple[int, str, str]:
    """
    Run an external tool and return (returncode, stdout, stderr).
    Never raises; errors are logged and returncode -1 is returned.
    """
    log = logger or logging.getLogger("switch_translator")
    str_cmd = [str(c) for c in cmd]
    log.debug("run: %s", " ".join(str_cmd))
    try:
        result = subprocess.run(
            str_cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.stdout:
            log.debug("stdout: %s", result.stdout[:2000])
        if result.returncode != 0 and result.stderr:
            log.debug("stderr: %s", result.stderr[:2000])
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log.error("tool timed out after %ds: %s", timeout, str_cmd[0])
        return -1, "", "timeout"
    except FileNotFoundError:
        log.error("tool not found: %s", str_cmd[0])
        return -1, "", "not found"
    except Exception as exc:  # noqa: BLE001
        log.error("tool error %s: %s", str_cmd[0], exc)
        return -1, "", str(exc)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_size(size_bytes: int) -> str:
    """Return a human-readable file-size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes = int(size_bytes / 1024)
    return f"{size_bytes:.1f} TB"


def print_progress(current: int, total: int, prefix: str = "") -> None:
    """Print a simple ASCII progress bar to stdout."""
    pct = int(current / total * 100) if total else 0
    filled = pct // 5
    bar = "#" * filled + "-" * (20 - filled)
    print(f"\r{prefix}[{bar}] {current}/{total} ({pct}%)", end="", flush=True)
    if current >= total:
        print()


def banner(title: str) -> None:
    """Print a section banner."""
    width = 64
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)
