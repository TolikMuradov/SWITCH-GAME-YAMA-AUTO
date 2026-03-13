#!/usr/bin/env python3
"""
monitor.py — Switch Translator Gelişmiş Terminal UI
=====================================================
Kullanım:
    python monitor.py [--refresh N]   # N = saniye (varsayılan 4)

Özellikler:
  • Canlı progress bar (dosya + giriş bazlı)
  • Aşama takibi (Phase 1-7)
  • ETA hesaplaması (kayan ortalama)
  • Hata & uyarı sayacı
  • Son aktivite akışı
  • Crash / durma tespiti (log yaşına göre)
  • Ollama bağlantı durumu
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
CACHE_DB = ROOT / "translated" / ".cache.db"

try:
    import requests as _req_lib
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from rich.columns import Columns
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Eksik kütüphane: pip install rich requests")
    sys.exit(1)

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────────────────────

PHASE_MARKERS = [
    ("extractor",   1, "Aşama 1-2",  "Çıkarma (Extraction)"),
    ("scanner",     2, "Aşama 3-4",  "Tarama & Metin Aktarımı"),
    ("translator",  3, "Aşama 5",    "Çeviri (Translation)"),
    ("rebuilder",   4, "Aşama 6",    "Yeniden Derleme (Rebuild)"),
    ("patcher",     5, "Aşama 7",    "Yama Oluşturma (Patch)"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Veri toplama fonksiyonları
# ─────────────────────────────────────────────────────────────────────────────

def find_game_name() -> Optional[str]:
    for d in sorted((ROOT / "text").iterdir()) if (ROOT / "text").exists() else []:
        if d.is_dir() and any(d.glob("*.json")):
            return d.name
    return None


def find_latest_log() -> Optional[Path]:
    logs_dir = ROOT / "logs"
    if not logs_dir.exists():
        return None
    logs = sorted(logs_dir.glob("pipeline_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def get_text_stats(game_name: str) -> tuple[int, int]:
    """(dosya_sayısı, toplam_giriş) — ilk yüklemede hesaplanır."""
    text_dir = ROOT / "text" / game_name
    if not text_dir.exists():
        return 0, 0
    files, entries = 0, 0
    for f in text_dir.glob("*.json"):
        try:
            files += 1
            entries += len(json.loads(f.read_bytes()).get("entries", []))
        except Exception:
            pass
    return files, entries


def get_cache_count() -> int:
    if not CACHE_DB.exists():
        return 0
    try:
        c = sqlite3.connect(str(CACHE_DB), timeout=1)
        n = c.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        c.close()
        return n
    except Exception:
        return 0


def get_translated_file_count(game_name: str) -> int:
    d = ROOT / "translated" / game_name
    return sum(1 for _ in d.glob("*.json")) if d.exists() else 0


def get_build_stats() -> tuple[int, int]:
    """(build dosyaları, patch dosyaları)"""
    build_dir = ROOT / "build"
    patch_dir = ROOT / "build" / "game_translation_patch"
    build = sum(1 for _ in build_dir.rglob("*") if _.is_file()) if build_dir.exists() else 0
    patch = sum(1 for _ in patch_dir.rglob("*") if _.is_file()) if patch_dir.exists() else 0
    return build, patch


def parse_log(log_path: Path) -> dict:
    """Log dosyasını parse et, özet bilgileri döndür."""
    result = {
        "current_phase_num": 0,
        "current_phase_label": "Başlatılıyor…",
        "current_phase_detail": "",
        "is_complete": False,
        "is_crashed": False,
        "error_count": 0,
        "warning_count": 0,
        "recent_lines": [],      # [(ts, msg, style)]
        "error_lines": [],       # [(msg, style)]
        "last_activity_ts": None,
        "log_age_secs": 0,
    }
    try:
        txt = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return result

    lines = txt.splitlines()
    result["log_age_secs"] = time.time() - log_path.stat().st_mtime

    for line in lines:
        low = line.lower()
        for module, num, label, detail in PHASE_MARKERS:
            if f"switch_translator.{module}" in low or f"switch_translator.{module}" in line:
                if num > result["current_phase_num"]:
                    result["current_phase_num"] = num
                    result["current_phase_label"] = label
                    result["current_phase_detail"] = detail
        if "[error" in low:
            result["error_count"] += 1
            msg = line.split("] ", 2)[-1].strip()
            result["error_lines"].append((msg[-120:], "bold red"))
        elif "[warning" in low or "[warn" in low:
            result["warning_count"] += 1
            msg = line.split("] ", 2)[-1].strip()
            result["error_lines"].append((msg[-120:], "yellow"))

    # Pipeline tamamlandı mı?
    if any("Pipeline Complete" in l or "Elapsed time" in l for l in lines):
        result["is_complete"] = True
        result["current_phase_label"] = "Tamamlandı"
        result["current_phase_detail"] = "Tüm aşamalar başarıyla bitti"

    # Son aktivite zaman damgası
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    for line in reversed(lines[-200:]):
        m = ts_re.match(line)
        if m:
            try:
                result["last_activity_ts"] = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            break

    # Son 10 önemli satır
    recent: list = []
    for line in reversed(lines[-2000:]):
        if "[info" in line.lower() or "[error" in line.lower() or "[warning" in line.lower():
            ts_part = line[:19]
            msg = line.split("] ", 2)[-1].strip()
            style = "bold red" if "[error" in line.lower() else ("yellow" if "[warning" in line.lower() else "dim white")
            recent.append((ts_part[-8:], msg[:115], style))
            if len(recent) >= 10:
                break
    result["recent_lines"] = list(reversed(recent))

    # Crash tespiti: log 10+ dakika yaşlıysa ve bitmemişse
    if not result["is_complete"] and result["log_age_secs"] > 600:
        result["is_crashed"] = True

    return result


def check_ollama(endpoint: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Ollama sunucusuna bağlanabilir miyiz?"""
    if not _REQUESTS_OK:
        return False, "requests kurulu değil"
    # endpoint: http://host:port/api/generate → http://host:port
    base = re.sub(r"/api/.*$", "", endpoint)
    try:
        r = _req_lib.get(f"{base}/api/tags", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            return True, f"{len(models)} model yüklü"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)[:60]


