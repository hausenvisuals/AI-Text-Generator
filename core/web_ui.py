#!/usr/bin/env python3
"""Modern Local Web UI for AI Caption Generator for Adobe After Effects.

Two-Stage Decoupled Workflow:
Stage 1: Export Text (Render AE Work Area -> STT -> Kinetic Typography Chunking).
Review & Edit: View, modify phrasing, adjust start/end timestamps, and save before import.
Stage 2: Import Text (Language Selection: Original / Indonesian / English -> Direct AE Timeline Injection).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.parse
import uuid
import webbrowser

from config import config
from grouping_rules import GroupingMode
from grouping_service import CaptionGroup
from main import (
    export_captions,
    format_timestamp,
    generate_srt,
    import_captions_to_timeline,
    render_ae_workarea,
    trigger_ae_import,
)

PORT = 5055

HTML_CONTENT = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Caption Generator for Adobe After Effects</title>
  <style>
    :root {
      --bg: #0f1117;
      --card-bg: #1a1d27;
      --border: #2a2e3d;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --accent-light: rgba(99, 102, 241, 0.15);
      --ae-orange: #f97316;
      --ae-orange-hover: #ea580c;
      --success: #10b981;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 30px 20px;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
    }
    header {
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    h1 {
      font-size: 22px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .badge-container { display: flex; gap: 8px; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 600;
      background: var(--accent-light);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .badge.green {
      background: rgba(16, 185, 129, 0.15);
      color: #6ee7b7;
      border-color: rgba(16, 185, 129, 0.3);
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 22px;
      margin-bottom: 20px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    .card.stage1 {
      border: 1px solid rgba(249, 115, 22, 0.4);
      background: linear-gradient(180deg, #201e29 0%, #1a1d27 100%);
    }
    .card.preview {
      border: 1px solid rgba(16, 185, 129, 0.35);
      background: linear-gradient(180deg, #162420 0%, #1a1d27 100%);
    }
    .card.stage2 {
      border: 1px solid rgba(99, 102, 241, 0.4);
      background: linear-gradient(180deg, #191b2c 0%, #1a1d27 100%);
    }
    .card-title {
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card-desc {
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 16px;
    }
    .form-group {
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 8px;
      color: var(--text);
    }
    select {
      width: 100%;
      background: #13151f;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      color: var(--text);
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    select:focus { border-color: var(--accent); }
    .mode-desc {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 6px;
      font-style: italic;
    }
    .btn-export {
      background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
      color: white;
      border: none;
      padding: 14px 24px;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      box-shadow: 0 4px 14px rgba(249, 115, 22, 0.3);
    }
    .btn-export:hover {
      background: linear-gradient(135deg, #ea580c 0%, #c2410c 100%);
      transform: translateY(-1px);
    }
    .btn-export:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    
    .btn-import {
      background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
      color: white;
      border: none;
      padding: 14px 24px;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
    }
    .btn-import:hover {
      background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
      transform: translateY(-1px);
    }
    .btn-import:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

    .status-box {
      display: none;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 13px;
      margin-top: 14px;
    }
    .status-box.loading {
      display: flex;
      align-items: center;
      gap: 12px;
      background: var(--accent-light);
      color: #c7d2fe;
      border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .status-box.success {
      display: block;
      background: rgba(16, 185, 129, 0.15);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .status-box.error {
      display: block;
      background: rgba(239, 68, 68, 0.15);
      color: #fca5a5;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .spinner {
      width: 18px;
      height: 18px;
      border: 2px solid rgba(255, 255, 255, 0.3);
      border-radius: 50%;
      border-top-color: white;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .results-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 13px;
    }
    .results-table th, .results-table td {
      padding: 8px 10px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }
    .results-table th {
      color: var(--text-muted);
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      background: rgba(0, 0, 0, 0.2);
    }
    .results-table tr:hover { background: rgba(255, 255, 255, 0.02); }
    
    .edit-input {
      background: #13151f;
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.2s;
      width: 100%;
    }
    .edit-input:focus { border-color: var(--accent); }
    .time-input {
      width: 70px;
      text-align: center;
      font-family: monospace;
    }

    .btn-save-changes {
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: white;
      border: none;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn-save-changes:hover {
      background: linear-gradient(135deg, #059669 0%, #047857 100%);
      transform: translateY(-1px);
    }
    
    .btn-secondary {
      background: #272b38;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
    }
    .btn-secondary:hover { background: #353b4c; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🎬 AI Caption Generator <span style="font-size: 14px; color: var(--text-muted); font-weight: normal;">After Effects</span></h1>
      <div class="badge-container">
        <span class="badge green" id="el-status">ElevenLabs Ready ✓</span>
        <span class="badge green" id="llm-status">OpenAI Ready ✓</span>
      </div>
    </header>

    <!-- TAHAP 1: EXPORT CARD -->
    <div class="card stage1">
      <div class="card-title">🎬 1. EXPORT &amp; SUSUN TEKS DARI WORK AREA</div>
      <p class="card-desc">
        Tandai area bicara di timeline After Effects dengan shortcut <strong style="color: white;">B</strong> (awal) dan <strong style="color: white;">N</strong> (akhir), pilih susunan kata, lalu klik tombol di bawah untuk mengekstrak dan menyusun teks.
      </p>

      <div class="form-group">
        <label for="mode-select">Pilihan Susunan Kata (Kinetic Typography Mode):</label>
        <select id="mode-select" onchange="updateModeDesc()">
          <option value="Single Word">Single Word (1 kata per layer - Gaya TikTok/Reels cepat)</option>
          <option value="Short">Short (2–3 kata per subtitle - Punchy Kinetic Typography)</option>
          <option value="Long" selected>Long (3–5 kata per subtitle - Kinetic Typography Frasa Utuh)</option>
        </select>
        <div class="mode-desc" id="mode-desc">Ideal 3–5 kata per subtitle (maksimal 6 kata). Visual chunking frasa utuh, tanpa kata tunggal.</div>
      </div>

      <button class="btn-export" id="export-btn" onclick="executeExport()">
        🎬 1. Export &amp; Susun Teks dari Work Area
      </button>

      <div class="status-box" id="export-status-box"></div>
    </div>

    <!-- HASIL EXPORT: REVIEW & EDIT CARD -->
    <div class="card preview" id="results-card" style="display: none;">
      <div class="card-title" style="justify-content: space-between;">
        <span id="results-title">Hasil Export (Review &amp; Edit Subtitle)</span>
        <div style="display: flex; gap: 8px;">
          <button class="btn-save-changes" id="btn-save" onclick="saveTableChanges()">
            💾 Simpan Perubahan Teks &amp; Waktu
          </button>
          <button class="btn-secondary" onclick="openFolder()">📂 Folder Output</button>
        </div>
      </div>

      <p class="card-desc" style="margin-bottom: 10px;">
        Anda dapat mengubah susunan teks atau mengatur timing (start / end) langsung pada kolom di bawah sebelum melakukan import ke timeline After Effects.
      </p>

      <div style="max-height: 420px; overflow-y: auto;">
        <table class="results-table">
          <thead>
            <tr>
              <th width="45">#</th>
              <th width="90">Start (s)</th>
              <th width="90">End (s)</th>
              <th width="75">Durasi</th>
              <th>Teks Subtitle (Bisa Diedit Langsung)</th>
            </tr>
          </thead>
          <tbody id="results-body"></tbody>
        </table>
      </div>

      <div class="status-box" id="table-status-box"></div>
    </div>

    <!-- TAHAP 2: IMPORT CARD -->
    <div class="card stage2" id="import-card">
      <div class="card-title">🚀 2. IMPORT LANGSUNG KE TIMELINE AFTER EFFECTS</div>
      <p class="card-desc">
        Pilih bahasa subtitle. Jika memilih terjemahan, AI akan menerjemahkan per potongan (chunk-by-chunk) terlebih dahulu lalu <strong>langsung otomatis membuat text layer-nya di timeline After Effects</strong>.
      </p>

      <div class="form-group">
        <label for="lang-select">Pilihan Bahasa Subtitle:</label>
        <select id="lang-select">
          <option value="original" selected>Bahasa Asli / Original (Langsung Import Teks Asli / Hasil Edit)</option>
          <option value="id">Terjemahkan ke Bahasa Indonesia ➔ Langsung Buat Text Layer di AE</option>
          <option value="en">Terjemahkan ke Bahasa Inggris ➔ Langsung Buat Text Layer di AE</option>
        </select>
      </div>

      <button class="btn-import" id="import-btn" onclick="executeImport()">
        🚀 2. Import Langsung ke Timeline After Effects
      </button>

      <div class="status-box" id="import-status-box"></div>
    </div>
  </div>

  <script>
    let currentCaptions = [];

    function updateModeDesc() {
      const mode = document.getElementById('mode-select').value;
      const desc = document.getElementById('mode-desc');
      if (mode === 'Single Word') {
        desc.innerText = 'Tepat 1 kata per layer. Dinamis dan cocok untuk video pendek.';
      } else if (mode === 'Short') {
        desc.innerText = 'Target 2–3 kata per subtitle (maksimal 4 kata). Punchy Kinetic Typography, tanpa kata tunggal.';
      } else {
        desc.innerText = 'Ideal 3–5 kata per subtitle (maksimal 6 kata). Visual chunking frasa utuh, tanpa kata tunggal.';
      }
    }

    // Load initial captions if existing
    window.addEventListener('DOMContentLoaded', async () => {
      try {
        const resp = await fetch('/api/captions');
        const data = await resp.json();
        if (data.captions && data.captions.length > 0) {
          currentCaptions = data.captions;
          renderTable(data.captions, data.captions.length, data.mode || 'Exported', 'Siap Import / Diedit');
        }
      } catch (e) {}
    });

    // Stage 1: Export & Group
    async function executeExport() {
      const mode = document.getElementById('mode-select').value;
      const statusBox = document.getElementById('export-status-box');
      const btn = document.getElementById('export-btn');

      btn.disabled = true;
      statusBox.className = 'status-box loading';
      statusBox.innerHTML = '<div class="spinner"></div> 1/2 Merender audio Work Area dari After Effects...';

      try {
        const resp1 = await fetch('/api/workarea/render', { method: 'POST' });
        const data1 = await resp1.json();
        if (!data1.success) {
          throw new Error(data1.error || 'Gagal merender Work Area dari After Effects. Pastikan AE terbuka.');
        }

        statusBox.innerHTML = `<div class="spinner"></div> 2/2 Mentranskripsi (${data1.work_area_duration.toFixed(1)}s) & menyusun kata (${mode})...`;

        const resp2 = await fetch('/api/workarea/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: mode })
        });
        const data2 = await resp2.json();
        if (!data2.success) {
          throw new Error(data2.error || 'Gagal menyusun caption');
        }

        statusBox.className = 'status-box success';
        statusBox.innerHTML = `✓ <strong>Sukses Export!</strong> Berhasil menyusun <strong>${data2.total_captions}</strong> potongan subtitle (${data2.mode}). Silakan tinjau/edit di bawah atau lanjut ke Langkah 2.`;

        currentCaptions = data2.captions;
        renderTable(data2.captions, data2.total_captions, data2.mode, 'Bahasa Asli');

      } catch (err) {
        statusBox.className = 'status-box error';
        statusBox.innerText = 'Error: ' + err.message;
      } finally {
        btn.disabled = false;
      }
    }

    // Stage 2: Translate & Direct Import to AE
    async function executeImport() {
      // Auto-save any table changes first
      await saveTableChanges(true);

      const lang = document.getElementById('lang-select').value;
      const statusBox = document.getElementById('import-status-box');
      const btn = document.getElementById('import-btn');

      btn.disabled = true;
      statusBox.className = 'status-box loading';

      if (lang === 'original') {
        statusBox.innerHTML = '<div class="spinner"></div> Membuat text layer bahasa asli di timeline After Effects...';
      } else {
        const langLabel = (lang === 'id') ? 'Bahasa Indonesia' : 'Bahasa Inggris';
        statusBox.innerHTML = `<div class="spinner"></div> Menerjemahkan potongan per potongan ke ${langLabel} & membuat text layer di After Effects...`;
      }

      try {
        const resp = await fetch('/api/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ language: lang })
        });
        const data = await resp.json();
        if (!data.success) {
          throw new Error(data.error || 'Gagal mengimport ke After Effects');
        }

        const langName = (data.language === 'id') ? 'Bahasa Indonesia' : (data.language === 'en' ? 'Bahasa Inggris' : 'Asli');
        statusBox.className = 'status-box success';
        statusBox.innerHTML = `🎉 <strong>Berhasil!</strong> Sebanyak <strong>${data.total_layers}</strong> layer teks (${langName}) sudah dibuat langsung di timeline After Effects! (Tekan Cmd+Z jika ingin membatalkan).`;

        if (data.captions) {
          currentCaptions = data.captions;
          renderTable(data.captions, data.total_layers, 'Aktif', langName);
        }

      } catch (err) {
        statusBox.className = 'status-box error';
        statusBox.innerText = 'Error: ' + err.message;
      } finally {
        btn.disabled = false;
      }
    }

    function renderTable(captions, total, mode, langLabel) {
      const resultsCard = document.getElementById('results-card');
      const tbody = document.getElementById('results-body');
      tbody.innerHTML = '';
      currentCaptions = captions;

      captions.forEach((c, idx) => {
        const row = document.createElement('tr');
        const s = typeof c.start === 'number' ? c.start : parseFloat(c.start);
        const e = typeof c.end === 'number' ? c.end : parseFloat(c.end);
        const dur = (e - s).toFixed(2);

        row.innerHTML = `
          <td style="color: var(--text-muted); font-weight: bold;">${c.index || (idx + 1)}</td>
          <td><input type="number" step="0.05" class="edit-input time-input" id="time-start-${idx}" value="${s.toFixed(2)}" onchange="onInputChange(${idx})"></td>
          <td><input type="number" step="0.05" class="edit-input time-input" id="time-end-${idx}" value="${e.toFixed(2)}" onchange="onInputChange(${idx})"></td>
          <td style="color: #38bdf8; font-family: monospace;" id="dur-${idx}">${dur}s</td>
          <td><input type="text" class="edit-input" id="txt-${idx}" value="${escapeHtml(c.text || '')}" onchange="onInputChange(${idx})"></td>
        `;
        tbody.appendChild(row);
      });

      document.getElementById('results-title').innerText = `Hasil Export (${total} Subtitle) - [${langLabel}]`;
      resultsCard.style.display = 'block';
    }

    function escapeHtml(text) {
      return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    function onInputChange(idx) {
      const sVal = parseFloat(document.getElementById(`time-start-${idx}`).value);
      const eVal = parseFloat(document.getElementById(`time-end-${idx}`).value);
      const durEl = document.getElementById(`dur-${idx}`);
      if (!isNaN(sVal) && !isNaN(eVal)) {
        durEl.innerText = (eVal - sVal).toFixed(2) + 's';
      }
    }

    async function saveTableChanges(silent = false) {
      if (!currentCaptions || currentCaptions.length === 0) return;

      const updated = [];
      for (let i = 0; i < currentCaptions.length; i++) {
        const sVal = parseFloat(document.getElementById(`time-start-${i}`).value);
        const eVal = parseFloat(document.getElementById(`time-end-${i}`).value);
        const tVal = document.getElementById(`txt-${i}`).value.trim();

        if (isNaN(sVal) || isNaN(eVal) || eVal <= sVal) {
          if (!silent) alert(`Subtitle #${i + 1}: Waktu tidak valid (End harus lebih besar dari Start).`);
          return;
        }
        if (!tVal) {
          if (!silent) alert(`Subtitle #${i + 1}: Teks tidak boleh kosong.`);
          return;
        }

        updated.push({
          index: i + 1,
          start: sVal,
          end: eVal,
          text: tVal,
          word_count: tVal.split(/\\s+/).length,
          word_indices: currentCaptions[i].word_indices || []
        });
      }

      const statusBox = document.getElementById('table-status-box');
      if (!silent) {
        statusBox.className = 'status-box loading';
        statusBox.innerHTML = '<div class="spinner"></div> Menyimpan perubahan...';
      }

      try {
        const resp = await fetch('/api/captions/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ captions: updated })
        });
        const data = await resp.json();
        if (!data.success) {
          throw new Error(data.error || 'Gagal menyimpan perubahan');
        }

        currentCaptions = data.captions;
        if (!silent) {
          statusBox.className = 'status-box success';
          statusBox.innerHTML = `✓ <strong>Tersimpan!</strong> Seluruh perubahan teks dan timing (${data.total_captions} subtitle) berhasil disimpan ke file export.`;
          setTimeout(() => { statusBox.style.display = 'none'; }, 4000);
        }
      } catch (err) {
        if (!silent) {
          statusBox.className = 'status-box error';
          statusBox.innerText = 'Error: ' + err.message;
        }
      }
    }

    async function openFolder() {
      await fetch('/api/open-folder', { method: 'POST' });
    }
  </script>
</body>
</html>
"""


class CaptionServerHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "elevenlabs": config.has_elevenlabs_key(),
                        "openai": bool(config.openai_api_key),
                        "gemini": bool(config.gemini_api_key),
                    }
                ).encode("utf-8")
            )
        elif self.path == "/api/captions":
            captions_file = config.output_dir / "captions.json"
            if captions_file.exists():
                with open(captions_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(data, ensure_ascii=False).encode("utf-8")
                )
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"captions": []}')
        elif self.path in {"/api/captions.srt", "/api/download/srt"}:
            srt_path = config.output_dir / "captions.srt"
            if srt_path.exists():
                with open(srt_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="captions.srt"'
                )
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/workarea/render":
            self._handle_workarea_render()
        elif self.path == "/api/workarea/export":
            self._handle_workarea_export()
        elif self.path == "/api/captions/update":
            self._handle_captions_update()
        elif self.path == "/api/import":
            self._handle_import()
        elif self.path == "/api/open-folder":
            config.output_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(config.output_dir.resolve())])
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_workarea_render(self):
        """Renders Work Area audio from active composition in After Effects."""
        try:
            meta = render_ae_workarea()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": True, **meta}).encode("utf-8")
            )
        except Exception as e:
            self._send_json_error(str(e))

    def _handle_workarea_export(self):
        """Stage 1: Transcribes rendered Work Area audio and groups into captions."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            req_data = json.loads(raw_body.decode("utf-8")) if raw_body else {}

            mode_str = req_data.get("mode", "Long")
            selected_mode = GroupingMode.from_string(mode_str)

            meta_json = Path("/tmp/ae_workarea_meta.json")
            if not meta_json.exists():
                self._send_json_error(
                    "No rendered Work Area audio found. Please render first."
                )
                return

            with open(meta_json, "r", encoding="utf-8") as f:
                meta = json.load(f)

            audio_file = Path(meta["audio_file"])
            work_start = float(meta["work_area_start"])

            # Export captions (NO auto-import yet)
            res = export_captions(
                input_file=audio_file,
                mode=selected_mode,
                time_offset=work_start,
            )

            formatted_captions = []
            for c in res["captions"]:
                c_dict = dict(c)
                c_dict["start_formatted"] = format_timestamp(c["start"])
                c_dict["end_formatted"] = format_timestamp(c["end"])
                formatted_captions.append(c_dict)

            resp_data = {
                "success": True,
                "mode": selected_mode.value,
                "total_captions": len(formatted_captions),
                "captions": formatted_captions,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            )
        except Exception as e:
            self._send_json_error(str(e))

    def _handle_captions_update(self):
        """Updates captions text & timing in captions.json and captions.srt."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            req_data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            new_captions = req_data.get("captions", [])

            captions_file = config.output_dir / "captions.json"
            existing_data = {}
            if captions_file.exists():
                with open(captions_file, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)

            groups = []
            for i, c in enumerate(new_captions):
                txt = str(c.get("text", "")).strip()
                s_time = float(c.get("start", 0.0))
                e_time = float(c.get("end", 0.0))
                groups.append(
                    CaptionGroup(
                        index=i + 1,
                        text=txt,
                        start=s_time,
                        end=e_time,
                        word_indices=c.get("word_indices", []),
                        word_count=len(txt.split()),
                    )
                )

            srt_content = generate_srt(groups)
            existing_data["captions"] = [g.to_dict() for g in groups]
            existing_data["total_captions"] = len(groups)
            existing_data["srt"] = srt_content

            with open(captions_file, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)

            srt_path = config.output_dir / "captions.srt"
            with open(srt_path, "w", encoding="utf-8") as sf:
                sf.write(srt_content)

            resp_data = {
                "success": True,
                "total_captions": len(groups),
                "captions": [g.to_dict() for g in groups],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            )
        except Exception as e:
            self._send_json_error(str(e))

    def _handle_import(self):
        """Stage 2: Translates chunk-by-chunk if requested, and directly creates AE text layers."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            req_data = json.loads(raw_body.decode("utf-8")) if raw_body else {}

            target_lang = req_data.get("language", "original")
            import_res = import_captions_to_timeline(
                target_language=target_lang
            )

            formatted_captions = []
            for c in import_res.get("captions", []):
                c_dict = dict(c)
                c_dict["start_formatted"] = format_timestamp(c["start"])
                c_dict["end_formatted"] = format_timestamp(c["end"])
                formatted_captions.append(c_dict)

            resp_data = {
                "success": True,
                "language": import_res.get("language", target_lang),
                "total_layers": import_res.get("total_layers", len(formatted_captions)),
                "captions": formatted_captions,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            )
        except Exception as e:
            self._send_json_error(str(e))

    def _send_json_error(self, message: str, status_code: int = 400):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"success": False, "error": message}).encode("utf-8")
        )


def main():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, CaptionServerHandler)
    url = f"http://localhost:{PORT}"
    print("\n" + "=" * 60)
    print(f"🚀 AI Caption Generator UI running at:")
    print(f"   {url}")
    print("=" * 60 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[UI Server Stopped]")


if __name__ == "__main__":
    main()
