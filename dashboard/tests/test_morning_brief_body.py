"""Standalone body sanitization with invented prose; no producer or input files."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import morning_brief_markdown


class MorningBriefBodyTests(unittest.TestCase):
    def test_complete_long_body_and_markup_survive(self):
        body = ('# Example outlook\n\n**U.S. demand rose 1.25%. Risks remain.**\n\n'
                '## Evidence\n\n' + ('Demand depends on confirmed orders. ' * 180).strip()
                + '\n\n- 📌 Evidence remains preliminary.\n  Margins could weaken.\n'
                '- [Example filing](https://example.com/evidence)')
        self.assertEqual(morning_brief_markdown(body), body)
        self.assertEqual(morning_brief_markdown(morning_brief_markdown(body)), body)

    def test_private_continuations_withhold_the_complete_item(self):
        for continuation in ('  Our holdings changed.', 'Our holdings changed.',
                             '\n  Our holdings changed.', '\n\tOur holdings changed.',
                             '  - Our holdings changed.'):
            with self.subTest(continuation=continuation):
                body = ('## Evidence\n- Orders rose.\n' + continuation
                        + '\n  Demand could weaken.\n- Costs remain uncertain.')
                self.assertEqual(morning_brief_markdown(body),
                                 '## Evidence\n\n- Costs remain uncertain.')
        ordered = '## Evidence\n3. Orders rose.\n   Demand could weaken.\n4. Costs fell.'
        self.assertEqual(morning_brief_markdown(ordered), ordered)

    def test_private_scopes_and_fences_cannot_create_public_sections(self):
        for scope in ('## Private', '**Holdings**', '## Internal',
                      '## Research Activity / Wiki Updates\n### Private',
                      '## Files written', '## ACTION: WATCH'):
            with self.subTest(scope=scope):
                body = ('# Outlook\n\nCosts remain uncertain.\n\n' + scope
                        + '\n\nWithheld detail.\n\n**Sources checked**\n\n'
                        '[Withheld citation](https://example.com/withheld)')
                self.assertEqual(morning_brief_markdown(body),
                                 '# Outlook\n\nCosts remain uncertain.')
        for fence in ('```', '~~~'):
            self.assertEqual(morning_brief_markdown(
                '## Empty\n' + fence + '\n## False boundary\nHidden text.'), '')

    def test_research_receipt_reset_is_exact(self):
        prefix = '## Research Activity / Wiki Updates\nRoutine receipt.\n\n'
        self.assertEqual(morning_brief_markdown(
            prefix + '**Sources checked**\n\n[Evidence](https://example.com/evidence)'),
            '**Sources checked**\n\n[Evidence](https://example.com/evidence)')
        for heading in ('**Sources**', '**Sources checked:**', '### Sources checked',
                        '**Sources checked privately**'):
            self.assertEqual(morning_brief_markdown(prefix + heading + '\nHidden detail.'), '')

    def test_company_identity_and_existing_public_privacy_boundary(self):
        heading = '### $DEMO — ACTION: closer look'
        evidence = '- Demand grew, but margins remain uncertain.'
        expected = '### $DEMO\n\n' + evidence
        self.assertEqual(morning_brief_markdown(heading + '\n\n' + evidence), expected)
        self.assertEqual(morning_brief_markdown(expected), expected)
        correction = ('January’s official release reports U.S. sales rose 2.25%. '
                      'Demand is **not** assured.')
        item = '- **Why now:** Inside a scout band. ' + correction
        # The public repository's generic possessive-name filter is stricter
        # than the producer's filter. Do not weaken it for an evidence suffix.
        self.assertEqual(morning_brief_markdown(heading + '\n\n' + item), '')
        for rejected in (item + ' Buy now.', item + ' Incomplete caveat',
                         item.replace('Inside a scout band.', 'Our holdings changed.'),
                         item.replace('January’s official release', 'This'),
                         item.replace('**not**', '**not'), item.replace('Why now:', 'Proof-add:')):
            self.assertEqual(morning_brief_markdown(heading + '\n\n' + rejected), '')
        self.assertEqual(morning_brief_markdown('## Context\n\n' + item), '')
        self.assertEqual(morning_brief_markdown(
            '### $DEMO — ACTION: private notes\n\nOrders rose.'), '')

    def test_optional_operational_filter_withholds_whole_items(self):
        body = '## Evidence\n- Receipt completed.\n  Orders rose.\n- Costs fell.'
        self.assertEqual(morning_brief_markdown(
            body, operational_line=lambda line: 'Receipt' in line),
            '## Evidence\n\n- Costs fell.')

    def test_dependent_references_and_empty_headings(self):
        self.assertEqual(morning_brief_markdown(
            '## Empty parent\n### Empty child\n- Max size: unavailable.\n'
            '## Evidence\n- One of those conditions could fail.\n- Costs fell.'),
            '## Evidence\n\n- Costs fell.')
        body = 'Orders rise only if demand holds. These conditions remain uncertain.'
        self.assertEqual(morning_brief_markdown(body), body)
        for value in (None, 0, [], {}):
            self.assertEqual(morning_brief_markdown(value), '')


if __name__ == '__main__':
    unittest.main()
