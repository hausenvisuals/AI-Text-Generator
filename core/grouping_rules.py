"""Caption Grouping Rules and Configurations (Kinetic Typography Standards).

Defines the three supported grouping modes:
- Single Word: exactly 1 word per caption layer.
- Short: target 2-3 words per caption layer (strict tolerance: 2-4 words, NO 1-word groups!).
- Long: target 3-5 words per caption layer (strict tolerance: 2-6 words, NO 1-word groups!).

Strict Constraints:
1. MINIMUM 2 WORDS per caption group (NO single isolated words allowed in Short or Long).
2. Never split compound proper nouns or terms (e.g. "Marco Island", "Bonita Springs", "Fort Myers").
3. Preserve visual chunking and natural grammatical phrase boundaries.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Union


class GroupingMode(str, Enum):
    SINGLE_WORD = "Single Word"
    SHORT = "Short"
    LONG = "Long"

    @classmethod
    def from_string(cls, value: str) -> "GroupingMode":
        """Normalize string inputs like 'single', 'short', 'long', 'single word'."""
        val = value.strip().lower()
        if val in {"single", "single word", "single_word", "1"}:
            return cls.SINGLE_WORD
        elif val in {"short", "2-3", "2"}:
            return cls.SHORT
        elif val in {"long", "4-5", "3"}:
            return cls.LONG
        return cls.SHORT


@dataclass(frozen=True)
class ModeRules:
    mode: GroupingMode
    target_min: int
    target_max: int
    min_tolerance: int
    max_tolerance: int
    max_pause_sec: float
    description: str


# Predefined rules for each mode (Strict Kinetic Typography)
MODE_RULES: Dict[GroupingMode, ModeRules] = {
    GroupingMode.SINGLE_WORD: ModeRules(
        mode=GroupingMode.SINGLE_WORD,
        target_min=1,
        target_max=1,
        min_tolerance=1,
        max_tolerance=1,
        max_pause_sec=0.0,
        description="Creates exactly one caption text layer per recognized word.",
    ),
    GroupingMode.SHORT: ModeRules(
        mode=GroupingMode.SHORT,
        target_min=2,
        target_max=3,
        min_tolerance=2,  # Strict: NO single word groups allowed!
        max_tolerance=4,  # Tolerance: max 1 word extra from 3 = 4 words
        max_pause_sec=0.35,
        description="Target 2-3 words per caption (strict: 2 to 4 words). Punchy, dynamic, NO single words.",
    ),
    GroupingMode.LONG: ModeRules(
        mode=GroupingMode.LONG,
        target_min=3,
        target_max=5,
        min_tolerance=2,  # Strict: NO single word groups allowed!
        max_tolerance=7,  # Maximum 7 words per subtitle (safety net for compound phrases)
        max_pause_sec=0.45,
        description="Ideal 3-5 words per caption (strict: 2 to 7 words). Visual chunking, NO single words.",
    ),
}


def get_mode_rules(mode: Union[GroupingMode, str]) -> ModeRules:
    """Retrieves the ModeRules for the specified grouping mode."""
    if isinstance(mode, str):
        mode = GroupingMode.from_string(mode)
    return MODE_RULES.get(mode, MODE_RULES[GroupingMode.SHORT])


def build_llm_prompt_for_mode(mode: GroupingMode, word_list_text: str, total_words: int) -> str:
    """Builds an LLM prompt specifically customized to the selected grouping mode
    incorporating strict Kinetic Typography segmentation rules.
    """
    if mode == GroupingMode.LONG:
        mode_instructions = """ATURAN UTAMA SEGMENTASI LONG (KINETIC TYPOGRAPHY):
1. MINIMAL 2 KATA PER SUBTITLE. STRICT: TIDAK BOLEH ADA 1 KATA YANG BERDIRI SENDIRI DALAM SATU SUBTITLE!
   - Pengecualian HANYA jika:
     a. Kata penegasan atau reaksi dramatis yang diapit jeda hening / pause panjang (misal: "..... Yes .....", "..... Exactly .....", "..... No .....").
     b. Kalimat 1 kata dramatis berakhiran tanda titik (misal: "Nothing.").
     c. Penyebutan poin-poin/daftar kata tunggal yang memang berdiri sendiri dalam konteksnya (misal: "Location,", "Price,", "Quality.").
   - Di luar 3 kondisi pengecualian di atas, JANGAN PERNAH menyisakan 1 kata berdiri sendiri!
2. TARGET RITME: 3–5 KATA PER SUBTITLE (FLEKSIBILITAS SEMANTIK 2–7 KATA).
   - Kisaran 3–5 kata adalah ritme visual ideal video vertikal (TikTok/Reels/Shorts).
   - REKOMENDASI AI & FLEKSIBILITAS SEMANTIK (Hingga 6–7 Kata): Berikan fleksibilitas elastis hingga 6 atau maksimal 7 kata JIKA diperlukan untuk menjaga keutuhan kata majemuk, nama fasilitas/tempat (misal: "private beach club,", "beachfront fire pits,"), atau agar klausa yang berakhiran tanda koma (,) tidak terpotong canggung di tengah jalan. Utamakan keutuhan makna dan jeda koma di atas kekakuan hitungan angka kata!
