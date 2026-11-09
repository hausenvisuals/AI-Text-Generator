"""Intelligent Caption Grouping Service.

Groups transcribed words into readable, rhythmic caption phrases based on selected mode:
- Single Word: exactly 1 word per layer
- Short (Default): target 2-3 words (tolerance 2-4, NO single words!)
- Long: target 3-5 words (tolerance 2-7, NO single words!)

Supports:
1. LLM-based grouping (OpenAI & Gemini APIs) with mode-aware prompts and strict validation.
2. Deterministic heuristic fallback grouper respecting selected mode, speech pauses, syntax, and compound terms.
3. Strict integrity validator ensuring zero dropped, duplicated, or reordered words.
4. Export to standard SRT format (HH:MM:SS,mmm) and structured JSON.
"""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.error
import urllib.request

from config import config, safe_urlopen
from grouping_rules import (
    GroupingMode,
    ModeRules,
    build_llm_prompt_for_mode,
    get_mode_rules,
)
from stt_service import WordToken

# Words that naturally open prepositional, adverbial, or conjunctional phrases (English, Spanish, Indonesian)
PHRASE_STARTERS = {
    # English
    "to", "in", "on", "at", "by", "for", "with", "about", "into", "through", "from",
    "under", "over", "a", "an", "the", "and", "or", "but", "inside", "outside",
    "after", "before", "while", "when",
    # Spanish
    "a", "en", "de", "con", "por", "para", "sin", "sobre", "desde", "hasta", "hacia",
    "el", "la", "los", "las", "un", "una", "unos", "unas", "del", "al", "que", "y", "e",
    "o", "u", "pero", "cuando", "donde", "como", "porque",
    # Indonesian
    "di", "ke", "dari", "pada", "untuk", "dengan", "dalam", "tentang", "setelah",
    "sebelum", "ketika", "saat", "dan", "atau", "tetapi", "tapi", "karena", "bahwa", "jika",
}

# Connective words that shouldn't sit awkwardly at the end of a caption group (English, Spanish, Indonesian)
DANGLING_END_WORDS = {
    # English
    "the", "a", "an", "to", "of", "in", "on", "at", "by", "for", "with", "and", "or",
    "but", "that", "which", "as", "is", "are", "was", "were", "my", "your", "his",
    "her", "our", "their",
    # Spanish (Articles, Possessives, Prepositions, Conjunctions, Numerals)
    "el", "la", "los", "las", "un", "una", "unos", "unas", "del", "al", "lo",
    "mi", "mis", "tu", "tus", "su", "sus", "nuestro", "nuestra", "nuestros", "nuestras",
    "de", "en", "a", "con", "por", "para", "sin", "sobre", "hacia", "desde", "hasta",
    "entre", "bajo", "contra", "que", "y", "e", "o", "u", "pero", "sino", "porque",
    "como", "si", "aunque", "donde", "cuando", "más", "mas", "menos", "tan", "muy",
    "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    "veinte", "treinta", "cuarenta", "cincuenta", "es", "son", "fue", "era", "está",
    "estan", "están", "ha", "han",
    # Indonesian
    "di", "ke", "dari", "pada", "untuk", "dengan", "dan", "atau", "tapi", "tetapi",
    "yang", "ini", "itu", "sebuah", "para", "sang", "si", "dalam", "atas", "bawah",
    "oleh", "karena", "sebab", "agar", "supaya", "jika", "kalau", "saat", "ketika",
    "adalah", "ialah", "yaitu", "merupakan", "akan", "telah", "sudah", "sedang",
    "bisa", "dapat", "lebih", "kurang", "sangat", "paling",
}

# Known multi-word proper nouns, compounds, and amenities that should never be split across captions
KNOWN_COMPOUNDS = [
    # Florida proper locations and communities
    ("marco", "island"),
    ("bonita", "springs"),
    ("fort", "myers"),
    ("caloosa", "cove"),
    ("calusa", "cove"),
    ("miami", "lakes"),
    ("realty", "group"),
    ("vanguard", "realty"),
    ("southwest", "florida"),
    ("real", "estate"),
    ("estate", "expert"),
    ("backed", "by"),
    ("part", "of"),
    ("open", "house"),
    ("gulf", "coast"),
    ("social", "media"),
    ("customer", "service"),
    ("after", "effects"),
    ("work", "area"),
    # Hospitality, luxury amenities, and property features
    ("beach", "club"),
    ("fire", "pits"),
    ("fire", "pit"),
    ("beachfront", "fire"),
    ("tiki", "bar"),
    ("tennis", "court"),
    ("tennis", "courts"),
    ("swimming", "pool"),
    ("swimming", "pools"),
    ("fitness", "center"),
    ("fitness", "centre"),
    ("dining", "room"),
    ("dining", "lawn"),
    ("dining", "area"),
    ("golf", "course"),
    ("club", "house"),
    ("pickleball", "court"),
    ("pickleball", "courts"),
    ("valet", "parking"),
    ("water", "front"),
    ("living", "room"),
    # Spanish kinetic typography phrases, community collocations & proper terms
    ("pueblos", "pequeños"),
    ("pueblos", "pequenos"),
    ("centro", "histórico"),
    ("centro", "historico"),
    ("lugares", "favoritos"),
    ("comunidad", "privada"),
    ("cuotas", "de"),
    ("de", "cdd"),
    ("sentido", "de"),
    ("de", "comunidad"),
    ("a", "orillas"),
    ("orillas", "del"),
    ("del", "río"),
    ("del", "rio"),
    ("echar", "raíces"),
    ("echar", "raices"),
    ("toda", "la"),
    ("la", "familia"),
    ("totalmente", "nuevas"),
    ("hoy", "mismo"),
    ("sin", "embargo"),
    ("más", "allá"),
    ("mas", "alla"),
    ("más", "que"),
    ("mas", "que"),
    ("más", "tranquilo"),
    ("mas", "tranquilo"),
    ("más", "tranquilos"),
    ("mas", "tranquilos"),
    ("barrios", "bulliciosos"),
    ("treinta", "minutos"),
    ("dos", "horas"),
    ("lo", "que"),
]


