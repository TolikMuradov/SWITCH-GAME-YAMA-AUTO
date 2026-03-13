"""
Phase 5 — Translation via Ollama HTTP API.

Features:
  • Placeholder preservation (format strings, tags, escape sequences)
  • Automatic text chunking for large files
  • SQLite translation cache (avoids re-translating identical text)
  • Retry with exponential back-off
  • Batch processing of all text manifests
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .utils import hash_text, print_progress

_LOG = logging.getLogger("switch_translator.translator")


# ---------------------------------------------------------------------------
# Placeholder preservation
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERNS = [
    re.compile(r"\{[^}]{1,64}\}"),          # {variable}, {0}, {player_name}
    re.compile(r"%[-+0-9*.]*[sdifuxXeEgGc%]"),  # printf: %s %02d %05.2f %%
    re.compile(r"</?[A-Za-z][^>]{0,64}>"),  # <color=red>, </br>
    re.compile(r"\\[nrtbfv0]"),              # \n \r \t \b etc.
    re.compile(r"\[\[[^\]]{1,64}\]\]"),     # [[code]]
    re.compile(r"\^[A-Z@]"),                # control chars ^A ^B
    re.compile(r"~[A-Z]"),                  # ~N (Nintendo line-break codes)
]

_TOKEN_PATTERN = re.compile(r"@@PH(\d+)@@")


def _preserve_placeholders(text: str) -> Tuple[str, List[str]]:
    """
    Replace all placeholders with @@PHn@@ tokens.
    Returns (modified_text, original_placeholders_list).
    """
    placeholders: List[str] = []
    combined = "|".join(p.pattern for p in _PLACEHOLDER_PATTERNS)
    master_re = re.compile(combined)

    def _replace(m: re.Match) -> str:
        idx = len(placeholders)
        placeholders.append(m.group(0))
        return f"@@PH{idx}@@"

    modified = master_re.sub(_replace, text)
    return modified, placeholders


def _restore_placeholders(text: str, placeholders: List[str]) -> str:
    """Restore @@PHn@@ tokens back to original placeholder strings."""
    def _replace(m: re.Match) -> str:
        idx = int(m.group(1))
        return placeholders[idx] if idx < len(placeholders) else m.group(0)
    return _TOKEN_PATTERN.sub(_replace, text)


def _verify_placeholders(original: str, translated: str, placeholders: List[str]) -> bool:
    """Check that all tokens survived translation."""
    for i in range(len(placeholders)):
        if f"@@PH{i}@@" not in translated:
            return False
    return True


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, max_size: int) -> List[str]:
    """
    Split *text* into chunks no larger than *max_size* characters,
    splitting on paragraph boundaries where possible.
    """
    if len(text) <= max_size:
        return [text]

    # Try paragraph splits first
    paragraphs = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_size:
            current = (current + "\n\n" + para).lstrip("\n")
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_size:
                current = para
            else:
                # Split oversized paragraph by sentence
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_size:
                        current = (current + " " + sent).lstrip()
                    else:
                        if current:
                            chunks.append(current)
                        current = sent[:max_size]
    if current:
        chunks.append(current)
    return chunks or [text[:max_size]]


# ---------------------------------------------------------------------------
# Translation cache (SQLite)
# ---------------------------------------------------------------------------

class TranslationCache:
    def __init__(self, cache_path: Path) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(cache_path), check_same_thread=False)
        self._init()

    def _init(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT NOT NULL UNIQUE,
                source     TEXT NOT NULL,
                translation TEXT NOT NULL,
                language   TEXT NOT NULL,
                model      TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_key ON cache(key)")
        self.conn.commit()

    def _make_key(self, text: str, language: str, model: str) -> str:
        return hash_text(text + "|" + language + "|" + model)

    def get(self, text: str, language: str, model: str) -> Optional[str]:
        key = self._make_key(text, language, model)
        row = self.conn.execute(
            "SELECT translation FROM cache WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def put(self, text: str, translation: str, language: str, model: str) -> None:
        key = self._make_key(text, language, model)
        self.conn.execute(
            """INSERT OR REPLACE INTO cache
               (key, source, translation, language, model, created_at)
               VALUES (?,?,?,?,?,?)""",
            (key, text, translation, language, model, datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# Ollama HTTP client
# ---------------------------------------------------------------------------

def _build_prompt(text: str, language: str) -> str:
    return (
        f"Translate the following video game text into {language}.\n"
        "Rules:\n"
        "1. Preserve all @@PHn@@ tokens exactly as-is.\n"
        "2. Preserve formatting, line breaks, and indentation.\n"
        "3. Output ONLY the translated text, no commentary.\n"
        "4. Do not add or remove any @@PHn@@ tokens.\n\n"
        f"TEXT:\n{text}"
    )


def _wait_for_server(endpoint: str, max_wait: int = 600, poll: int = 30) -> None:
    """
    Block until Ollama endpoint is reachable again, or max_wait seconds pass.
    Polls every `poll` seconds and logs status.
    """
    import re as _re
    base = _re.sub(r"/api/.*$", "", endpoint)
    deadline = time.time() + max_wait
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = requests.get(f"{base}/api/tags", timeout=5)
            if r.status_code == 200:
                _LOG.info("Ollama sunucusu tekrar erişilebilir — devam ediliyor.")
                return
        except Exception:
            pass
        remaining = int(deadline - time.time())
        _LOG.warning("Ollama bekleniyor (%d/%ds, %dds'de tekrar deneniyor)…",
                     attempt * poll, max_wait, poll)
        time.sleep(poll)
    _LOG.error("Ollama %ds içinde geri gelmedi — bu chunk atlanacak.", max_wait)


def translate_chunk(
    text: str,
    config: dict,
    cache: TranslationCache,
    retry_count: int = 3,
    retry_delay: float = 5.0,
) -> Optional[str]:
    """
    Translate a single text chunk via Ollama.
    Returns the translation, or None on failure.
    """
    language = config["translation_language"]
    model = config["translation_model"]
    endpoint = config["translation_endpoint"]
    timeout = config.get("request_timeout", 120)

    # Check cache first
    cached = cache.get(text, language, model)
    if cached is not None:
        _LOG.debug("Cache hit (len=%d)", len(text))
        return cached

    modified_text, placeholders = _preserve_placeholders(text)
    prompt = _build_prompt(modified_text, language)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }

    last_error: Optional[str] = None
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            try:
                result = resp.json()
            except ValueError as json_exc:
                raise ValueError(
                    f"Non-JSON response from server: {resp.text[:200]}"
                ) from json_exc
            translated_modified = result.get("response", "").strip()

            if not translated_modified:
                raise ValueError("Empty response from translation server")

            if placeholders and not _verify_placeholders(modified_text, translated_modified, placeholders):
                _LOG.warning(
                    "Placeholder mismatch in translation (attempt %d/%d); retrying …",
                    attempt, retry_count,
                )
                last_error = "placeholder mismatch"
                time.sleep(retry_delay)
                continue

            translated = _restore_placeholders(translated_modified, placeholders)
            cache.put(text, translated, language, model)
            return translated

        except requests.exceptions.ConnectionError as exc:
            last_error = f"connection error: {exc}"
            _LOG.warning("Translation request failed (attempt %d/%d): %s", attempt, retry_count, exc)
            # Network unreachable — wait for server to come back (up to 10 min)
            if "unreachable" in str(exc).lower() or "refused" in str(exc).lower():
                _LOG.warning("Ollama sunucusu erişilemiyor — 60sn bekleyip yeniden deneniyor…")
                _wait_for_server(endpoint, max_wait=600)
            # connection errors always retry (no limit)
            continue
        except requests.exceptions.Timeout:
            last_error = "request timed out"
            _LOG.warning("Translation timed out (attempt %d)", attempt)
        except requests.exceptions.HTTPError as exc:
            last_error = f"HTTP {exc.response.status_code}"
            _LOG.error("Translation HTTP error: %s", exc)
            break  # Don't retry HTTP errors
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            _LOG.error("Unexpected translation error: %s", exc)
            if attempt >= retry_count:
                break

        if attempt < retry_count:
            wait = retry_delay * min(attempt, 5)  # max 5x delay
            _LOG.info("Waiting %.0fs before retry …", wait)
            time.sleep(wait)

    _LOG.error("Translation failed after %d attempts: %s", attempt, last_error)
    return None


# ---------------------------------------------------------------------------
# File-level translation
# ---------------------------------------------------------------------------

def translate_manifest(
    manifest_path: Path,
    translated_path: Path,
    config: dict,
    cache: TranslationCache,
) -> bool:
    """
    Translate all entries in a JSON text manifest.
    Writes the translated manifest to *translated_path*.
    Returns True on success (even if some entries failed).
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _LOG.error("Cannot read manifest %s: %s", manifest_path, exc)
        return False

    entries = manifest.get("entries", [])
    max_chunk = config.get("max_chunk_size", 2000)
    retry_count = config.get("retry_count", 3)
    retry_delay = config.get("retry_delay", 5)
    ok_count = 0

    translated_entries = []
    for entry in entries:
        original_text = entry.get("text", "")
        if not original_text.strip():
            translated_entries.append(entry)
            continue

        # Chunk large entries
        chunks = chunk_text(original_text, max_chunk)
        translated_chunks = []
        all_ok = True

        for chunk in chunks:
            result = translate_chunk(chunk, config, cache, retry_count, retry_delay)
            if result is None:
                translated_chunks.append(chunk)  # Keep original on failure
                all_ok = False
            else:
                translated_chunks.append(result)

        if all_ok:
            ok_count += 1

        translated_entry = dict(entry)
        translated_entry["text"] = "\n\n".join(translated_chunks) if len(chunks) > 1 else translated_chunks[0]
        translated_entries.append(translated_entry)

    result_manifest = dict(manifest)
    result_manifest["entries"] = translated_entries
    result_manifest["translation_language"] = config["translation_language"]
    result_manifest["translation_model"] = config["translation_model"]

    translated_path.parent.mkdir(parents=True, exist_ok=True)
    translated_path.write_text(
        json.dumps(result_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _LOG.debug(
        "Translated %d/%d entries: %s", ok_count, len(entries), manifest_path.name
    )
    return True


# ---------------------------------------------------------------------------
# Batch translation
# ---------------------------------------------------------------------------

def translate_all(
    text_dir: Path,
    translated_dir: Path,
    game_name: str,
    config: dict,
    logger: Optional[logging.Logger] = None,
) -> int:
    """
    Phase 5 entry point. Translate all manifests in text/<game_name>/.
    Returns number of successfully translated files.
    """
    global _LOG
    if logger:
        _LOG = logger.getChild("translator")

    from .utils import ROOT_DIR
    cache_path = ROOT_DIR / "translated" / ".cache.db"
    cache = TranslationCache(cache_path)

    game_text_dir = text_dir / game_name
    game_translated_dir = translated_dir / game_name
    game_translated_dir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(game_text_dir.glob("*.json"))
    if not manifests:
        _LOG.warning("No text manifests found in %s", game_text_dir)
        cache.close()
        return 0

    _LOG.info("Translating %d manifest(s) to %s …", len(manifests), config["translation_language"])
    success = 0
    for i, mpath in enumerate(manifests):
        print_progress(i, len(manifests), prefix="Translating: ")
        out_path = game_translated_dir / mpath.name

        # Skip if already translated
        if out_path.exists():
            _LOG.debug("Already translated: %s", mpath.name)
            success += 1
            continue

        ok = translate_manifest(mpath, out_path, config, cache)
        if ok:
            success += 1

    print_progress(len(manifests), len(manifests), prefix="Translating: ")
    _LOG.info("Translation complete: %d/%d files", success, len(manifests))
    cache.close()
    return success