3. FORMULA SINTAKSIS & FRASA TATA BAHASA (SYNTACTIC CHUNKING - ENGLISH / SPANISH / INDONESIAN):
   - Gabungkan kata berdasarkan unit gramatikal yang utuh: Frasa Benda (Noun Phrase), Frasa Kata Sifat (Adj + Noun), Frasa Kata Depan (Prepositional Phrase).
   - JANGAN MEMOTONG di tengah gabungan kata yang merupakan satu kesatuan makna, nama, brand, fasilitas, atau istilah majemuk:
     * English: "Marco Island", "Bonita Springs", "Fort Myers", "Caloosa Cove", "Calusa Cove", "Miami Lakes", "I-75", "HOA", "Realty Group", "Vanguard Realty Group", "Southwest Florida", "real estate", "real estate expert", "luxury waterfront property", "trusted partner", "beach club", "private beach club", "fire pits", "beachfront fire pits", "tiki bar", "tennis courts", "swimming pool", "fitness center", "dining room", "dining lawn".
     * Spanish: "Calusa Cove", "Fort Myers", "sentido de comunidad", "pueblos pequeños", "centro histórico", "comunidad privada", "cuotas de CDD", "a orillas del río", "echar raíces", "más que", "más allá", "sin embargo", "toda la familia", "totalmente nuevas", "hoy mismo", "lo que".
     * Indonesian: "real estat", "kolam renang", "lapangan tenis", "pusat kebugaran", "ruang makan", "rumah terbuka", "agen properti".
   - KATA KUNCI FASILITAS, LOKASI & PROPERTI: HARUS SELALU MENJADI SATU KESATUAN UTUH (jangan memisahkan "beach" dan "club", "Calusa" dan "Cove", "sentido" dan "de comunidad").
   - JANGAN MEMBIARKAN KATA GANTUNG:
     * Hindari memotong frasa yang membuat kata sandang/kepemilikan (the, a, an, our; el, la, los, las, un, una, del, al, su, sus, mi, tu) atau kata depan/konjungsi (to, of, in, on, at, by, for, with, and, or; de, en, a, con, por, para, sin, sobre, que, y, e, o, u) menggantung canggung di akhir baris tanpa kata bendanya.
     * Kata depan atau konjungsi (seperti "and", "y", "con", "por", "to") harus menjadi kata PEMBUKA di baris baru, bukan kata penutup yang menggantung.
   - Potonglah di batas frasa yang alami (misal: potong sebelum kata depan "to local expertise", atau sebelum konjungsi "and", "y a dos horas de Miami").
   - Jangan memisahkan angka dengan satuannya jika memungkinkan (misal: "30 minutes", "treinta minutos", "dos horas", "$500").
   - Setiap subtitle harus berdiri sebagai satu "visual chunk" yang utuh, tidak menggantung, dan enak dibaca dalam 1-2 detik.
4. JIKA TERSISA 1 KATA DI AKHIR KALIMAT: Selalu gabungkan dengan grup sebelumnya (asal total <= 7 kata) atau seimbangkan (misal 3+2 kata, bukan 4+1 kata).
5. STRICT SENTENCE BOUNDARY: JANGAN PERNAH MENYEBERANG TANDA TITIK (.), TANDA TANYA (?), ATAU TANDA SERU (!). Kata yang memiliki tanda titik (.) di belakangnya HARUS menjadi kata TERAKHIR di grupnya. Awal kalimat berikutnya HARUS dimulai pada grup subtitle baru!
6. ATURAN TANDA KOMA (,) & BATAS KLAUSA / DAFTAR POIN:
   - KOMA KLAUSA / JEDA BIASA: Tanda koma pada jeda anak kalimat biasa adalah batas pemotong baris (misal: "Two markets," [layer baru] "one trusted connection.").
   - DAFTAR POIN / ENUMERASI DENGAN BANYAK KOMA:
     * POIN RINGKAS (1–2 KATA PER POIN): Jika kalimat menyebutkan rangkaian poin pendek (misal: "tennis courts, swimming pools,"), JANGAN memotong di setiap koma! Gabungkan 2 poin pendek tersebut ke dalam 1 baris (total 4–5 kata) agar tidak kedip terlalu cepat di layar video.
     * POIN BERBOBOT (>= 3 KATA PER POIN): Jika sebuah poin sudah terdiri dari 3 kata atau lebih (misal: "beachfront fire pits,"), poin tersebut SUDAH cukup berbobot dan MASUK target ritme ideal (3–5 kata), sehingga HARUS DIPISAH menjadi baris mandiri tepat setelah tanda komanya!
   - PEMENGGALAN SEIMBANG KLAUSA PANJANG (> 7 KATA SEBELUM KOMA): Jika sebuah klausa sebelum tanda koma melebihi 7 kata, potonglah secara seimbang menjadi dua grup logis (misal: 4–5 kata pada grup pertama, lalu 2–3 kata penutup yang berakhiran tanda koma pada grup kedua), JANGAN memotong sembarangan yang menyisakan 1 kata menggantung sebelum koma.
   - JANGAN PERNAH menarik 1 kata setelah tanda koma ke dalam grup yang sama jika kata tersebut bagian dari frasa berikutnya (misal: JANGAN "club, beachfront" jika beachfront adalah bagian dari fire pits).
   - Jangan memisahkan angka/determiner dengan bendanya (misal: "one" dipisahkan dari "trusted connection")."""
    elif mode == GroupingMode.SHORT:
        mode_instructions = """ATURAN UTAMA SEGMENTASI SHORT (KINETIC TYPOGRAPHY):
