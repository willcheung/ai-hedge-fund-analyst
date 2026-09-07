# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Named-owner public boundary regressions; synthetic examples only."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import clean_narrative, sanitize_legacy, PRIVATE


class PublicIdentityTests(unittest.TestCase):
    def test_owner_units_withheld_not_renamed_as_public_advice(self):
        for text in [
            'By Rowan Example', 'By Rowan', 'Author: Rowan',
            "Rowan's current holdings are private.", 'Rowan’s asymmetric framework.',
            'Rowan-style small-cap strategy.', '| Rowan (manual) | THESIS | Direct |',
            '| Rowan (portfolio/watchlist) | HOLDING | Portfolio |',
            'Rowan already owns 123 EXAMPLE shares.', 'Rowan should hold existing exposure.',
            'Rowan asked to prioritize the next research run.',
            'Trim optional if Rowan wants to reduce speculative beta.',
            'Prefer this if Rowan insists on a speculative sleeve.',
            'Execution friction for Rowan versus alternatives.',
            'It diversifies Rowan away from concentrated exposure.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(clean_narrative(text), '')
                self.assertEqual(sanitize_legacy({'summary': text})['summary'], '')

    def test_modal_word_and_factual_third_party_names_survive(self):
        for text in [
            'Revenue will grow if demand holds.',
            'Will revenue grow if demand holds?',
            'Example debate: Who Will Explain The Test?',
            'Will Fictional discussed the film.',
            'Will Imaginary discussed company earnings.',
            "Will Imaginary's outlook remains cautious.",
            'By Will Fictional',
        ]:
            with self.subTest(text=text):
                self.assertFalse(PRIVATE.search(text))
                self.assertEqual(clean_narrative(text), text)

    def test_company_numbers_survive_separate_owner_unit(self):
        text = "Rowan's current holdings are private. Revenue was $123 million."
        self.assertEqual(clean_narrative(text), 'Revenue was $123 million.')

    def test_full_name_is_unsafe_in_structural_fields(self):
        self.assertEqual(sanitize_legacy({'id': 'rowan-example'}), {'id': ''})


if __name__ == '__main__':
    unittest.main()
