# 🎮 SWITCH-GAME-YAMA-AUTO

**Nintendo Switch oyunlarını tamamen otomatik olarak Türkçeye çeviren pipeline.**  
NSP/XCI dosyasını al → metinleri çıkar → yerel AI ile çevir → Atmosphere yaması oluştur → SD karta koy. Bitti.

![Pipeline Screenshot](screenshot/Screenshot%202026-03-13%20075453.png)

---

## ✨ Özellikler

- 🔄 **Tam otomatik** — tek komutla tüm aşamalar çalışır
- 🧠 **Yerel AI çevirisi** — Ollama + `qwen2.5:14b` (internet bağlantısı gerekmez)
- 💾 **Akıllı cache** — çevrilen stringler SQLite'da saklanır, tekrar çevrilmez; kaldığı yerden devam eder
- 🔤 **Placeholder koruması** — `{değişken}`, `%s`, `\n`, `<tag>` gibi oyun kodları asla bozulmaz
- 📦 **Atmosphere LayeredFS** çıktısı — doğrudan SD karta kopyalanmaya hazır
- 📊 **Canlı terminal UI** — `monitor.py` ile gerçek zamanlı ilerleme takibi
- ▶️ **Kesintisiz devam** — `--skip-extract` ile durdurulduğu yerden devam eder

---

## 📋 Gereksinimler

| Gereksinim | Açıklama |
|-----------|----------|
| **Python 3.11+** | [python.org](https://www.python.org/downloads/) |
| **Ollama** | [ollama.ai](https://ollama.ai/) — lokalda çalışıyor olmalı |
| **Model** | `ollama pull qwen2.5:14b` |
| **hactool** | `hactool/hactool.exe` — [SciresM/hactool releases](https://github.com/SciresM/hactool/releases) |
| **Switch Keys** | `hactool/keys/prod.keys` + `hactool/keys/title.keys` — kendiniz temin edin |

---

## ⚙️ Kurulum

```powershell
git clone https://github.com/TolikMuradov/SWITCH-GAME-YAMA-AUTO.git
cd SWITCH-GAME-YAMA-AUTO

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Ollama modelini çek:
```bash
ollama pull qwen2.5:14b
```

`hactool.exe` binary'sini `hactool/` klasörüne, anahtarları `hactool/keys/` klasörüne koy.

---

## 🚀 Hızlı Başlangıç

1. NSP veya XCI dosyasını `input/` klasörüne koy
2. Pipeline'ı başlat:

```powershell
python pipeline.py
```

3. Yamayı bul ve SD karta kopyala:

```
build/game_translation_patch/atmosphere/  →  SD kart kökü
```

---

## 🛠️ CLI Seçenekleri

```
python pipeline.py [SEÇENEKLER]

  --input FILE        Oyun dosyasını doğrudan belirt (input/ taramasını atlar)
  --config FILE       Config dosyası (varsayılan: config/config.json)
  --language LANG     Çeviri dilini değiştir (varsayılan: Turkish)
  --skip-extract      Mevcut work/ klasörünü kullan, yeniden extract etme
  --skip-translate    Mevcut translated/ klasörünü kullan
  --zip               Yamayı ZIP olarak paketle
```

**Pipeline durdurulduğunda kaldığı yerden devam:**
```powershell
python pipeline.py --skip-extract
```

---

## 📊 İlerleme Takibi

Çeviri sırasında canlı UI:
```powershell
pip install rich
python monitor.py
```

Anlık durum raporu:
```powershell
python _check.py
```

---

## ⚙️ Konfigürasyon (`config/config.json`)

| Anahtar | Açıklama | Varsayılan |
|---------|----------|-----------|
| `translation_language` | Hedef dil | `"Turkish"` |
| `translation_endpoint` | Ollama API URL | `"http://127.0.0.1:11434/api/generate"` |
| `translation_model` | Ollama model adı | `"qwen2.5:14b"` |
| `max_chunk_size` | Maks karakter/istek | `2000` |
| `retry_count` | Hata sonrası tekrar | `3` |
| `retry_delay` | Tekrar bekleme (sn) | `5` |
| `request_timeout` | HTTP timeout (sn) | `120` |

---

## 🔄 Pipeline Aşamaları

```
Aşama 1+2  │  NSP/XCI tespit → NCA çıkar → Program NCA bul → RomFS çıkar
Aşama 3+4  │  RomFS tara → SARC aç → metinleri JSON manifest'e aktar
Aşama 5    │  Ollama ile çevir (cache + retry + placeholder koruması)
Aşama 6    │  Çevrilmiş metinlerden MSBT/SARC yeniden derle
Aşama 7    │  Atmosphere LayeredFS yaması oluştur
```

---

## 🗂️ Klasör Yapısı

```
SWITCH-GAME-YAMA-AUTO/
├── input/              ← .nsp / .xci buraya
├── work/               ← çıkarılmış NCA / RomFS (otomatik)
├── text/               ← kaynak metin JSON'ları (otomatik)
├── translated/         ← çevrilmiş JSON'lar + .cache.db (otomatik)
├── build/              ← final Atmosphere yaması (otomatik)
├── hactool/            ← hactool.exe + keys/
├── config/             ← config.json
├── src/                ← Python kaynak kodları
├── screenshot/         ← ekran görüntüleri
├── pipeline.py         ← ana pipeline
├── monitor.py          ← canlı terminal UI
├── _check.py           ← durum raporu
└── _reset.py           ← sıfırlama aracı
```

---

## 📝 Desteklenen Formatlar

| Format | Okuma | Yeniden Derleme |
|--------|-------|----------------|
| MSBT | ✅ | ✅ |
| JSON | ✅ | ✅ |
| CSV | ✅ | ✅ |
| XML | ✅ | ✅ |
| TXT / YAML | ✅ | ✅ |
| SARC / SZS | ✅ | ✅ |
| Binary strings | ✅ | ❌ (analiz amaçlı) |

---

## ⚠️ Önemli Notlar

- Switch anahtarları (`prod.keys`, `title.keys`) bu repoda **yer almaz** — kendiniz temin etmelisiniz
- Yalnızca **yasal olarak sahip olduğunuz** oyunlarda kullanın
- Bilgisayar uyku moduna girerse pipeline durur — güç ayarlarında uyku modunu kapatın
- Pipeline **idempotent**: tekrar çalıştırmak güvenli, tamamlanan aşamalar atlanır

---

## 📄 Lisans

Kişisel ve eğitim amaçlı kullanım için tasarlanmıştır.