def load_config() -> dict:
    cfg_path = ROOT / "config" / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception:
            pass
    return {}

# ─────────────────────────────────────────────────────────────────────────────
# ETA Hesaplayıcı
# ─────────────────────────────────────────────────────────────────────────────

class ETACalc:
    def __init__(self) -> None:
        self._samples: list[tuple[float, int]] = []

    def update(self, done: int, total: int) -> str:
        remaining = max(total - done, 0)
        if remaining == 0:
            return "Tamamlandı 🎉"
        now = time.monotonic()
        self._samples.append((now, done))
        if len(self._samples) > 40:
            self._samples.pop(0)
        if len(self._samples) < 2:
            return "hesaplanıyor…"
        t0, d0 = self._samples[0]
        t1, d1 = self._samples[-1]
        dt, dd = t1 - t0, d1 - d0
        if dt <= 0 or dd <= 0:
            return "hesaplanıyor…"
        secs = remaining * (dt / dd)
        td = timedelta(seconds=int(secs))
        h, remainder = divmod(td.seconds + td.days * 86400, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"~{h}s {m}dk"
        elif m > 0:
            return f"~{m}dk {s}s"
        else:
            return f"~{s}sn"

# ─────────────────────────────────────────────────────────────────────────────
# UI oluşturucu
# ─────────────────────────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 28) -> str:
    if total == 0:
        return f"[{'─' * width}]  —"
    pct = min(done / total, 1.0)
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]  {done:,}/{total:,}  ({pct * 100:.1f}%)"


def _phase_progress(current: int) -> Text:
    phases = [
        (1, "Ext"),
        (2, "Scan"),
        (3, "Çeviri"),
        (4, "Rebuild"),
        (5, "Patch"),
    ]
    t = Text()
    for num, label in phases:
        if num < current:
            t.append(f" ✅{label} ", style="green")
        elif num == current:
            t.append(f" ▶{label} ", style="bold cyan")
        else:
            t.append(f" ·{label} ", style="dim")
        if num < len(phases):
            t.append("→", style="dim")
    return t


