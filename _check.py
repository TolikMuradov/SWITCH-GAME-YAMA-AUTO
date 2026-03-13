#!/usr/bin/env python3
import sqlite3, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
db = ROOT / "translated" / ".cache.db"
text_dir = ROOT / "text" / "Hades [0100535012974000][v0]"
translated_dir = ROOT / "translated" / "Hades [0100535012974000][v0]"
build_dir = ROOT / "build"
patch_dir = ROOT / "build" / "game_translation_patch"

# cache
conn = sqlite3.connect(str(db))
cache_count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
last = conn.execute("SELECT created_at, source FROM cache ORDER BY id DESC LIMIT 1").fetchone()
errors_db = conn.execute("SELECT COUNT(*) FROM cache WHERE translation=''").fetchone()[0]
conn.close()

# text
text_files = list(text_dir.glob("*.json")) if text_dir.exists() else []
total_entries = 0
for f in text_files:
    try:
        total_entries += len(json.loads(f.read_bytes()).get("entries", []))
    except Exception:
        pass

# translated
trans_files = list(translated_dir.glob("*.json")) if translated_dir.exists() else []

# build / patch
build_files = sum(1 for _ in build_dir.rglob("*") if _.is_file()) if build_dir.exists() else 0
patch_files = sum(1 for _ in patch_dir.rglob("*") if _.is_file()) if patch_dir.exists() else 0

# log
logs = sorted(Path(ROOT / "logs").glob("pipeline_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
log_path = logs[0] if logs else None
log_errors = 0
log_complete = False
log_last_line = ""
if log_path:
    lines = log_path.read_text(errors="replace").splitlines()
    log_errors = sum(1 for l in lines if "[ERROR" in l)
    log_complete = any("Pipeline Complete" in l or "Elapsed time" in l for l in lines)
    log_last_line = lines[-1] if lines else ""

pct = 100 * cache_count // total_entries if total_entries else 0

print("=" * 60)
print("  SWITCH TRANSLATOR — DURUM RAPORU")
print("=" * 60)
print(f"  Log           : {log_path.name if log_path else 'bulunamadı'}")
print(f"  Tamamlandı mı : {'✅ EVET' if log_complete else '⏳ DEVAM EDİYOR / DURDU'}")
print(f"  Log hatalar   : {log_errors} adet [ERROR] satırı")
print()
print(f"  TEXT dosyaları: {len(text_files)} json  ({total_entries:,} toplam giriş)")
print(f"  CACHE girişleri: {cache_count:,}  ({pct}% tamamlandı)")
print(f"  TRANSLATED dir: {len(trans_files)} json dosyası")
print(f"  BUILD dosyaları: {build_files}")
print(f"  PATCH dosyaları: {patch_files}  (klasör: {'var' if patch_dir.exists() else 'YOK'})")
print()
print(f"  Son cache girişi: {last[0] if last else 'yok'}")
print(f"  Son cache metni : {str(last[1])[:80] if last else 'yok'}")
print()
print(f"  Log son satır  : {log_last_line[-100:]}")
print("=" * 60)
