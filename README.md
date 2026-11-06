# AI Text Generator for Adobe After Effects

A lightweight, modular, and beginner-friendly automation tool that transcribes spoken audio, groups words into natural caption phrases using AI, and generates precisely synchronized, editable text layers inside Adobe After Effects.

---

## ⚡ Fitur Utama: Work Area Timeline Automation (B & N)

Anda dapat menandai bagian tertentu di timeline After Effects dan langsung membuat caption secara otomatis:

1. Di timeline After Effects, tandai kalimat dengan tombol **`B`** (awal) dan **`N`** (akhir).
2. Klik tombol **`🎬 Render Work Area & Generate Captions`** di Web UI atau jalankan script **`Auto_Caption_Work_Area.jsx`**.
3. Sistem otomatis:
   * Merender audio murni hanya pada area yang ditandai (1–2 detik).
   * Mengirim audio ke ElevenLabs Scribe STT.
   * Mengelompokkan kata (Single Word / Short / Long) dengan OpenAI / Heuristik.
   * Menambahkan offset waktu sehingga teks muncul **persis di posisi Work Area** yang Anda tandai di timeline!

---

## 🎯 Caption Grouping Modes

| Mode | Target Words | Normal Tolerance | Best Used For |
| :--- | :---: | :---: | :--- |
| **`Single Word`** | Exactly 1 | 1 word | High-energy social clips (TikTok, Reels, Shorts) where text pops word-by-word. |
| **`Short`** *(Default)* | 2–3 words | 1–4 words | Punchy, modern conversational pacing; easy to read without cluttering the screen. |
| **`Long`** | 4–5 words | 2–7 words | Traditional subtitles, educational videos, and full sentence phrases. |

---

## 🚀 3 Cara Menggunakan

### Cara 1: Menggunakan Web UI (Paling Direkomendasikan & Visual)
```bash
python3 ui.py
```
1. Di After Effects, tandai bagian bicara dengan **B** dan **N**.
2. Di browser, klik tombol oranye: **"🎬 Render Work Area dari After Effects & Generate Captions"**.
3. Selesai! Caption langsung tercipta di timeline After Effects Anda secara otomatis.

---

### Cara 2: Langsung dari Dalam Adobe After Effects
1. Di After Effects, tandai area dengan **B** dan **N**.
2. Klik menu: **File > Scripts > Run Script File...**
3. Pilih [`Auto_Caption_Work_Area.jsx`](file:///Users/alfonrenaldo/Documents/antigravity/AE%20text%20automation%20plugins/Auto_Caption_Work_Area.jsx).
4. Pilih mode grouping pada dialog pop-up, dan klik **Generate Captions**.

---

### Cara 3: Menggunakan Terminal Langsung
Otomatis Work Area dari After Effects:
```bash
python3 main.py --workarea --mode single
```

Atau memproses file audio/video dari Finder:
```bash
python3 main.py --input "/path/ke/audio.mp3" --mode short
```

---

## 📁 Struktur File Bersih (Clean Architecture)

```text
📁 AE text automation plugins/
├── 📄 AI_Text_Generator.jsx            # Panel After Effects utama (Dockable ScriptUI)
├── 📄 CARA_PAKAI_EDITOR.txt            # Panduan ringkas siap baca untuk video editor
├── 📦 AI_Text_Generator_for_Editor.zip # Paket ZIP siap kirim ke editor
├── 📄 README.md                        # Dokumentasi teknis proyek
└── 📁 core/                            # Subfolder internal (mesin di balik layar)
    ├── 📄 .env                         # Konfigurasi & Kunci API
    ├── 📄 main.py                      # Orkestrator CLI backend
    ├── 📄 config.py                    # Zero-dependency config loader
    ├── 📄 stt_service.py               # ElevenLabs Scribe STT
    ├── 📄 grouping_rules.py            # Aturan Kinetic Typography
    ├── 📄 grouping_service.py          # Chunking & Gap Bridging
    ├── 📄 translation_service.py       # OpenAI Chunk-by-chunk translation
    ├── 📄 web_ui.py                    # Web browser UI server
    ├── 📄 test_suite.py                # 23 automated unit tests
    └── 📁 output/                      # File output JSON & SRT
```
