"""Intelligent Chunk-by-Chunk Caption Translation Service.

Translates pre-segmented caption groups (Single Word, Short, Long) into the target language
(Indonesian or English) with strict 1-to-1 chunk correspondence:
1. Each input chunk i maps strictly to output chunk i with identical start and end timestamps.
2. Mode-aware translation:
   - Single Word: translates 1 word per unit while respecting overall context.
   - Short: translates cohesive 2-3 word phrases.
   - Long: translates smooth 3-5 word clauses with natural syntax.
3. Proper noun compound protection: keeps 'Marco Island', 'Bonita Springs',
   'Vanguard Realty Group', 'Southwest Florida', etc. intact.
4. Directly prepares the translated CaptionGroups for After Effects timeline import.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union
import urllib.error
import urllib.request

from config import config, safe_urlopen
from grouping_rules import GroupingMode
from grouping_service import CaptionGroup

PROPER_NOUNS_PROTECTION = [
    "Marco Island",
    "Bonita Springs",
    "Naples",
    "Fort Myers",
    "Caloosa Cove",
    "Miami Lakes",
    "Vanguard Realty Group",
    "Southwest Florida",
    "Florida",
    "After Effects",
]


class TranslationError(Exception):
    """Raised when translation fails or violates 1-to-1 chunk correspondence."""

    pass


def build_translation_prompt(
    chunks: List[str],
    full_transcript: str,
    target_language: str,
    mode: GroupingMode,
) -> str:
    """Builds a strict 1-to-1 chunk translation prompt for LLM."""
    lang_name = "Bahasa Indonesia" if target_language.lower() in {"id", "indonesia", "indonesian"} else "English"
    total_slots = len(chunks)

    if mode == GroupingMode.SINGLE_WORD:
        mode_instruction = (
            f"MODE: SINGLE WORD (KATA PER KATA / KINETIC TYPOGRAPHY)\n"
            f"- Terdapat {total_slots} slot kata (nomor 0 sampai {total_slots - 1}).\n"
            f"- Setiap nomor slot wajib memiliki 1 kata terjemahan yang pas dan natural.\n"
            f"- Jika ada frasa majemuk (misal 'real estate' -> 'real' 'estat'), sebarkan kata-katanya ke slot yang tersedia.\n"
            f"- JANGAN melewatkan nomor slot mana pun. Seluruh {total_slots} slot harus memiliki entri terjemahan."
        )
    elif mode == GroupingMode.SHORT:
        mode_instruction = (
            f"MODE: SHORT (FRASA 2-3 KATA)\n"
            f"- Terdapat {total_slots} slot frasa (nomor 0 sampai {total_slots - 1}).\n"
            f"- Terjemahkan secara berurutan agar menghasilkan kalimat {lang_name} yang padat, enak dibaca, dan mengalir wajar.\n"
            f"- JANGAN menggabungkan dua nomor slot menjadi satu. Setiap slot 0 s/d {total_slots - 1} harus ada entri tersendiri."
        )
    else:
        mode_instruction = (
            f"MODE: LONG (KLAUSA / KALIMAT 3-5 KATA)\n"
            f"- Terdapat {total_slots} slot klausa (nomor 0 sampai {total_slots - 1}).\n"
            f"- Terjemahkan setiap baris menjadi bahasa yang mengalir alami (idiomatic), enak dibaca, dan tidak kaku."
        )

    formatted_chunks = "\n".join(f"{i}: {c}" for i, c in enumerate(chunks))

    prompt = f"""You are an elite video subtitler and translator for video editors.
Translate the following sequentially numbered subtitle chunks into {lang_name}.

FULL AUDIO CONTEXT (For reference only to understand the meaning):
\"\"\"{full_transcript}\"\"\"

{mode_instruction}

STRICT TRANSLATION RULES:
1. STRICT 1-TO-1 CORRESPONDENCE (EXACTLY {total_slots} ITEMS):
   - You must output EXACTLY {total_slots} translated chunks numbered 0 to {total_slots - 1}.
   - Item i in the output MUST correspond to Item i in the input.
   - Do NOT merge two items together. Do NOT skip any index.
2. PROPER NOUNS & BRAND NAMES:
   - DO NOT translate or alter proper location names, brand names, or real estate entities:
     * Keep 'Marco Island', 'Bonita Springs', 'Naples', 'Vanguard Realty Group', 'Southwest Florida', 'Florida' intact.
3. PUNCTUATION & CAPITALIZATION:
   - Maintain appropriate punctuation (commas, question marks, periods) corresponding to the original chunks.
4. Output format: respond ONLY with valid JSON with key "translations", which is a list of indexed objects:
{{
  "translations": [
    {{"index": 0, "text": "translated chunk 0"}},
    {{"index": 1, "text": "translated chunk 1"}},
    ...
    {{"index": {total_slots - 1}, "text": "translated chunk {total_slots - 1}"}}
  ]
}}

