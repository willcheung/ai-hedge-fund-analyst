# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from public_content import clean_narrative

class PublicPlaceholderTests(unittest.TestCase):
    def test_explicit_legacy_research_placeholder_is_plain(self):
        self.assertEqual(clean_narrative('SYNTHT - X Signal Stub'),'SYNTHT - Research incomplete')
        self.assertEqual(clean_narrative('Market Cap: TBD; Exchange: TBD'),'Market capitalization unavailable; Exchange unavailable')
    def test_ordinary_company_names_and_real_values_are_preserved(self):
        self.assertEqual(clean_narrative('Synthetic Stub Company reported revenue of USD 5 billion.'),'Synthetic Stub Company reported revenue of USD 5 billion.')
        self.assertEqual(clean_narrative('Market Cap: $25B; Exchange: NYSE'),'Market Cap: $25B; Exchange: NYSE')
