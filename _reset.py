#!/usr/bin/env python3
"""
_reset.py — Pipeline sıfırlama aracı
• text/ ve translated/ dizinlerini temizler
• cache'deki çöp kayıtları siler
• sadece gerçek oyun metni (Subtitles/en) kalır
Çalıştır: python3 _reset.py
"""
import sqlite3, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAME = "Hades [0100535012974000][v0]"
text_dir = ROOT / "text" / GAME
translated_dir = ROOT / "translated" / GAME
db_path = ROOT / "translated" / ".cache.db"

print("=" * 55)
print("  PIPELINE SIFIRLAMA")
print("=" * 55)

# 1. text/ temizle
if text_dir.exists():
    files = list(text_dir.glob("*.json"))
    print(f"  text/ klasöründe {len(files)} dosya siliniyor…")
    shutil.rmtree(text_dir)
    text_dir.mkdir(parents=True)
    print("  text/ temizlendi ✅")
else:
    print("  text/ zaten boş")

# 2. translated/ temizle
if translated_dir.exists():
    files = list(translated_dir.glob("*.json"))
    print(f"  translated/ klasöründe {len(files)} dosya siliniyor…")
    shutil.rmtree(translated_dir)
    translated_dir.mkdir(parents=True)
    print("  translated/ temizlendi ✅")
else:
    print("  translated/ zaten boş")

# 3. cache temizle (tüm kayıtlar çöpten geldiğinden hepsini sil)
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    before = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    conn.execute("DELETE FROM cache")
    conn.commit()
    conn.close()
    print(f"  Cache {before} kayıt silindi → 0 ✅")
else:
    print("  Cache DB bulunamadı")

print()
print("  Hazır! Şimdi pipeline'ı yeniden çalıştırabilirsin.")
print("  Komut:")
print("  source venv/bin/activate")
print("  python pipeline.py --skip-extract")
print("=" * 55)