@dataclass
class CaptionGroup:
    """Represents a synchronized caption group ready for After Effects & NLE export."""

    index: int
    text: str
    start: float
    end: float
    word_indices: List[int]
    word_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GroupingValidationError(Exception):
    """Raised when grouped captions violate word sequence, coverage, or timing rules."""

    pass


def format_timestamp_srt(seconds: float) -> str:
    """Format seconds into SRT timestamp HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3600000
    remainder = total_ms % 3600000
    minutes = remainder // 60000
    remainder = remainder % 60000
    secs = remainder // 1000
    ms = remainder % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def bridge_caption_gaps(
    groups: List[CaptionGroup],
    max_bridge_gap: float = 0.35,
) -> List[CaptionGroup]:
    """Eliminates visual flicker and micro-blank spaces between adjacent captions.

    If the gap between caption[i].end and caption[i+1].start is <= max_bridge_gap
    (e.g. <= 0.35 seconds / ~10 frames), snap caption[i].end to caption[i+1].start.
    If the gap is > max_bridge_gap, preserve the natural breath / silence blank space.
    """
    if not groups or len(groups) <= 1:
        return groups

    for i in range(len(groups) - 1):
        cur_group = groups[i]
        next_group = groups[i + 1]

        gap = next_group.start - cur_group.end
        # Snap adjacent or micro gaps up to max_bridge_gap (e.g. 0.35s)
        if 0.0 < gap <= max_bridge_gap:
            cur_group.end = round(next_group.start, 3)

    return groups


def generate_srt(groups: List[CaptionGroup]) -> str:
    """Generates standard SubRip (.srt) subtitle string from caption groups.

    Compatible with CapCut, Adobe Premiere Pro, Final Cut Pro, DaVinci Resolve.
    """
    blocks: List[str] = []
    for i, g in enumerate(groups, start=1):
        start_str = format_timestamp_srt(g.start)
        end_str = format_timestamp_srt(g.end)
        blocks.append(f"{i}\n{start_str} --> {end_str}\n{g.text.strip()}\n")
    return "\n".join(blocks).strip() + "\n"


def _clean_word(text: str) -> str:
    """Helper to strip punctuation and lowercase a word token for phrase matching."""
    return re.sub(r"[^\w]", "", text.strip().lower())


def _ends_sentence(text: str) -> bool:
    """Helper to detect sentence end punctuation (. ! ?)."""
    return any(text.rstrip().endswith(p) for p in [".", "!", "?"])


def _is_dramatic_single_word_pause(
    indices: List[int],
    tokens: List[WordToken],
    pause_threshold: float = 0.40,
) -> bool:
    """Detects if a single word has a significant acoustic pause / silence before and/or after it,
    or is a recognized reaction/affirmation word surrounded by silences (e.g. '... Yes ...').
    """
    if len(indices) != 1 or not tokens:
        return False
    w_idx = indices[0]
    if w_idx < 0 or w_idx >= len(tokens):
        return False

    tok = tokens[w_idx]

    # Check pause before
    if w_idx > 0:
        pause_before = max(0.0, tok.start - tokens[w_idx - 1].end)
    else:
        pause_before = tok.start

    # Check pause after
    if w_idx < len(tokens) - 1:
        pause_after = max(0.0, tokens[w_idx + 1].start - tok.end)
    else:
        pause_after = 1.0

    # Common reaction / affirmation words (English, Spanish, Indonesian)
    clean = _clean_word(tok.text)
    is_reaction_word = clean in {
        # English
        "yes", "no", "yeah", "yep", "nope", "exactly",
        "absolutely", "never", "always", "why", "right",
        "sure", "true", "false", "nothing", "now", "stop", "wait", "ok", "okay",
        "definitely", "totally", "correct", "indeed",
        # Spanish
        "sí", "si", "claro", "exacto", "exactamente", "nada", "jamás", "jamas",
        "nunca", "verdad", "cierto", "obvio", "bueno",
        # Indonesian
        "ya", "tidak", "betul", "benar", "pasti", "tentu", "tepat",
    }

    # If it's a reaction word with pause >= 0.35s either before or after
    if is_reaction_word and (pause_before >= 0.35 or pause_after >= 0.35):
        return True

    # General word: significant silence both before and after (or ends sentence with pause)
    prev_ends = _ends_sentence(tokens[w_idx - 1].text) if w_idx > 0 else True
    if pause_after >= pause_threshold and (pause_before >= pause_threshold or prev_ends):
        return True

    if pause_before >= pause_threshold and (pause_after >= pause_threshold or _ends_sentence(tok.text)):
        return True

    return False


def validate_caption_groups(
    groups: List[CaptionGroup],
    tokens: List[WordToken],
    mode: Optional[Union[GroupingMode, str]] = None,
) -> Tuple[bool, str]:
    """Strictly validates caption groupings against the original word tokens and selected mode.

    Ensures:
    1. Every token index [0 .. N-1] is present exactly once, in ascending order.
    2. No words are dropped, duplicated, or reordered.
    3. Group start time matches first word start; end time matches last word end.
    4. Chronological order is preserved.
    5. Word counts strictly satisfy the selected mode constraints:
       - Single Word: exactly 1 word
       - Short: 2 to 4 words (MINIMUM 2 words, NO 1-word groups if total >= 2)
       - Long: 2 to 6 words (MINIMUM 2 words, NO 1-word groups if total >= 2)
    """
    if not tokens:
        if not groups:
            return True, "Valid empty caption set"
        return False, "Input tokens are empty but groups were returned."

    if not groups:
        return False, "No caption groups generated from non-empty tokens."

    flattened_indices: List[int] = []
    prev_end = -1.0

    mode_rules: Optional[ModeRules] = None
    if mode:
        mode_rules = get_mode_rules(mode)

    for i, g in enumerate(groups, start=1):
        if not g.word_indices:
            return False, f"Group {i} has empty word indices."

        # Chronological order check
        if g.start < 0 or g.end < g.start:
            return (
                False,
                f"Group {i} has invalid time range: [{g.start}s - {g.end}s]",
            )

        if g.start < prev_end - 0.05:  # Allow 50ms tolerance for minor speech overlap
            return (
                False,
                f"Group {i} starts at {g.start}s before previous group ends at {prev_end}s",
            )
        prev_end = g.end

        # Check timing against underlying tokens
        first_tok = tokens[g.word_indices[0]]
        last_tok = tokens[g.word_indices[-1]]
        if abs(g.start - first_tok.start) > 0.001:
            return (
                False,
                f"Group {i} start {g.start} does not match token start {first_tok.start}",
            )
        # End must not truncate the last word prematurely (can extend if gap bridged up to next start)
        if g.end < last_tok.end - 0.001:
            return (
                False,
                f"Group {i} end {g.end} is earlier than token end {last_tok.end}",
            )

        # Check word text integrity
        expected_text = " ".join(tokens[idx].text for idx in g.word_indices)
        if g.text.strip() != expected_text.strip():
            return (
                False,
                f"Group {i} text mismatch.\nExpected: '{expected_text}'\nGot: '{g.text}'",
            )

        # Mode-specific constraints check
        if mode_rules:
            if mode_rules.mode == GroupingMode.SINGLE_WORD:
                if g.word_count != 1:
                    return (
                        False,
                        f"Single Word mode violation: Group {i} has {g.word_count} words instead of 1.",
                    )
            elif mode_rules.mode in (GroupingMode.SHORT, GroupingMode.LONG):
                if len(tokens) >= mode_rules.min_tolerance and g.word_count < mode_rules.min_tolerance:
                    # Allow a 1-word group if it is a standalone sentence ending with '.', '!', '?'
                    # OR if it is an explicit enumeration / point item ending with ',', ':', ';'
                    is_standalone_sentence = bool(g.word_indices) and any(tokens[g.word_indices[-1]].text.rstrip().endswith(p) for p in [".", "!", "?"])
                    is_enumeration_point = bool(g.word_indices) and any(tokens[g.word_indices[-1]].text.rstrip().endswith(p) for p in [",", ":", ";"]) and (
                        (i > 1 and any(tokens[groups[i - 2].word_indices[-1]].text.rstrip().endswith(p) for p in [",", ":", ";", "."])) or
                        (i < len(groups) and any(tokens[groups[i].word_indices[-1]].text.rstrip().endswith(p) for p in [",", ":", ";", "."]))
                    )
                    is_dramatic_pause = _is_dramatic_single_word_pause(g.word_indices, tokens)
                    if not (is_standalone_sentence or is_enumeration_point or is_dramatic_pause):
                        return (
                            False,
                            f"{mode_rules.mode.value} mode violation: Group {i} ('{g.text}') has only {g.word_count} word(s). Minimum {mode_rules.min_tolerance} words required (no orphan words).",
                        )
                if g.word_count > mode_rules.max_tolerance:
                    return (
                        False,
                        f"{mode_rules.mode.value} mode violation: Group {i} has {g.word_count} words, exceeding tolerance of {mode_rules.max_tolerance}.",
                    )

        # Kinetic typography rule: never cross a sentence boundary mid-group
        if mode_rules and mode_rules.mode != GroupingMode.SINGLE_WORD:
            for w_idx in g.word_indices[:-1]:
                if any(tokens[w_idx].text.rstrip().endswith(p) for p in [".", "!", "?"]):
                    return (
                        False,
                        f"Kinetic typography rule violation: Group {i} crosses a sentence boundary after '{tokens[w_idx].text}'.",
                    )

        # Kinetic typography rule: never split known compound proper nouns across adjacent groups (Short & Long mode)
        if mode_rules and mode_rules.mode != GroupingMode.SINGLE_WORD and i < len(groups):
            next_g = groups[i]
            if g.word_indices and next_g.word_indices:
                w_last = _clean_word(tokens[g.word_indices[-1]].text)
                w_first = _clean_word(tokens[next_g.word_indices[0]].text)
                for c1, c2 in KNOWN_COMPOUNDS:
                    if w_last == c1 and w_first == c2:
                        return (
                            False,
                            f"Kinetic typography rule violation: Compound '{c1} {c2}' split between Group {i} and Group {i+1}.",
                        )

        flattened_indices.extend(g.word_indices)

    # Check complete coverage and order
    expected_indices = list(range(len(tokens)))
    if flattened_indices != expected_indices:
        missing = set(expected_indices) - set(flattened_indices)
        duplicated = [
            x for x in flattened_indices if flattened_indices.count(x) > 1
        ]
        return (
            False,
            f"Word index sequence mismatch. Missing: {sorted(list(missing))}, Duplicated: {list(set(duplicated))}",
        )

    return True, "All validation checks passed."


def group_single_word(tokens: List[WordToken]) -> List[CaptionGroup]:
    """Generates exactly one caption group per recognized word."""
    groups: List[CaptionGroup] = []
    for i, tok in enumerate(tokens):
        groups.append(
            CaptionGroup(
                index=i + 1,
                text=tok.text.strip(),
                start=tok.start,
                end=tok.end,
                word_indices=[i],
                word_count=1,
            )
        )
    return groups


def _is_compound_boundary(tokens: List[WordToken], current_idx: int) -> bool:
    """Checks if current_idx and current_idx + 1 form a known compound phrase."""
    if current_idx >= len(tokens) - 1:
        return False
    w1 = _clean_word(tokens[current_idx].text)
    w2 = _clean_word(tokens[current_idx + 1].text)
    for c1, c2 in KNOWN_COMPOUNDS:
        if w1 == c1 and w2 == c2:
            return True
    return False


def _get_compound_chain_length(tokens: List[WordToken], start_idx: int) -> int:
    """Returns the length of a compound chain starting at start_idx (minimum 1)."""
    curr = start_idx
    while curr < len(tokens) - 1:
        w1 = _clean_word(tokens[curr].text)
        w2 = _clean_word(tokens[curr + 1].text)
        if any(c1 == w1 and c2 == w2 for c1, c2 in KNOWN_COMPOUNDS):
            curr += 1
        else:
            break
    return (curr - start_idx) + 1


def _split_sentence_boundaries_in_raw_indices(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
) -> List[List[int]]:
    """Splits any raw group that crosses a sentence boundary (. ! ?) mid-phrase."""
    out: List[List[int]] = []
    for g in raw_groups_indices:
        current: List[int] = []
        for idx in g:
            current.append(idx)
            tok = tokens[idx]
            if _ends_sentence(tok.text):
                if idx != g[-1]:
                    out.append(list(current))
                    current = []
        if current:
            out.append(list(current))
    return out


def _repair_compound_splits(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
    rules: ModeRules,
) -> List[List[int]]:
    """Repairs any known compound word or compound chain split across adjacent groups."""
    groups = [list(g) for g in raw_groups_indices if g]
    for i in range(len(groups) - 1):
        if not groups[i] or not groups[i + 1]:
            continue
        w_last = _clean_word(tokens[groups[i][-1]].text)
        w_first = _clean_word(tokens[groups[i + 1][0]].text)
        for c1, c2 in KNOWN_COMPOUNDS:
            if w_last == c1 and w_first == c2:
                # Compound split detected across groups[i] and groups[i+1]
                # Option 2 Check first (Backward move):
                # If c2 ends with a comma (e.g. "club,") or moving c2 backward keeps groups[i] <= max_tolerance
                # and leaves groups[i+1] valid (or collapses it if empty), move c2 backward so group i ends cleanly!
                c2_ends_comma = tokens[groups[i + 1][0]].text.rstrip().endswith(",")
                can_move_c2_back = (
                    len(groups[i]) + 1 <= rules.max_tolerance
                    and (len(groups[i + 1]) - 1 >= rules.min_tolerance or len(groups[i + 1]) <= 1)
                )
                if c2_ends_comma and can_move_c2_back:
                    if len(groups[i + 1]) <= 1:
                        groups[i].extend(groups[i + 1])
                        groups[i + 1] = []
                    else:
                        borrowed = groups[i + 1].pop(0)
                        groups[i].append(borrowed)
                    break

                # Option 1: Move c1 (and any preceding words in the same compound chain / preposition) forward to groups[i+1]
                chain_prefix = [groups[i].pop()]
                while groups[i]:
                    prev_w = _clean_word(tokens[groups[i][-1]].text)
                    curr_head = _clean_word(tokens[chain_prefix[0]].text)
                    if any(cp1 == prev_w and cp2 == curr_head for cp1, cp2 in KNOWN_COMPOUNDS):
                        chain_prefix.insert(0, groups[i].pop())
                    else:
                        break
                if groups[i] and _clean_word(tokens[groups[i][-1]].text) in {"of", "in", "to", "for", "with", "at", "by", "the", "a"}:
                    if len(groups[i]) - 1 >= rules.min_tolerance:
                        chain_prefix.insert(0, groups[i].pop())

                if len(groups[i]) >= rules.min_tolerance and len(groups[i + 1]) + len(chain_prefix) <= rules.max_tolerance:
                    groups[i + 1] = chain_prefix + groups[i + 1]
                else:
                    # Put back prefix into groups[i] and try Option 2: Move c2 backward to groups[i]
                    groups[i].extend(chain_prefix)
                    if len(groups[i]) + 1 <= rules.max_tolerance and (len(groups[i + 1]) - 1 >= rules.min_tolerance or len(groups[i + 1]) <= 1):
                        if len(groups[i + 1]) <= 1:
                            groups[i].extend(groups[i + 1])
                            groups[i + 1] = []
                        else:
                            borrowed = groups[i + 1].pop(0)
                            groups[i].append(borrowed)
                break
    return [g for g in groups if g]


def _repair_comma_splits(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
    rules: ModeRules,
) -> List[List[int]]:
    """Repairs awkward mid-phrase comma splits (e.g. 'Two markets, one' -> 'Two markets,' and 'one ...').

    Also repairs stranded leading comma words (e.g. Group i starts with 'club,' because the previous group cut before the comma).
    """
    groups = [list(g) for g in raw_groups_indices if g]

    # Pass 1: If group i starts with a word ending with a comma (e.g. 'club,'),
    # and previous group didn't end a sentence, move it backward into group i-1 if it fits max_tolerance.
    i = 1
    while i < len(groups):
        if groups[i] and tokens[groups[i][0]].text.rstrip().endswith(","):
            prev_ends_sentence = _ends_sentence(tokens[groups[i - 1][-1]].text)
            if not prev_ends_sentence and len(groups[i - 1]) + 1 <= rules.max_tolerance:
                moved_word = groups[i].pop(0)
                groups[i - 1].append(moved_word)
                if not groups[i]:
                    groups.pop(i)
                    continue
        i += 1

    # Pass 2: If a group has a comma before its end and is not a compact enumeration list,
    # split at the comma if the left portion meets min_tolerance, and pass trailing words
    # to the next group (or create a new group if valid).
    i = 0
    while i < len(groups):
        g = groups[i]
        comma_positions = [
            pos for pos in range(len(g) - 1)
            if tokens[g[pos]].text.rstrip().endswith(",")
        ]

        word_texts = [tokens[idx].text for idx in g]
        comma_count = sum(1 for w in word_texts if w.rstrip().endswith(","))
        # Skip if it is a short list enumeration, e.g. "House, hotel, apartment"
        if comma_count >= 2 and len(g) <= 4:
            i += 1
            continue

        if comma_positions:
            split_pos = comma_positions[-1]
            left = g[:split_pos + 1]
            right = g[split_pos + 1:]

            # DO NOT split at comma if right side contains or ends with a sentence terminator (., !, ?)
            # because passing right to the next group would push a sentence end across into a new sentence!
            right_has_sentence_end = any(tokens[idx].text.rstrip().endswith(p) for idx in right for p in [".", "!", "?"])
            if right_has_sentence_end:
                i += 1
                continue

            if len(left) >= rules.min_tolerance:
                # If the group ends with a comma (closed enumeration) and left side is < 3 words while entire group <= target_max,
                # KEEP the short points together in 1 group so they don't flicker awkwardly!
                group_ends_comma = tokens[g[-1]].text.rstrip().endswith(",")
                if group_ends_comma and len(left) < 3 and len(g) <= rules.target_max:
                    i += 1
                    continue

                if i + 1 < len(groups):
                    if len(right) + len(groups[i + 1]) <= rules.max_tolerance:
                        groups[i] = left
                        groups[i + 1] = right + groups[i + 1]
                        i += 1
                        continue
                    elif len(right) >= rules.min_tolerance:
                        groups[i] = left
                        groups.insert(i + 1, right)
                        i += 2
                        continue
                elif len(right) >= rules.min_tolerance:
                    groups[i] = left
                    groups.append(right)
                    break
        i += 1
    return [g for g in groups if g]


def _merge_short_enumeration_groups(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
    rules: ModeRules,
) -> List[List[int]]:
    """Merges adjacent short enumeration groups (< 3 words each) that both end in commas

    into a single group (e.g. 'tennis courts,' + 'swimming pools,' -> 'tennis courts, swimming pools,').
    Groups with >= 3 words (e.g. 'beachfront fire pits,') are preserved as independent lines.
    """
    if len(raw_groups_indices) <= 1:
        return raw_groups_indices

    merged: List[List[int]] = []
    i = 0
    while i < len(raw_groups_indices):
        curr = raw_groups_indices[i]
        if i + 1 < len(raw_groups_indices):
            nxt = raw_groups_indices[i + 1]
            curr_ends_comma = bool(curr) and tokens[curr[-1]].text.rstrip().endswith(",")
            nxt_ends_comma = bool(nxt) and (
                tokens[nxt[-1]].text.rstrip().endswith(",") or
                (len(nxt) <= 3 and any(tokens[nxt[-1]].text.rstrip().endswith(p) for p in [".", "!", "?"]))
            )
            both_short = len(curr) < 3 and len(nxt) < 3
            fits_target = len(curr) + len(nxt) <= rules.target_max

            if curr_ends_comma and nxt_ends_comma and both_short and fits_target:
                merged.append(curr + nxt)
                i += 2
                continue

        merged.append(curr)
        i += 1
    return merged


def _split_oversized_groups(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
    rules: ModeRules,
) -> List[List[int]]:
    """Splits any group that exceeds rules.max_tolerance into balanced sub-groups (e.g. 5+3, 5+4, 5+5).

    Ensures every sub-group meets rules.min_tolerance and does not exceed rules.max_tolerance.
    Protects known compound phrases and sentence boundaries from being split.
    """
    out: List[List[int]] = []
    for g in raw_groups_indices:
        if len(g) <= rules.max_tolerance:
            out.append(list(g))
            continue

        remaining = list(g)
        while len(remaining) > rules.max_tolerance:
            target_cut = min(rules.target_max, max(rules.min_tolerance, len(remaining) // 2))

            best_cut = target_cut
            candidates = [
                target_cut,
                target_cut + 1,
                target_cut - 1,
                target_cut + 2,
                target_cut - 2,
            ]
            for cand in candidates:
                if rules.min_tolerance <= cand <= len(remaining) - rules.min_tolerance and cand <= rules.max_tolerance:
                    w1 = _clean_word(tokens[remaining[cand - 1]].text)
                    w2 = _clean_word(tokens[remaining[cand]].text)
                    if any(c1 == w1 and c2 == w2 for c1, c2 in KNOWN_COMPOUNDS):
                        continue
                    if _clean_word(tokens[remaining[cand - 1]].text) not in DANGLING_END_WORDS:
                        best_cut = cand
                        break
                    best_cut = cand

            chunk = remaining[:best_cut]
            remaining = remaining[best_cut:]
            out.append(chunk)

        if remaining:
            if len(remaining) < rules.min_tolerance and out and len(out[-1]) + len(remaining) <= rules.max_tolerance:
                out[-1].extend(remaining)
            else:
                out.append(remaining)
    return out


def _rebalance_and_merge_groups(
    raw_groups_indices: List[List[int]],
    tokens: List[WordToken],
    rules: ModeRules,
) -> List[CaptionGroup]:
    """Post-processes groups to strictly eliminate orphan words (< min_tolerance)

    and builds final CaptionGroup objects.
    """
    if not raw_groups_indices:
        return []

    # If only 1 group or total tokens < min_tolerance, return as-is
    if len(raw_groups_indices) <= 1 or len(tokens) < rules.min_tolerance:
        groups = []
        for idx, indices in enumerate(raw_groups_indices, start=1):
            text = " ".join(tokens[i].text for i in indices)
            groups.append(
                CaptionGroup(
                    index=idx,
                    text=text,
                    start=tokens[indices[0]].start,
                    end=tokens[indices[-1]].end,
                    word_indices=list(indices),
                    word_count=len(indices),
                )
            )
        return groups

    # Work with mutable list of index lists
    groups_list = [list(g) for g in raw_groups_indices if g]

    # Backward pass: resolve single-word groups from right to left
    i = len(groups_list) - 1
    while i >= 0 and len(groups_list) > 1:
        if len(groups_list[i]) < rules.min_tolerance:
            # Standalone sentence or dramatic acoustic pause protection:
            # If this single-word group ends with '.', '!', '?' OR is surrounded by significant pauses (e.g. '... Yes ...'),
            # it must NEVER be merged across the silence gap!
            is_standalone_sentence = any(tokens[idx].text.rstrip().endswith(p) for idx in groups_list[i] for p in [".", "!", "?"])
            is_dramatic_pause = _is_dramatic_single_word_pause(groups_list[i], tokens)

            prev_ends = (i > 0) and _ends_sentence(tokens[groups_list[i - 1][-1]].text)

            pause_before = 0.0
            if i > 0 and groups_list[i] and groups_list[i - 1]:
                pause_before = max(0.0, tokens[groups_list[i][0]].start - tokens[groups_list[i - 1][-1]].end)

            if (is_standalone_sentence or is_dramatic_pause) and (prev_ends or pause_before >= 0.35):
                # Keep as valid standalone dramatic group!
                i -= 1
                continue

            if i > 0 and not prev_ends and pause_before < 0.35:
                # Merge into previous group if fits within max_tolerance
                if len(groups_list[i - 1]) + len(groups_list[i]) <= rules.max_tolerance:
                    groups_list[i - 1].extend(groups_list[i])
                    groups_list.pop(i)
                    i = min(i, len(groups_list) - 1)
                    continue
                # Otherwise, rebalance: borrow a word from previous group if previous has > min_tolerance
                elif len(groups_list[i - 1]) > rules.min_tolerance:
                    borrowed = groups_list[i - 1].pop()
                    groups_list[i].insert(0, borrowed)
                    i -= 1
                    continue
                else:
                    # Previous group also at min_tolerance, force merge
                    groups_list[i - 1].extend(groups_list[i])
                    groups_list.pop(i)
                    i = min(i, len(groups_list) - 1)
                    continue
            else:
                if is_standalone_sentence or is_dramatic_pause:
                    # Previous group ends sentence and this is standalone or dramatic pause (e.g. 'Nothing.', 'Yes').
                    # Keep as a valid standalone sentence group without merging forward into next sentence!
                    i -= 1
                    continue
                # Previous group ends sentence OR this is the first group: merge forward into next group
                if i + 1 < len(groups_list):
                    groups_list[i + 1] = groups_list[i] + groups_list[i + 1]
                    groups_list.pop(i)
                    i = min(i, len(groups_list) - 1)
                    continue
                elif i > 0:
                    # Trailing last word of sentence, merge backward
                    groups_list[i - 1].extend(groups_list[i])
                    groups_list.pop(i)
                    i = min(i, len(groups_list) - 1)
                    continue
        i -= 1

    # Convert to CaptionGroup objects
    final_groups: List[CaptionGroup] = []
    for idx, indices in enumerate(groups_list, start=1):
        text = " ".join(tokens[k].text for k in indices)
        final_groups.append(
            CaptionGroup(
                index=idx,
                text=text,
                start=tokens[indices[0]].start,
                end=tokens[indices[-1]].end,
                word_indices=list(indices),
                word_count=len(indices),
            )
        )
    return final_groups


def heuristic_grouping(
    tokens: List[WordToken],
    mode: Union[GroupingMode, str] = GroupingMode.SHORT,
) -> List[CaptionGroup]:
    """Deterministic, high-precision rule-based fallback caption grouper.

    Splits tokens based on the selected mode:
    - Single Word: exactly 1 word per layer
    - Short: target 2-3 words (tolerance 2-4, NO single words!)
    - Long: target 3-5 words (tolerance 2-7, NO single words!)
    """
    if not tokens:
        return []

    rules = get_mode_rules(mode)

    # Mode A: Single Word
    if rules.mode == GroupingMode.SINGLE_WORD:
        return group_single_word(tokens)

    # Mode B & C: Short and Long
    target_min = rules.target_min
    target_max = rules.target_max
    max_tolerance = rules.max_tolerance
    max_pause_sec = rules.max_pause_sec

    # Identify all compound word boundaries (never split across these indices)
    compound_split_forbidden = set()
    for k in range(len(tokens) - 1):
        w1 = _clean_word(tokens[k].text)
        w2 = _clean_word(tokens[k + 1].text)
        for c1, c2 in KNOWN_COMPOUNDS:
            if w1 == c1 and w2 == c2:
                compound_split_forbidden.add(k)
                break

    raw_groups: List[List[int]] = []
    current_indices: List[int] = []

    for i, tok in enumerate(tokens):
        current_indices.append(i)
        count = len(current_indices)

        is_last_token = i == len(tokens) - 1
        ends_sentence = any(tok.text.rstrip().endswith(p) for p in [".", "!", "?"])
        ends_comma = tok.text.rstrip().endswith(",")
        pause_after = 0.0
        if not is_last_token:
            next_tok = tokens[i + 1]
            pause_after = max(0.0, next_tok.start - tok.end)

        # Lookahead: how many words remain until next sentence boundary or pause?
        words_until_bound = 0
        for j in range(i + 1, len(tokens)):
            words_until_bound += 1
            if any(tokens[j].text.rstrip().endswith(p) for p in [".", "!", "?"]):
                break
            if (
                j < len(tokens) - 1
                and (tokens[j + 1].start - tokens[j].end) >= max_pause_sec
            ):
                break

        should_split = False

        # Protect known compound words: NEVER split in the middle of a compound
        if i in compound_split_forbidden:
            should_split = False
        elif is_last_token:
            should_split = True
        elif ends_sentence or pause_after >= max_pause_sec:
            should_split = True
        elif ends_comma and count >= rules.min_tolerance and words_until_bound >= rules.min_tolerance:
            # Check point length in an enumeration:
            # If current point has < 3 words, and next words form another short point (< 3 words)
            # that together fit within target_max, do NOT split early! Let them combine into a 4-5 word line.
            # But if current point already has >= 3 words, it is substantial -> split now!
            if count < 3 and not is_last_token:
                next_point_len = 0
                for k in range(i + 1, len(tokens)):
                    next_point_len += 1
                    if tokens[k].text.rstrip().endswith(",") or any(tokens[k].text.rstrip().endswith(p) for p in [".", "!", "?"]):
                        break
                if 1 <= next_point_len < 3 and (count + next_point_len <= target_max):
                    should_split = False
                else:
                    should_split = True
            else:
                should_split = True
        elif not is_last_token and tokens[i + 1].text.rstrip().endswith(",") and (count + 1 <= max_tolerance):
            # Lookahead comma absorption: If next word ends with a comma and count + 1 <= max_tolerance,
            # DO NOT split early! Absorb the comma word into current group so it closes neatly on the comma.
            should_split = False
        elif (
            count >= target_min
            and getattr(tok, "emphasis_score", 0.0) >= 1.1
            and pause_after >= 0.18
        ):
            # Secondary Acoustic Rule: Natural cadence release after an emphasized anchor word
            should_split = True
        elif (
            count < target_max
            and not is_last_token
            and getattr(tokens[i + 1], "emphasis_score", 0.0) >= 1.3
            and (count + 2 <= max_tolerance)
        ):
            # Secondary Acoustic Rule: Anchor protection (do not cut immediately before a strong anchor word)
            should_split = False
        next_chain_len = _get_compound_chain_length(tokens, i + 1) if not is_last_token else 0
        if not should_split:
            if (
                not is_last_token
                and next_chain_len > 1
                and (count + next_chain_len > max_tolerance)
                and count >= rules.min_tolerance
            ):
                # Next words form a compound chain and adding them would exceed tolerance -> split now!
                should_split = True
            elif (
                not is_last_token
                and _clean_word(tokens[i + 1].text) in {"of", "with", "in", "at", "to", "for"}
                and _get_compound_chain_length(tokens, i + 2) > 1
                and (count + 1 + _get_compound_chain_length(tokens, i + 2) > max_tolerance)
                and count >= rules.min_tolerance
            ):
                # Next word is a preposition opening a compound chain -> split now!
                should_split = True
            elif count >= max_tolerance:
                should_split = True
            elif (
                count >= target_min
                and words_until_bound == 1
                and (count + 1 <= max_tolerance)
                and not (not is_last_token and _is_dramatic_single_word_pause([i + 1], tokens))
                and pause_after < max_pause_sec
            ):
                # Absorb a single trailing word before a pause/sentence end to prevent 1-word orphans
                should_split = False
            elif count >= target_max:
                # Reached target max: split unless current word is dangling and tolerance permits
                text_clean = tok.text.strip().lower()
                word_no_punct = re.sub(r"[^\w]", "", text_clean)
                if word_no_punct in DANGLING_END_WORDS and count < max_tolerance:
                    should_split = False
                else:
                    should_split = True
            elif count >= target_min and not is_last_token:
                # Check if next word begins a natural prepositional or relative phrase
                next_word_clean = _clean_word(tokens[i + 1].text)
                curr_word_clean = _clean_word(tok.text)
                if (
                    next_word_clean in PHRASE_STARTERS
                    and curr_word_clean not in DANGLING_END_WORDS
                    and words_until_bound >= target_min
                ):
                    should_split = True

        if should_split and current_indices:
            raw_groups.append(list(current_indices))
            current_indices = []

    # If any trailing tokens remained, append
    if current_indices:
        raw_groups.append(list(current_indices))

    # Apply strict post-processing pipeline: sentence boundaries, compound repair, comma split repair, short enumeration merging, oversized splitting, and orphan rebalancing
    raw_groups = _split_sentence_boundaries_in_raw_indices(raw_groups, tokens)
    raw_groups = _repair_compound_splits(raw_groups, tokens, rules)
    raw_groups = _repair_comma_splits(raw_groups, tokens, rules)
    raw_groups = _merge_short_enumeration_groups(raw_groups, tokens, rules)
    raw_groups = _split_oversized_groups(raw_groups, tokens, rules)
    return _rebalance_and_merge_groups(raw_groups, tokens, rules)


class LLMGroupingService:
    """Calls an LLM API to group words into natural, readable caption phrases
    according to the selected Caption Grouping Mode.
    """

    def __init__(self):
        self.openai_key = config.openai_api_key
        self.gemini_key = config.gemini_api_key

    def _call_openai(self, prompt: str) -> Dict[str, Any]:
        """Calls OpenAI Chat Completion endpoint using standard library urllib."""
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": config.llm_model or "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional video editor and kinetic typography subtitler. Output only valid JSON.",
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
        """Calls Gemini API endpoint using standard library urllib."""
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

    def group_words(
        self,
        tokens: List[WordToken],
        mode: Union[GroupingMode, str] = GroupingMode.SHORT,
        force_fallback: bool = False,
    ) -> List[CaptionGroup]:
        """Groups words into caption phrases using LLM for the chosen mode,
        with automatic validation and graceful fallback.
        """
        if not tokens:
            return []

        mode_enum = (
            mode
            if isinstance(mode, GroupingMode)
            else GroupingMode.from_string(mode)
        )

        # Mode A: Single Word requires no LLM hallucination risk or token cost
        if mode_enum == GroupingMode.SINGLE_WORD:
            print(
                f"[Grouping] Mode: '{mode_enum.value}' - Generating 1 layer per word directly."
            )
            return group_single_word(tokens)

        # If fallback is forced or no LLM keys are configured, use heuristic grouper
        if force_fallback or not (self.openai_key or self.gemini_key):
            print(
                f"[Grouping] Mode: '{mode_enum.value}' - Using high-precision heuristic fallback."
            )
            return heuristic_grouping(tokens, mode=mode_enum)

        word_list = [f"{t.index}: {t.text}" for t in tokens]
        words_formatted = "\n".join(word_list)
        prompt = build_llm_prompt_for_mode(
            mode_enum, words_formatted, len(tokens)
        )

        llm_response = None

        # Try LLM
        try:
            if self.openai_key:
                print(
                    f"[Grouping] Calling OpenAI ({config.llm_model}) for '{mode_enum.value}' mode..."
                )
                llm_response = self._call_openai(prompt)
            elif self.gemini_key:
                print(
                    f"[Grouping] Calling Gemini API for '{mode_enum.value}' mode..."
                )
                llm_response = self._call_gemini(prompt)
        except Exception as e:
            print(f"[Warning] LLM API call encountered an error: {e}")

        # Assemble groups from LLM response if valid
        if llm_response and "groups" in llm_response:
            try:
                raw_indices = [
                    [int(x) for x in item.get("word_indices", [])]
                    for item in llm_response["groups"]
                    if item.get("word_indices")
                ]
                rules = get_mode_rules(mode_enum)
                # Enforce sentence boundary integrity on LLM raw output
                raw_indices = _split_sentence_boundaries_in_raw_indices(
                    raw_indices, tokens
                )
                # Repair any compound phrases split across groups
                raw_indices = _repair_compound_splits(raw_indices, tokens, rules)
                # Repair any awkward mid-phrase comma splits
                raw_indices = _repair_comma_splits(raw_indices, tokens, rules)
                # Merge short enumeration points (< 3 words) while keeping >= 3 word points independent
                raw_indices = _merge_short_enumeration_groups(raw_indices, tokens, rules)
                # Split any oversized groups > max_tolerance into balanced sub-groups
                raw_indices = _split_oversized_groups(raw_indices, tokens, rules)
                # Rebalance candidate groups to eliminate orphan 1-word groups
                rebalanced_groups = _rebalance_and_merge_groups(
                    raw_indices, tokens, rules
                )

                is_valid, reason = validate_caption_groups(
                    rebalanced_groups, tokens, mode=mode_enum
                )
                if is_valid:
                    print(
                        f"[Grouping] Successfully generated {len(rebalanced_groups)} caption groups via LLM ({mode_enum.value})."
                    )
                    return rebalanced_groups
                else:
                    print(
                        f"[Warning] LLM grouping validation failed: {reason}. Falling back to heuristic."
                    )
            except Exception as e:
                print(
                    f"[Warning] Failed to parse LLM response format: {e}. Falling back to heuristic."
                )

        # Fallback to heuristic grouping
        print(
            f"[Grouping] Safe fallback activated: generating rule-based groups for '{mode_enum.value}'."
        )
        return heuristic_grouping(tokens, mode=mode_enum)