1. MINIMAL 2 KATA PER SUBTITLE. STRICT: TIDAK BOLEH ADA 1 KATA YANG BERDIRI SENDIRI DALAM SATU SUBTITLE!
   - Pengecualian HANYA jika:
     a. Kata penegasan atau reaksi dramatis yang diapit jeda hening / pause panjang (misal: "..... Yes .....", "..... Exactly .....", "..... No .....").
     b. Kalimat 1 kata dramatis berakhiran tanda titik (misal: "Nothing.").
     c. Penyebutan poin-poin/daftar kata tunggal yang memang berdiri sendiri (misal: "Location,", "Price,").
   - Di luar 3 kondisi pengecualian di atas, JANGAN PERNAH menyisakan 1 kata berdiri sendiri!
2. TARGET: 2–3 KATA PER SUBTITLE. Toleransi maksimal 1 kata (Range: 2 sampai 4 kata per grup).
   - Range kata per grup: HARUS ANTARA 2 SAMPAI 4 KATA.
3. Potonglah di batas frasa yang alami, cepat, dan punchy untuk video vertikal (Reels/TikTok/Shorts).
4. PANDUAN PEMENGGALAN FRASA LOGIS & COMPOUND TERMS (ENGLISH / SPANISH / INDONESIAN):
   - JANGAN MEMOTONG di tengah gabungan kata yang merupakan satu kesatuan nama/istilah/brand/fasilitas (misal: "Marco Island", "Bonita Springs", "Fort Myers", "Calusa Cove", "Vanguard Realty Group", "Southwest Florida", "real estate", "real estate expert", "beach club", "fire pits", "tiki bar", "sentido de comunidad", "pueblos pequeños", "centro histórico", "comunidad privada", "más que", "sin embargo").
   - KATA KUNCI FASILITAS & LOKASI: HARUS SELALU MENJADI SATU KESATUAN UTUH.
   - JANGAN MEMBIARKAN KATA GANTUNG: Hindari memotong frasa yang membuat kata sandang/kepemilikan (the, a; el, la, los, las, un, una, del, al, su) atau kata depan/konjungsi (to, of, in, with; de, en, a, con, por, para, sin, que, y, o) menggantung di akhir baris.
   - Jangan memisahkan angka dengan satuannya (misal: "30 minutes", "treinta minutos").
   - Setiap subtitle harus berdiri sebagai satu "visual chunk" yang utuh dan tidak menggantung.
5. JIKA TERSISA 1 KATA DI AKHIR KALIMAT: Selalu gabungkan atau seimbangkan (misal 2+2 kata, bukan 3+1 kata).
6. STRICT SENTENCE BOUNDARY: JANGAN PERNAH MENYEBERANG TANDA TITIK (.), TANDA TANYA (?), ATAU TANDA SERU (!). Kata yang memiliki tanda titik (.) di belakangnya HARUS menjadi kata TERAKHIR di grupnya. Awal kalimat berikutnya HARUS dimulai pada grup subtitle baru!
7. ATURAN TANDA KOMA (,) & BATAS KLAUSA:
   - Tanda koma (,) pada frasa/anak kalimat HARUS menjadi kata TERAKHIR di grupnya (misal: "Two markets," [layer baru] "one trusted connection.").
   - JANGAN PERNAH menarik 1 kata setelah tanda koma ke dalam grup yang sama.
   - Pengecualian HANYA jika berupa daftar kata tunggal pendek yang rapat (misal: "House, hotel, apartment")."""
    else:
        mode_instructions = """Target: Exactly 1 word per group. Create one group for each word index."""

    return f"""You are an elite video editor and caption subtitler specializing in Kinetic Typography subtitles.
Group the following sequentially numbered words into professional caption phrases according to the exact rules below.

Caption Grouping Mode: {mode.value}

{mode_instructions}

SHARED INTEGRITY RULES:
1. Do NOT drop, omit, duplicate, add, translate, or rewrite any words.
2. Every word index from 0 to {total_words - 1} must appear exactly once in contiguous chronological order.
3. Keep original punctuation and capitalization intact.
4. Output structured JSON with key "groups", where each group contains:
   - "word_indices": list of consecutive integer indices.

Word List:
{word_list_text}

Respond ONLY with valid JSON in this exact structure:
{{
  "groups": [
    {{"word_indices": [0, 1, 2]}},
    {{"word_indices": [3, 4, 5]}}
  ]
}}
"""
