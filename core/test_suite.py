"""Comprehensive Test Suite for AI Caption Generator.

Tests:
1. All three Caption Grouping Modes (Single Word, Short, Long) on identical transcripts.
2. Single Word mode produces exactly 1 word per layer with matching timestamps.
3. Short mode produces predominantly 2-3 words (tolerance 1-4).
4. Long mode produces predominantly 4-5 words (tolerance 2-7).
5. Mode switching produces distinctly different layer counts and structures.
6. Zero lost, duplicated, or reordered words in all modes.
7. Mode constraint violation detection in validator.
8. Non-overlapping layer intervals.
9. Edge cases: missing timestamps, empty token list, dropped words, invented timestamps.
"""

import json
from pathlib import Path
import unittest

from grouping_rules import GroupingMode, get_mode_rules
from grouping_service import (
    CaptionGroup,
    heuristic_grouping,
    validate_caption_groups,
)
from stt_service import MockSTTProvider, WordToken


class TestCaptionGenerator(unittest.TestCase):

    def setUp(self):
        sample_path = Path(__file__).parent / "test_data" / "sample_words.json"
        with open(sample_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        self.tokens = [
            WordToken(
                text=item["text"],
                start=item["start"],
                end=item["end"],
                index=i,
            )
            for i, item in enumerate(raw_data)
        ]

    def test_mock_stt_provider(self):
        """Verify MockSTTProvider returns valid WordTokens."""
        provider = MockSTTProvider()
        tokens = provider.transcribe()
        self.assertEqual(len(tokens), 21)
        self.assertEqual(tokens[0].text, "Welcome")
        self.assertEqual(tokens[0].index, 0)
        self.assertLess(tokens[0].start, tokens[0].end)

    # -------------------------------------------------------------
    # MODE A: Single Word Mode Tests
    # -------------------------------------------------------------
    def test_mode_single_word(self):
        """Verify Single Word mode produces exactly 1 word per caption group with matching timestamps."""
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SINGLE_WORD)

        # 1. Total groups must equal total tokens
        self.assertEqual(
            len(groups),
            len(self.tokens),
            "Single Word mode must produce exactly one caption group per word.",
        )

        # 2. Each group must contain exactly 1 word
        for i, g in enumerate(groups):
            self.assertEqual(
                g.word_count,
                1,
                f"Group {g.index} has {g.word_count} words instead of 1.",
            )
            self.assertEqual(g.word_indices, [i])
            self.assertEqual(g.text, self.tokens[i].text)
            self.assertAlmostEqual(g.start, self.tokens[i].start, places=3)
            self.assertAlmostEqual(g.end, self.tokens[i].end, places=3)

        # 3. Validation must pass
        is_valid, reason = validate_caption_groups(
            groups, self.tokens, mode=GroupingMode.SINGLE_WORD
        )
        self.assertTrue(is_valid, msg=f"Validation failed: {reason}")

    # -------------------------------------------------------------
    # MODE B: Short Mode Tests (Target 2-3 words, tolerance 1-4)
    # -------------------------------------------------------------
    def test_mode_short(self):
        """Verify Short mode predominantly produces 2-3 words per group within 1-4 tolerance."""
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        self.assertGreater(len(groups), 0)

        # Verify word counts stay strictly within 1-4 tolerance
        target_count = 0
        for g in groups:
            self.assertGreaterEqual(
                g.word_count,
                1,
                f"Group {g.index} has fewer than 1 word ({g.text})",
            )
            self.assertLessEqual(
                g.word_count,
                4,
                f"Group {g.index} exceeds 4-word tolerance ({g.text})",
            )
            if 2 <= g.word_count <= 3:
                target_count += 1

        # Most groups should be 2-3 words
        target_ratio = target_count / len(groups)
        self.assertGreaterEqual(
            target_ratio,
            0.60,
            f"Expected at least 60% of groups in Short mode to be 2-3 words; got {target_ratio:.1%}",
        )

        # Average words should be around 2-3
        avg_words = sum(g.word_count for g in groups) / len(groups)
        self.assertTrue(
            1.8 <= avg_words <= 3.2, f"Average words for Short was {avg_words}"
        )

        # Validation check
        is_valid, reason = validate_caption_groups(
            groups, self.tokens, mode=GroupingMode.SHORT
        )
        self.assertTrue(is_valid, msg=f"Validation failed: {reason}")

    # -------------------------------------------------------------
    # MODE C: Long Mode Tests (Target 4-5 words, tolerance 2-7)
    # -------------------------------------------------------------
    def test_mode_long(self):
        """Verify Long mode predominantly produces 4-5 words per group within 2-7 tolerance."""
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.LONG)
        self.assertGreater(len(groups), 0)

        # Verify word counts stay strictly within 2-7 tolerance (allowing 1 at sentence break)
        target_count = 0
        for g in groups:
            self.assertGreaterEqual(
                g.word_count,
                1,
                f"Group {g.index} has fewer than 1 word ({g.text})",
            )
            self.assertLessEqual(
                g.word_count,
                7,
                f"Group {g.index} exceeds 7-word tolerance ({g.text})",
            )
            if 3 <= g.word_count <= 6:
                target_count += 1

        # Most groups should be in the longer range
        target_ratio = target_count / len(groups)
        self.assertGreaterEqual(
            target_ratio,
            0.60,
            f"Expected at least 60% of groups in Long mode to be 3-6 words; got {target_ratio:.1%}",
        )

        # Average words should be higher than Short mode
        avg_words = sum(g.word_count for g in groups) / len(groups)
        self.assertTrue(
            3.5 <= avg_words <= 6.0, f"Average words for Long was {avg_words}"
        )

        # Validation check
        is_valid, reason = validate_caption_groups(
            groups, self.tokens, mode=GroupingMode.LONG
        )
        self.assertTrue(is_valid, msg=f"Validation failed: {reason}")

    # -------------------------------------------------------------
    # Comparative Mode Switching Tests
    # -------------------------------------------------------------
    def test_mode_switching_changes_output(self):
        """Verify changing mode on the same transcript changes grouping count and structure appropriately."""
        single_groups = heuristic_grouping(
            self.tokens, mode=GroupingMode.SINGLE_WORD
        )
        short_groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        long_groups = heuristic_grouping(self.tokens, mode=GroupingMode.LONG)

        # In 21 words: Single Word > Short > Long in layer count
        self.assertEqual(len(single_groups), 21)
        self.assertGreater(
            len(single_groups),
            len(short_groups),
            "Single Word should produce more layers than Short mode",
        )
        self.assertGreater(
            len(short_groups),
            len(long_groups),
            "Short mode should produce more layers than Long mode",
        )

        # All three must preserve the full transcript text
        for mode_name, grps in [
            ("Single", single_groups),
            ("Short", short_groups),
            ("Long", long_groups),
        ]:
            flattened_text = " ".join(g.text for g in grps)
            expected_text = " ".join(t.text for t in self.tokens)
            self.assertEqual(
                flattened_text,
                expected_text,
                f"{mode_name} mode text did not match full transcript.",
            )

    # -------------------------------------------------------------
    # Mode Constraint Violation Detection
    # -------------------------------------------------------------
    def test_mode_violation_detection(self):
        """Verify validate_caption_groups detects mode rule violations."""
        # Single Word mode receiving a multi-word group must fail validation
        short_groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        is_valid, reason = validate_caption_groups(
            short_groups, self.tokens, mode=GroupingMode.SINGLE_WORD
        )
        self.assertFalse(is_valid)
        self.assertIn("Single Word mode violation", reason)

        # Short mode receiving a 5-word group must fail validation
        long_groups = heuristic_grouping(self.tokens, mode=GroupingMode.LONG)
        # Verify if long_groups has any group with >4 words
        if any(g.word_count > 4 for g in long_groups):
            is_valid, reason = validate_caption_groups(
                long_groups, self.tokens, mode=GroupingMode.SHORT
            )
            self.assertFalse(is_valid)
            self.assertIn("Short mode violation", reason)

    # -------------------------------------------------------------
    # General Timing and Integrity Tests
    # -------------------------------------------------------------
    def test_timing_integrity_across_modes(self):
        """Ensure each caption starts exactly at word[0].start and ends at word[-1].end across all modes."""
        for m in [
            GroupingMode.SINGLE_WORD,
            GroupingMode.SHORT,
            GroupingMode.LONG,
        ]:
            groups = heuristic_grouping(self.tokens, mode=m)
            for g in groups:
                expected_start = self.tokens[g.word_indices[0]].start
                expected_end = self.tokens[g.word_indices[-1]].end
                self.assertAlmostEqual(g.start, expected_start, places=3)
                self.assertAlmostEqual(g.end, expected_end, places=3)
                self.assertGreater(g.end, g.start)

    def test_non_overlapping_layers_across_modes(self):
        """Ensure adjacent captions do not overlap unexpectedly in any mode."""
        for m in [
            GroupingMode.SINGLE_WORD,
            GroupingMode.SHORT,
            GroupingMode.LONG,
        ]:
            groups = heuristic_grouping(self.tokens, mode=m)
            for i in range(len(groups) - 1):
                curr_end = groups[i].end
                next_start = groups[i + 1].start
                self.assertGreaterEqual(
                    next_start,
                    curr_end,
                    f"Overlap detected in {m.value}: Group {i+1} ends at {curr_end}s but Group {i+2} starts at {next_start}s",
                )

    def test_missing_timestamps_resilience(self):
        """Check behavior when timestamps are zero or identical."""
        flawed_tokens = [
            WordToken("Zero", 0.0, 0.0, 0),
            WordToken("duration", 0.0, 0.0, 1),
            WordToken("test.", 0.0, 0.0, 2),
        ]
        groups = heuristic_grouping(flawed_tokens, mode=GroupingMode.SHORT)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].text, "Zero duration test.")

    def test_validator_catches_dropped_word(self):
        """Verify the validator catches a dropped word."""
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        groups[0].word_indices.pop()
        groups[0].text = " ".join(
            self.tokens[i].text for i in groups[0].word_indices
        )
        groups[0].end = self.tokens[groups[0].word_indices[-1]].end

        is_valid, reason = validate_caption_groups(
            groups, self.tokens, mode=GroupingMode.SHORT
        )
        self.assertFalse(is_valid)
        self.assertIn("sequence mismatch", reason)

    def test_validator_catches_invented_timestamp(self):
        """Verify the validator catches invented or misaligned timestamps."""
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        groups[0].start = groups[0].start + 0.05

        is_valid, reason = validate_caption_groups(
            groups, self.tokens, mode=GroupingMode.SHORT
        )
        self.assertFalse(is_valid)
        self.assertIn("does not match token start", reason)

    def test_empty_tokens(self):
        """Verify grouping handles empty token list cleanly without crashing."""
        for m in [
            GroupingMode.SINGLE_WORD,
            GroupingMode.SHORT,
            GroupingMode.LONG,
        ]:
            groups = heuristic_grouping([], mode=m)
            self.assertEqual(groups, [])
            is_valid, reason = validate_caption_groups([], [], mode=m)
            self.assertTrue(is_valid)

    def test_timeline_offset_integration(self):
        """Verify adding a timeline offset (Work Area start) shifts all caption timestamps accurately."""
        offset = 12.5
        shifted_tokens = [
            WordToken(
                text=t.text,
                start=round(t.start + offset, 3),
                end=round(t.end + offset, 3),
                index=t.index,
            )
            for t in self.tokens
        ]
        groups = heuristic_grouping(shifted_tokens, mode=GroupingMode.SHORT)
        self.assertGreater(len(groups), 0)
        self.assertAlmostEqual(groups[0].start, self.tokens[0].start + offset, places=3)
        is_valid, reason = validate_caption_groups(groups, shifted_tokens, mode=GroupingMode.SHORT)
        self.assertTrue(is_valid, msg=f"Shifted validation failed: {reason}")

    def test_generate_srt_format(self):
        """Verify SRT format matches SubRip specification (HH:MM:SS,mmm --> HH:MM:SS,mmm)."""
        from grouping_service import generate_srt
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        srt_text = generate_srt(groups)
        self.assertIn("-->", srt_text)
        self.assertIn("00:00:", srt_text)
        self.assertIn(",", srt_text)  # Millisecond comma separator in SRT
        self.assertTrue(srt_text.startswith("1\n"))

    def test_strict_minimum_two_words_in_short_and_long(self):
        """Strict Kinetic Typography rule: no 1-word groups in Short or Long mode."""
        for m in [GroupingMode.SHORT, GroupingMode.LONG]:
            groups = heuristic_grouping(self.tokens, mode=m)
            for g in groups:
                self.assertGreaterEqual(
                    g.word_count,
                    2,
                    f"Mode {m.value} produced a single-word group: '{g.text}'",
                )

    def test_acoustic_stress_enrichment(self):
        """Verify acoustic stress calculation runs without errors and assigns valid scores."""
        from stt_service import enrich_tokens_with_audio_acoustics
        audio_file = Path("/tmp/ae_workarea_audio.aif")
        if audio_file.exists():
            enriched = enrich_tokens_with_audio_acoustics(self.tokens, audio_file)
            self.assertEqual(len(enriched), len(self.tokens))
            self.assertTrue(hasattr(enriched[0], "emphasis_score"))
            self.assertTrue(hasattr(enriched[0], "rms_db"))

    def test_translation_prompt_builder(self):
        """Verify translation prompt builder sets proper rules and 1-to-1 correspondence."""
        from translation_service import build_translation_prompt
        chunks = ["What does your", "Florida look like?"]
        prompt = build_translation_prompt(chunks, "What does your Florida look like?", "id", GroupingMode.SHORT)
        self.assertIn("Bahasa Indonesia", prompt)
        self.assertIn("EXACTLY 2 translated chunks", prompt)
        self.assertIn("Marco Island", prompt)

    def test_translation_service_original_passthrough(self):
        """Verify TranslationService preserves groups without modification when language is original."""
        from translation_service import TranslationService
        groups = heuristic_grouping(self.tokens, mode=GroupingMode.SHORT)
        translator = TranslationService()
        res = translator.translate_groups(groups, target_language="original", mode=GroupingMode.SHORT)
        self.assertEqual(len(res), len(groups))
        self.assertEqual(res[0].text, groups[0].text)
        self.assertEqual(res[0].start, groups[0].start)
        self.assertEqual(res[0].end, groups[0].end)


    def test_intelligent_gap_bridging(self):
        """Verify micro-gaps <= 0.35s snap seamlessly while pauses > 0.35s retain blank space."""
        from grouping_service import bridge_caption_gaps, CaptionGroup
        test_groups = [
            CaptionGroup(1, "First sentence here.", 0.0, 2.0, [0], 3),
            # Gap of 0.70s (> 0.35s) -> must NOT be bridged (retain blank space)
            CaptionGroup(2, "Second sentence starts.", 2.70, 4.0, [1], 3),
            # Gap of 0.05s (<= 0.35s) -> MUST be bridged to 4.05
            CaptionGroup(3, "Continuing immediately.", 4.05, 5.5, [2], 2),
            # Gap of 0.20s (<= 0.35s) -> MUST be bridged to 5.70
            CaptionGroup(4, "Final clause ends.", 5.70, 7.0, [3], 3),
        ]
        bridged = bridge_caption_gaps(test_groups, max_bridge_gap=0.35)

        # 1. First gap (0.70s) should remain unchanged
        self.assertEqual(bridged[0].end, 2.0, "Gap > 0.35s must retain blank space.")
        self.assertEqual(bridged[1].start, 2.70)

        # 2. Second gap (0.05s) should be snapped to 4.05
        self.assertEqual(bridged[1].end, 4.05, "Micro-gap <= 0.35s must snap to next start.")
        self.assertEqual(bridged[2].start, 4.05)

        # 3. Third gap (0.20s) should be snapped to 5.70
        self.assertEqual(bridged[2].end, 5.70, "Micro-gap <= 0.35s must snap to next start.")
        self.assertEqual(bridged[3].start, 5.70)

    def test_compound_chain_real_estate_expert(self):
        """Verify 'real estate expert' is recognized as a compound chain and protected from mid-phrase splits."""
        from grouping_service import _repair_compound_splits, validate_caption_groups
        from grouping_rules import GroupingMode, get_mode_rules
        test_tokens = [
            WordToken("your", 0.0, 0.2, 0),
            WordToken("local", 0.2, 0.4, 1),
            WordToken("Southwest", 0.4, 0.6, 2),
            WordToken("Florida", 0.6, 0.8, 3),
            WordToken("real", 0.8, 1.0, 4),
            WordToken("estate", 1.0, 1.2, 5),
            WordToken("expert", 1.2, 1.4, 6),
            WordToken("and", 1.4, 1.6, 7),
            WordToken("trusted", 1.6, 1.8, 8),
            WordToken("partner", 1.8, 2.0, 9),
        ]
        # Malformed: split after "estate" (Group 1: [0..5], Group 2: [6..9])
        malformed_groups = [
            CaptionGroup(1, "your local Southwest Florida real estate", 0.0, 1.2, [0, 1, 2, 3, 4, 5], 6),
            CaptionGroup(2, "expert and trusted partner", 1.2, 2.0, [6, 7, 8, 9], 4),
        ]
        # Validator must catch compound split violation
        valid, msg = validate_caption_groups(malformed_groups, test_tokens, mode=GroupingMode.LONG)
        self.assertFalse(valid)
        self.assertIn("Compound 'estate expert' split", msg)

        # Repair must pull "real estate" together with "expert and trusted partner"
        rules = get_mode_rules(GroupingMode.LONG)
        repaired_indices = _repair_compound_splits([[0, 1, 2, 3, 4, 5], [6, 7, 8, 9]], test_tokens, rules)
        self.assertEqual(len(repaired_indices), 2)
        # Group 1 should be [0, 1, 2, 3] ("your local Southwest Florida")
        self.assertEqual(repaired_indices[0], [0, 1, 2, 3])
        # Group 2 should be [4, 5, 6, 7, 8, 9] ("real estate expert and trusted partner")
        self.assertEqual(repaired_indices[1], [4, 5, 6, 7, 8, 9])

    def test_repair_comma_splits_two_markets(self):
        """Verify mid-phrase comma drag (e.g. 'Two markets, one' + 'trusted connection.') is cleanly split."""
        from grouping_service import _repair_comma_splits
        from grouping_rules import GroupingMode, get_mode_rules
        test_tokens = [
            WordToken("Two", 0.0, 0.2, 0),
            WordToken("markets,", 0.2, 0.4, 1),
            WordToken("one", 0.4, 0.6, 2),
            WordToken("trusted", 0.6, 0.8, 3),
            WordToken("connection.", 0.8, 1.0, 4),
        ]
        # Raw group: Group 1 has trailing 'one', Group 2 has 'trusted connection.'
        raw_indices = [[0, 1, 2], [3, 4]]
        rules = get_mode_rules(GroupingMode.SHORT)
        repaired = _repair_comma_splits(raw_indices, test_tokens, rules)
        self.assertEqual(len(repaired), 2)
        self.assertEqual(repaired[0], [0, 1])  # 'Two markets,'
        self.assertEqual(repaired[1], [2, 3, 4])  # 'one trusted connection.'


    def test_long_mode_seven_word_safety_net(self):
        """Verify that 7 words pass in Long mode as a safety net, but 8 words trigger a violation."""
        tokens_7 = [WordToken(f"word{i}", float(i), float(i + 0.5), i) for i in range(7)]
        group_7 = [CaptionGroup(1, " ".join(t.text for t in tokens_7), 0.0, 6.5, list(range(7)), 7)]
        is_valid, msg = validate_caption_groups(group_7, tokens_7, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"7 words should be valid in Long mode: {msg}")

        tokens_8 = [WordToken(f"word{i}", float(i), float(i + 0.5), i) for i in range(8)]
        group_8 = [CaptionGroup(1, " ".join(t.text for t in tokens_8), 0.0, 7.5, list(range(8)), 8)]
        is_valid_8, msg_8 = validate_caption_groups(group_8, tokens_8, mode=GroupingMode.LONG)
        self.assertFalse(is_valid_8, "8 words must trigger Long mode violation")
        self.assertIn("Long mode violation", msg_8)


    def test_translation_align_elastic(self):
        """Verify _align_translated_chunks handles indexed objects, missing slots, and count mismatches without dropping to English."""
        from translation_service import TranslationService
        translator = TranslationService()
        mock_groups = [CaptionGroup(i + 1, f"orig_{i}", float(i), float(i + 1), [i], 1) for i in range(10)]

        # Test A: Indexed dict
        data_a = {"translations": [{"index": i, "text": f"id_{i}"} for i in range(10)]}
        res_a = translator._align_translated_chunks(mock_groups, data_a)
        self.assertEqual(len(res_a), 10)
        self.assertEqual(res_a[0], "id_0")
        self.assertEqual(res_a[9], "id_9")

        # Test B: Count mismatch (only 8 items returned for 10 slots) - must elastic-repair without crashing
        data_b = [{"index": 0, "text": "kata satu dan dua"}, {"index": 2, "text": "kata tiga"}]
        res_b = translator._align_translated_chunks(mock_groups, data_b)
        self.assertEqual(len(res_b), 10)
        self.assertTrue(res_b[0].startswith("kata"))
        self.assertTrue(bool(res_b[1]))  # Borrowed or filled, not empty

        # Test C: Flat list with 8 items for 10 groups
        data_c = [f"trans_{i}" for i in range(8)]
        res_c = translator._align_translated_chunks(mock_groups, data_c)
        self.assertEqual(len(res_c), 10)


    def test_safe_urlopen_ssl_fallback(self):
        """Verify safe_urlopen handles SSL verification errors by falling back to unverified context."""
        from unittest.mock import patch, MagicMock
        import urllib.error
        from config import safe_urlopen

        # Mock first call to raise CERTIFICATE_VERIFY_FAILED, second call to succeed
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"success": true}'
        ssl_error = urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        with patch("urllib.request.urlopen", side_effect=[ssl_error, mock_resp]) as mock_urlopen:
            resp = safe_urlopen("https://api.openai.com/test")
            self.assertEqual(mock_urlopen.call_count, 2)
            self.assertEqual(resp, mock_resp)


    def test_standalone_single_word_sentence_allowed_and_not_crossing_boundary(self):
        """Verify that a 1-word sentence ending with punctuation (e.g. 'Nothing.') is valid and does not cross boundaries."""
        tokens = [
            WordToken("We", 0.0, 0.2, 0),
            WordToken("looked", 0.2, 0.4, 1),
            WordToken("for", 0.4, 0.6, 2),
            WordToken("a", 0.6, 0.7, 3),
            WordToken("pool", 0.7, 0.9, 4),
            WordToken("net,", 0.9, 1.1, 5),
            WordToken("nothing.", 1.7, 2.0, 6),
            WordToken("At", 2.6, 2.8, 7),
            WordToken("that", 2.8, 3.0, 8),
            WordToken("point,", 3.0, 3.2, 9),
        ]
        groups = heuristic_grouping(tokens, mode=GroupingMode.LONG)
        is_valid, reason = validate_caption_groups(groups, tokens, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"Validation should pass with standalone sentence: {reason}")
        # Verify no group crosses the sentence boundary after 'nothing.'
        for g in groups:
            for w_idx in g.word_indices[:-1]:
                self.assertNotIn("nothing.", tokens[w_idx].text, "Group must not cross boundary after 'nothing.'")

    def test_beach_club_and_fire_pits_compound_protection(self):
        """Verify 'beach club' and 'fire pits' are protected as compounds and not split into awkward orphan lines."""
        from grouping_service import _repair_compound_splits, _repair_comma_splits, _rebalance_and_merge_groups
        words = [
            "They", "have", "a", "private", "beach", "club,",
            "beachfront", "fire", "pits,",
            "and", "even", "dining", "right", "on", "the", "lawn."
        ]
        tokens = [WordToken(w, i * 0.3, (i + 1) * 0.3, i) for i, w in enumerate(words)]
        rules = get_mode_rules(GroupingMode.LONG)

        # 1. Test Heuristic Grouping directly on this transcript
        groups = heuristic_grouping(tokens, mode=GroupingMode.LONG)
        group_texts = [g.text for g in groups]

        # Verify 'beach club' is never split
        for t in group_texts:
            if "beach" in t and "club" not in t and "beachfront" not in t:
                self.fail(f"'beach' was stranded without 'club': {t}")
            if "fire" in t and "pits" not in t:
                self.fail(f"'fire' was stranded without 'pits': {t}")

        is_valid, reason = validate_caption_groups(groups, tokens, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"Validation failed: {reason}")

        # 2. Test LLM Raw Output Repair Pipeline: simulate the exact awkward split from the screenshot:
        # Group 8 was [0..4] "They have a private beach"
        # Group 9 was [5..8] "club, beachfront fire pits,"
        raw_indices = [
            [0, 1, 2, 3, 4],       # "They have a private beach"
            [5, 6, 7, 8],          # "club, beachfront fire pits,"
            [9, 10, 11, 12, 13, 14, 15] # "and even dining right on the lawn."
        ]
        repaired = _repair_compound_splits(raw_indices, tokens, rules)
        repaired = _repair_comma_splits(repaired, tokens, rules)
        rebalanced = _rebalance_and_merge_groups(repaired, tokens, rules)

        repaired_texts = [g.text for g in rebalanced]
        self.assertEqual(repaired_texts[0], "They have a private beach club,")
        self.assertEqual(repaired_texts[1], "beachfront fire pits,")
        self.assertEqual(repaired_texts[2], "and even dining right on the lawn.")

        val_ok, val_err = validate_caption_groups(rebalanced, tokens, mode=GroupingMode.LONG)
        self.assertTrue(val_ok, f"Repaired groups must pass validation: {val_err}")

    def test_balanced_split_clause_exceeding_seven_words_before_comma(self):
        """Verify a clause with > 7 words before a comma is split into balanced sub-groups (e.g. 5+4 ending in comma)."""
        words = [
            "Through", "our", "deep", "local", "roots", "and", "community", "trusted", "partnership,",
            "we", "deliver", "results."
        ]
        tokens = [WordToken(w, i * 0.3, (i + 1) * 0.3, i) for i, w in enumerate(words)]
        groups = heuristic_grouping(tokens, mode=GroupingMode.LONG)

        # Ensure no group exceeds 7 words
        for g in groups:
            self.assertLessEqual(g.word_count, 7, f"Group '{g.text}' exceeded 7 words")

        # Ensure the group with partnership ends with the comma
        partnership_group = next(g for g in groups if "partnership," in g.text)
        self.assertTrue(partnership_group.text.endswith("partnership,"), f"Expected group to end on comma: {partnership_group.text}")

        is_valid, reason = validate_caption_groups(groups, tokens, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"Validation failed: {reason}")

    def test_single_word_enumeration_points_allowed(self):
        """Verify that single-word list items / enumeration points are permitted in Long and Short mode."""
        tokens = [
            WordToken("Location,", 0.0, 0.5, 0),
            WordToken("Price,", 0.6, 1.1, 1),
            WordToken("Quality.", 1.2, 1.8, 2),
        ]
        groups = [
            CaptionGroup(1, "Location,", 0.0, 0.5, [0], 1),
            CaptionGroup(2, "Price,", 0.6, 1.1, [1], 1),
            CaptionGroup(3, "Quality.", 1.2, 1.8, [2], 1),
        ]
        is_valid, reason = validate_caption_groups(groups, tokens, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"Enumeration points should pass validation: {reason}")

    def test_enumeration_points_short_merged_vs_three_words_separated(self):
        """Verify that short list points (1-2 words) combine into 1 line, while >= 3-word points separate."""
        # 1. Short points (2 words each) should be merged together in one group (4 words)
        short_words = ["Tennis", "courts,", "swimming", "pools,", "and", "cabanas."]
        short_tokens = [WordToken(w, i * 0.3, (i + 1) * 0.3, i) for i, w in enumerate(short_words)]
        groups_short = heuristic_grouping(short_tokens, mode=GroupingMode.LONG)
        texts_short = [g.text for g in groups_short]
        self.assertEqual(texts_short[0], "Tennis courts, swimming pools,")
        self.assertEqual(texts_short[1], "and cabanas.")

        # 2. Substantial points (>= 3 words) should separate cleanly after their comma
        long_words = [
            "They", "have", "a", "private", "beach", "club,",
            "beachfront", "fire", "pits,",
            "and", "even", "dining", "right", "on", "the", "lawn."
        ]
        long_tokens = [WordToken(w, i * 0.3, (i + 1) * 0.3, i) for i, w in enumerate(long_words)]
        groups_long = heuristic_grouping(long_tokens, mode=GroupingMode.LONG)
        texts_long = [g.text for g in groups_long]
        # 'beachfront fire pits,' is 3 words (>= 3) -> must be on its own line
        self.assertIn("beachfront fire pits,", texts_long)

    def test_dramatic_single_word_with_pause_allowed_without_punctuation(self):
        """Verify that a single word surrounded by acoustic silence (e.g. '... Yes ...') stands alone without punctuation."""
        tokens = [
            WordToken("Is", 0.0, 0.2, 0),
            WordToken("this", 0.2, 0.4, 1),
            WordToken("right", 0.4, 0.6, 2),
            # 0.8s silence before, 1.0s silence after, NO period/punctuation on 'Yes'
            WordToken("Yes", 1.4, 1.7, 3),
            WordToken("we", 2.7, 2.9, 4),
            WordToken("know", 2.9, 3.1, 5),
            WordToken("it", 3.1, 3.3, 6),
            WordToken("is.", 3.3, 3.5, 7),
        ]
        groups = heuristic_grouping(tokens, mode=GroupingMode.LONG)
        texts = [g.text for g in groups]

        # Ensure 'Yes' is preserved as its own independent layer
        self.assertIn("Yes", texts, f"'Yes' must stand as its own 1-word layer due to pauses. Got: {texts}")

        # Ensure validation passes in Long mode
        is_valid, reason = validate_caption_groups(groups, tokens, mode=GroupingMode.LONG)
        self.assertTrue(is_valid, f"Validation must pass for dramatic pause: {reason}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