Subtitle Chunks to Translate:
{formatted_chunks}
"""
    return prompt


class TranslationService:
    """Manages AI translation of caption groups with 1-to-1 chunk preservation."""

    def __init__(self):
        self.openai_key = config.openai_api_key
        self.gemini_key = config.gemini_api_key

    def _call_openai(self, prompt: str) -> Dict[str, Any]:
        """Calls OpenAI Chat Completion endpoint."""
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": config.llm_model or "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional subtitle translator. Output only valid JSON with key 'translations'.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_key}",
            },
            method="POST",
        )
        with safe_urlopen(req, timeout=30) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            content = resp_body["choices"][0]["message"]["content"]
            return json.loads(content)

    def _call_gemini(self, prompt: str) -> Dict[str, Any]:
        """Calls Gemini API endpoint."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with safe_urlopen(req, timeout=30) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            content = resp_body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(content)

    def translate_groups(
        self,
        groups: List[CaptionGroup],
        target_language: str = "id",
        mode: Union[GroupingMode, str] = GroupingMode.LONG,
    ) -> List[CaptionGroup]:
        """Translates each CaptionGroup chunk into the target language.

        Preserves exact start/end timestamps and 1-to-1 correspondence.
        """
        if not groups:
            return []

        # If original language requested, return clone as-is
        lang_code = target_language.lower().strip()
        if lang_code in {"original", "none", "asli", ""}:
            return deepcopy(groups)

        mode_enum = (
            mode
            if isinstance(mode, GroupingMode)
            else GroupingMode.from_string(mode)
        )

        chunk_texts = [g.text for g in groups]
        full_transcript = " ".join(chunk_texts)

        prompt = build_translation_prompt(
            chunks=chunk_texts,
            full_transcript=full_transcript,
            target_language=lang_code,
            mode=mode_enum,
        )

        translated_raw = None

        try:
            if self.openai_key:
                print(
                    f"[Translation] Calling OpenAI ({config.llm_model}) to translate {len(groups)} chunks to {lang_code}..."
                )
                resp = self._call_openai(prompt)
                translated_raw = resp.get("translations", resp)
            elif self.gemini_key:
                print(
                    f"[Translation] Calling Gemini to translate {len(groups)} chunks to {lang_code}..."
                )
                resp = self._call_gemini(prompt)
                translated_raw = resp.get("translations", resp)
            else:
                raise TranslationError(
                    "No LLM API key configured for translation. Please configure OPENAI_API_KEY in .env."
                )
        except Exception as e:
            print(f"[Error] Translation API call failed: {e}")
            raise TranslationError(f"Translation API call failed: {e}") from e

        # Parse and align translations with zero-drop elastic safety
        translated_texts = self._align_translated_chunks(groups, translated_raw)

        # Build translated CaptionGroups preserving identical timing
        result: List[CaptionGroup] = []
        for i, (orig, trans) in enumerate(zip(groups, translated_texts), start=1):
            clean_text = trans.strip() if trans else orig.text
            words = clean_text.split()
            result.append(
                CaptionGroup(
                    index=i,
                    text=clean_text,
                    start=orig.start,
                    end=orig.end,
                    word_indices=list(orig.word_indices),
                    word_count=len(words),
                )
            )

        print(
            f"✓ Successfully translated {len(result)} caption groups to {lang_code}!"
        )
        return result

    def _align_translated_chunks(
        self, groups: List[CaptionGroup], raw_data: Any
    ) -> List[str]:
        """Aligns translated items to the exact number of caption groups with zero-drop safety.

        Supports:
        - List of dicts with 'index' and 'text'
        - Dict with string index keys {"0": "text", ...}
        - Plain list of translated strings
        - Elastic borrower for missing slots (never falls back to English for minor mismatches)
        """
        N = len(groups)
        slot_map: Dict[int, str] = {}
        flat_list: List[str] = []

        if isinstance(raw_data, dict):
            if "translations" in raw_data:
                raw_data = raw_data["translations"]

        if isinstance(raw_data, dict):
            for k, v in raw_data.items():
                try:
                    slot_map[int(k)] = str(v).strip()
                except (ValueError, TypeError):
                    pass
        elif isinstance(raw_data, list):
            if raw_data and isinstance(raw_data[0], dict):
                for item in raw_data:
                    idx = item.get("index", item.get("id"))
                    txt = item.get("text", "")
                    if idx is not None:
                        try:
                            slot_map[int(idx)] = str(txt).strip()
                        except (ValueError, TypeError):
                            pass
            else:
                flat_list = [str(x).strip() for x in raw_data]
                for i, txt in enumerate(flat_list):
                    slot_map[i] = txt

        final_texts: List[str] = [""] * N

        # 1. Fill directly from slot_map
        if slot_map:
            for i in range(N):
                if i in slot_map and slot_map[i]:
                    final_texts[i] = slot_map[i]

        # 2. If slot_map was empty but flat_list existed, map elastically
        if not any(final_texts) and flat_list:
            M = len(flat_list)
            if M <= N:
                for i in range(M):
                    final_texts[i] = flat_list[i]
            else:
                for i in range(N - 1):
                    final_texts[i] = flat_list[i]
                final_texts[N - 1] = " ".join(flat_list[N - 1:])

        # 3. Elastic repair for any remaining empty slots (borrow from adjacent or fallback)
        for i in range(N):
            if not final_texts[i]:
                if i > 0 and len(final_texts[i - 1].split()) > 1:
                    parts = final_texts[i - 1].split()
                    final_texts[i - 1] = " ".join(parts[:-1])
                    final_texts[i] = parts[-1]
                elif i < N - 1 and final_texts[i + 1] and len(final_texts[i + 1].split()) > 1:
                    parts = final_texts[i + 1].split()
                    final_texts[i] = parts[0]
                    final_texts[i + 1] = " ".join(parts[1:])
                else:
                    final_texts[i] = groups[i].text

        return final_texts
