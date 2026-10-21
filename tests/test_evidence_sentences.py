"""RC-9: deterministic Evidence sentence segmentation for ID citations."""

from __future__ import annotations

import re
import unittest

from src.weekly_report.evidence_sentences import cited_text, resolve_sentence_ids, segment_evidence_sentences


class EvidenceSentenceTests(unittest.TestCase):
    def _texts(self, content):
        sentences = segment_evidence_sentences(content)
        for sentence in sentences:
            self.assertEqual(content[sentence.start:sentence.end], sentence.text)
        self.assertEqual(re.sub(r"\s", "", content), re.sub(r"\s", "", "".join(s.text for s in sentences)))
        self.assertEqual([s.sentence_id for s in sentences], [f"S{i}" for i in range(1, len(sentences) + 1)])
        return [s.text for s in sentences]

    def test_english_sentences_keep_abbreviations_decimals_and_numbers(self):
        self.assertEqual(
            self._texts("St. Louis opened an 8.4 km line. The five lines, namely No. 1, 2 and 8, include depots! Done?"),
            ["St. Louis opened an 8.4 km line.", "The five lines, namely No. 1, 2 and 8, include depots!", "Done?"],
        )

    def test_lowercase_continuation_and_initials_do_not_split(self):
        self.assertEqual(self._texts("It ran at 12.30 p.m. on Saturday. J. Smith said so."), ["It ran at 12.30 p.m. on Saturday.", "J. Smith said so."])

    def test_cjk_korean_and_line_breaks(self):
        self.assertEqual(self._texts("電車出軌。「已調查。」\n下一段"), ["電車出軌。", "「已調查。」", "下一段"])
        self.assertEqual(self._texts("급행열차를 늘린다. 버스도 도입한다."), ["급행열차를 늘린다.", "버스도 도입한다."])

    def test_resolution_rejects_unknown_repeated_and_empty_ids(self):
        sentences = segment_evidence_sentences("One. Two. Three.")
        self.assertEqual(cited_text(resolve_sentence_ids(sentences, ["S3", "S1"])), "One. Three.")
        for ids in ([], ["S4"], ["S1", "S1"], [1]):
            self.assertIsNone(resolve_sentence_ids(sentences, ids))


if __name__ == "__main__":
    unittest.main()