class MonitorUI:
    def __init__(self, game_name: str, config: dict) -> None:
        self.game_name = game_name
        self.config = config
        self.endpoint = config.get("translation_endpoint", "")
        self.model = config.get("translation_model", "?")
        self.target_lang = config.get("translation_language", "?")
        self.monitor_start = time.monotonic()
        self.eta_calc = ETACalc()
        self._ollama_ok: Optional[bool] = None
        self._ollama_msg: str = "kontrol ediliyor…"
        self._last_ollama_check = 0.0
        # Pre-load text stats (slow op — only once)
        console.print("[cyan]  Manifest dosyaları sayılıyor…[/cyan]", end="\r")
        self.total_files, self.total_entries = get_text_stats(game_name)
        console.print(f"[green]  {self.total_files} dosya,  {self.total_entries:,} giriş bulundu.[/green]")

    def _check_ollama(self) -> None:
        now = time.time()
        if now - self._last_ollama_check < 15:
            return
        self._last_ollama_check = now
        ok, msg = check_ollama(self.endpoint)
        self._ollama_ok, self._ollama_msg = ok, msg

    def render(self) -> Panel:
        self._check_ollama()

        log_path = find_latest_log()
        log_info = parse_log(log_path) if log_path else {}

        cached = get_cache_count()
        trans_files = get_translated_file_count(self.game_name)
        build_files, patch_files = get_build_stats()

        is_complete = log_info.get("is_complete", False)
        is_crashed = log_info.get("is_crashed", False)
        error_count = log_info.get("error_count", 0)
        warn_count = log_info.get("warning_count", 0)
        log_age = log_info.get("log_age_secs", 0)
        phase_num = log_info.get("current_phase_num", 0)
        phase_label = log_info.get("current_phase_label", "—")
        phase_detail = log_info.get("current_phase_detail", "")
        last_ts = log_info.get("last_activity_ts")
        recent = log_info.get("recent_lines", [])
        errors = log_info.get("error_lines", [])

        eta = self.eta_calc.update(cached, self.total_entries)

        elapsed_s = time.monotonic() - self.monitor_start
        h, r = divmod(int(elapsed_s), 3600)
        m_el, s_el = divmod(r, 60)
        uptime = f"{h:02d}:{m_el:02d}:{s_el:02d}"

        # Durum belirleme
        if is_complete:
            status_str = "✅  TAMAMLANDI"
            status_style = "bold green"
            status_icon = "🎉"
        elif is_crashed:
            status_str = "💥  CRASH / DURDU"
            status_style = "bold red"
            status_icon = "💥"
        elif log_age > 300:
            status_str = "⏳  YAVAŞ / OLLAMA BEKLİYOR"
            status_style = "yellow"
            status_icon = "⏳"
        elif log_path:
            status_str = "● ÇALIŞIYOR"
            status_style = "bold green"
            status_icon = "▶"
        else:
            status_str = "○  BAŞLATILMADI"
            status_style = "dim white"
            status_icon = "○"

        # ── Grid oluştur ──
        grid = Table.grid(padding=(0, 0))
        grid.add_column(min_width=72)

        def row(t=""):
            if isinstance(t, str):
                t = Text(t)
            grid.add_row(t)

        # ── Başlık ──
        title_t = Text()
        title_t.append(f"  🎮  {self.game_name}\n", style="bold white")

        row(title_t)
        row(Rule(style="blue"))

        # ── Durum + Ollama ──
        st = Text()
        st.append("  Durum   : ", style="bold white")
        st.append(status_str, style=status_style)
        st.append(f"   (izleme: {uptime})", style="dim")
        row(st)

        ph = Text()
        ph.append("  Aşama   : ", style="bold white")
        if phase_num:
            ph.append(f"{phase_label} — ", style="bold cyan")
            ph.append(phase_detail, style="cyan")
        else:
            ph.append("—", style="dim")
        row(ph)

        # Phase progress bar
        row()
        pp = Text("  ")
        pp.append_text(_phase_progress(phase_num))
        row(pp)
        row()

        # Ollama
        oll = Text()
        oll.append("  Ollama  : ", style="bold white")
        if self._ollama_ok is None:
            oll.append("kontrol ediliyor…", style="dim")
        elif self._ollama_ok:
            oll.append(f"● BAĞLI  {self._ollama_msg}", style="green")
        else:
            oll.append(f"✗ BAĞLANAMADI  {self._ollama_msg}", style="bold red")
        oll.append(f"   model: {self.model}", style="dim")
        row(oll)

        row(Text())
        row(Rule(title="İLERLEME", style="yellow"))

        # Progress bars
        row(Text(f"  Giriş (cache)   : {_bar(cached, self.total_entries)}"))
        row(Text(f"  Çevrilen dosya  : {_bar(trans_files, self.total_files)}"))
        row(Text(f"  Build dosyaları : {build_files:,}   Patch dosyaları: {patch_files:,}"))
        row()

        eta_t = Text()
        eta_t.append("  Tahmini kalan  : ", style="dim")
        eta_t.append(eta, style="bold white")

        if last_ts:
            ago = int((datetime.now() - last_ts).total_seconds())
            if ago > 60:
                eta_t.append(f"       Son aktivite: {ago // 60}dk {ago % 60}sn önce", style="dim")
            else:
                eta_t.append(f"       Son aktivite: {ago}sn önce", style="dim green")
        row(eta_t)

        row(Text())
        row(Rule(title="SON AKTİVİTE", style="yellow"))

        if recent:
            for ts, msg, style in recent:
                a = Text()
                a.append(f"  {ts}  ", style="dim")
                a.append(msg, style=style)
                row(a)
        else:
            row(Text("  (henüz aktivite yok)", style="dim"))

        row(Text())

        # Hatalar
        if errors:
            row(Rule(title=f"HATALAR / UYARILAR  ({error_count}🔴  {warn_count}🟡)", style="red"))
            for msg, style in errors[-8:]:
                row(Text(f"  {msg}", style=style))
        else:
            row(Rule(title="HATALAR / UYARILAR  (temiz ✅)", style="green"))
            row(Text("  Hata yok", style="green"))

        row(Text())
        row(Rule(style="blue"))

        cfg_t = Text()
        cfg_t.append(f"  Hedef: {self.target_lang}", style="dim")
        cfg_t.append("  │  ", style="dim")
        cfg_t.append(f"Log: {log_path.name if log_path else '—'}", style="dim")
        cfg_t.append("  │  ", style="dim")
        cfg_t.append(f"Hata: {error_count}", style="dim red" if error_count else "dim")
        row(cfg_t)

        return Panel(
            grid,
            title=f"[bold blue]Switch Translator — Canlı İzleme[/bold blue]   {datetime.now().strftime('%H:%M:%S')}",
            subtitle="[dim]Çıkmak için Ctrl+C   │   --refresh N ile yenileme hızını ayarla[/dim]",
            border_style="blue",
            padding=(0, 1),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Ana döngü
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Switch Translator canlı izleme")
    ap.add_argument("--refresh", type=float, default=4.0, metavar="SANIYE",
                    help="Yenileme aralığı saniye (varsayılan: 4)")
    args = ap.parse_args()

    game_name = find_game_name()
    if not game_name:
        # text/ boşsa build/ veya work/'a bak
        for parent in ((ROOT / "work"), (ROOT / "build")):
            for d in (parent.iterdir() if parent.exists() else []):
                if d.is_dir():
                    game_name = d.name
                    break
            if game_name:
                break
    if not game_name:
        console.print("[red]Oyun bulunamadı — önce pipeline'ı başlat.[/red]")
        sys.exit(1)

    cfg = load_config()
    ui = MonitorUI(game_name, cfg)

    console.print()
    try:
        with Live(ui.render(), console=console, refresh_per_second=1, screen=True) as live:
            while True:
                time.sleep(args.refresh)
                live.update(ui.render())
    except KeyboardInterrupt:
        console.print("\n[cyan]İzleme durduruldu.[/cyan]")


if __name__ == "__main__":
    main()
