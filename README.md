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

# switch-translator

Automated Nintendo Switch game translation pipeline for macOS.

Translates game text using a remote Ollama server and produces an
Atmosphere LayeredFS patch ready to deploy on a modded console.

---

## Requirements

- macOS with Python 3.11+
- Remote PC running [Ollama](https://ollama.ai/) at `http://192.168.1.115:11434`
- Model pulled on the Ollama server: `qwen2.5:14b`
- Nintendo Switch keys (`prod.keys`, `title.keys`) in `~/.switch/`

### External Tools (place in `tools/`)

| Tool | Purpose | Download |
|------|---------|----------|
| `hactool` | NSP/XCI/NCA/RomFS extraction | [SciresM/hactool](https://github.com/SciresM/hactool/releases) |
| `msbt_tool` *(optional)* | MSBT export/import | various Switch tools |
| `sarc_tool` *(optional)* | SARC archive extract/repack | [aboood40091/SARC-Tool](https://github.com/aboood40091/SARC-Tool) |

Make downloaded tools executable:
```bash
chmod +x tools/hactool tools/msbt_tool tools/sarc_tool
```

---

## Installation

```bash
cd switch-translator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Quick Start

1. Place your game file in `input/`:
   ```
   input/game.nsp
   # or
   input/game.xci
   ```

2. Run the pipeline:
   ```bash
   python pipeline.py
   ```

3. Find your patch in:
   ```
   build/game_translation_patch/atmosphere/contents/<TitleID>/romfs/
   ```

4. Copy the `atmosphere/` folder to the root of your SD card.

---

## CLI Options

```
python pipeline.py [OPTIONS]

  --input FILE        Specify game file directly (bypass input/ scan)
  --config FILE       Config file (default: config/config.json)
  --language LANG     Override translation language
  --skip-extract      Reuse an existing extraction in work/
  --skip-translate    Reuse existing translations in translated/
  --zip               Package the patch as a ZIP archive
```

---

## Configuration (`config/config.json`)

| Key | Description | Default |
|-----|-------------|---------|
| `translation_language` | Target language | `"Turkish"` |
| `translation_endpoint` | Ollama API URL | `"http://192.168.1.115:11434/api/generate"` |
| `translation_model` | Ollama model name | `"qwen2.5:14b"` |
| `max_chunk_size` | Max chars per translation request | `2000` |
| `retry_count` | Retry attempts on failure | `3` |
| `retry_delay` | Seconds between retries | `5` |
| `request_timeout` | HTTP timeout in seconds | `120` |
| `keys_file` | Path to prod.keys | `"~/.switch/prod.keys"` |

---

## Pipeline Phases

```
Phase 1+2 │ Detect game file → Extract NSP/XCI → find Program NCA → extract RomFS
Phase 3+4 │ Scan RomFS → extract SARCs → export text to JSON manifests
Phase 5   │ Translate manifests via Ollama (with cache & retry)
Phase 6   │ Rebuild original file formats from translations
Phase 7   │ Assemble Atmosphere LayeredFS patch
```

---

## Directory Layout

```
switch-translator/
├── input/                  ← Drop .nsp / .xci here
├── work/                   ← Extraction workspace (auto-created)
│   └── <game>/
│       ├── nca/            ← Extracted NCA files
│       ├── romfs/          ← Extracted RomFS
│       └── exefs/          ← Extracted ExeFS
├── text/                   ← Exported text manifests (JSON)
│   └── <game>/
├── translated/             ← Translated manifests (JSON)
│   └── <game>/
├── build/                  ← Build output
│   ├── <game>/romfs/       ← Rebuilt modified files
│   └── game_translation_patch/
│       └── atmosphere/
│           └── contents/
│               └── <TitleID>/
│                   └── romfs/  ← Deploy to SD card
├── logs/                   ← Log files (timestamped)
├── tools/                  ← Place external tools here
├── src/                    ← Python source modules
└── config/config.json      ← Configuration
```

---

## Supported Formats

| Format | Export | Rebuild | Notes |
|--------|--------|---------|-------|
| MSBT | ✅ | ✅ | Built-in + msbt_tool |
| JSON | ✅ | ✅ | Key-path tracking |
| CSV | ✅ | ✅ | Cell-level |
| XML | ✅ | ✅ | Element text |
| TXT / YAML | ✅ | ✅ | Line-level |
| SARC / SZS | ✅ extract | ✅ repack* | *Requires sarc_tool |
| Binary | ✅ strings | ❌ | For analysis only |

---

## Translation Caching

Translations are cached in `translated/.cache.db` (SQLite).  
Re-running the pipeline skips already-translated entries.  
Delete the cache file to force full re-translation.

---

## Placeholder Preservation

The following are automatically protected and never sent to the AI:

- `{variable}` — named placeholders
- `%02d`, `%s`, etc. — printf format strings
- `<color=red>`, `</tag>` — markup tags
- `\n`, `\t`, `\r` — escape sequences
- `[[code]]` — bracket codes
- `~N`, `^A` — Nintendo control characters

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `hactool: not found` | Place hactool binary in `tools/` and run `chmod +x tools/hactool` |
| `Keys file not found` | Copy `prod.keys` to `~/.switch/prod.keys` |
| Connection refused | Ensure Ollama is running on the Windows PC at the configured IP |
| Empty RomFS | Game may use encrypted NCA — ensure keys are correct |
| No text files found | Game may store text in a non-standard format |

---

## Notes

- The pipeline is idempotent: re-running skips already-completed phases.
- Logs are saved to `logs/pipeline_<timestamp>.log`.
- The pipeline never crashes on a single file failure — errors are logged and processing continues.


---

## 📄 Lisans

Kişisel ve eğitim amaçlı kullanım için tasarlanmıştır.

