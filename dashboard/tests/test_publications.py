# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
"""Safe fixtures: examples exercise publishing, not investment research."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import normalize_publication, merge_publications, adapt_legacy, clean_narrative, PublicationError


def example(job='morning-brief'):
    return {'schemaVersion': 1, 'id': f'{job}:2026-09-04', 'jobId': job, 'type': 'brief',
            'title': '📌 Revenue evidence', 'summary': 'Revenue reached $12B; margins may improve.',
            'publishedAt': '2026-09-04T14:00:00Z', 'informationAt': '2026-09-04T12:00:00Z',
            'tickers': ['SYNTHA', '0000.HK', 'NYSE:SYNTH.N'],
            'sections': [{'heading': 'Evidence', 'markdown': '🟢 Revenue reached $12B. Valuation remains a risk.'}],
            'sources': [{'id': 'release', 'title': 'Company release', 'url': 'https://example.com/release'}]}


class PublicationTests(unittest.TestCase):
    def test_two_publishers_share_type_and_preserve_facts(self):
        for job in ('morning-brief', 'macro-update'):
            out = normalize_publication(example(job), [])
            self.assertEqual(out['type'], 'brief')
            self.assertIn('$12B', out['summary'])
            self.assertIn('🟢', out['sections'][0]['markdown'])
    def test_allowlist(self):
        raw = example(); raw.update(holdings=[{'shares': 500}], cssClass='hot')
        raw['sections'][0]['prompt'] = 'secret'
        out = normalize_publication(raw, [])
        self.assertNotIn('holdings', out); self.assertNotIn('prompt', out['sections'][0])
    def test_sentence_withholding_not_fragment_redaction(self):
        self.assertEqual(clean_narrative('Revenue reached $12B. My position is $40,000. 🟢 Demand improved.'), 'Revenue reached $12B. 🟢 Demand improved.')
        for text in ('My P/L is +$900.', 'Our cost basis is $12.', 'Run the skill and send to Slack.', 'Read /root/private/notes.', 'Income $[private] today.'):
            self.assertEqual(clean_narrative(text), '')
    def test_malformed_input(self):
        for key, value in [('tickers', ['$123']), ('publishedAt', 'yesterday'), ('schemaVersion', 7), ('title', '<script>alert(1)</script>')]:
            raw = example(); raw[key] = value
            with self.assertRaises(PublicationError): normalize_publication(raw, [])
    def test_unsafe_urls(self):
        for url in ('javascript:alert(1)', 'http://localhost/private', 'https://user:pass@example.com/x', 'file:///root/a'):
            raw = example(); raw['sources'][0]['url'] = url
            with self.assertRaises(PublicationError): normalize_publication(raw, [])
    def test_unknown_and_ambiguous_action_withheld(self):
        for code in ('SCOUT', 'NEW_UNVERIFIED_STATUS', 'WAIT_FOR_PROOF'):
            raw = example(); raw['assessment'] = code; diagnostics=[]
            out = normalize_publication(raw, diagnostics)
            self.assertEqual(out['assessment'], 'Assessment unavailable'); self.assertTrue(diagnostics)
        raw=example(); raw['sections'][0]['markdown'] += '\nBest actionable idea/avoid: $SYNTHA = starter watch / add-after-proof, not chase;'
        out=normalize_publication(raw, [])
        self.assertNotIn('starter watch', str(out)); self.assertIn('$12B', str(out))
    def test_action_conditions_and_negation(self):
        raw=example(); raw['action']={'currentView':'Do not buy now. Consider a purchase only if demand is confirmed.', 'why':'Business demand may improve.', 'prerequisites':['Demand is confirmed.'], 'horizon':'Next earnings report.', 'context':'Readers considering a new purchase.', 'sourceIds':['release']}
        out=normalize_publication(raw, []); self.assertEqual(out['action'], raw['action'])
        missing=copy.deepcopy(raw); missing['action']['prerequisites']=[]
        self.assertNotIn('action', normalize_publication(missing, []))
        stripped=copy.deepcopy(raw); stripped['sourceAction']=copy.deepcopy(raw['action']); stripped['action']['currentView']='Buy now.'
        self.assertNotIn('action', normalize_publication(stripped, []))
    def test_explicit_incompatible_state(self):
        raw=example(); raw['action']={'currentView':'Buy now.', 'why':'Avoid new purchases now.', 'prerequisites':[], 'sourceIds':['release']}
        self.assertNotIn('action',normalize_publication(raw, []))
    def test_updates_duplicates_and_lkg(self):
        old=normalize_publication(example(), [])
        changed=example(); changed['summary']='Demand increased.'
        self.assertEqual(len(merge_publications([changed, changed], [old], [])), 1)
        bad=example(); bad['publishedAt']='invalid'
        self.assertEqual(merge_publications([bad],[old], []), [old])
        invalid_old=copy.deepcopy(old); invalid_old['summary']='My holdings are $4M.'
        self.assertEqual(merge_publications([bad], [invalid_old], []), [])
        other=copy.deepcopy(changed); other['summary']='Different view.'
        self.assertEqual(merge_publications([changed,other], [old], []), [old])
    def test_quote_period(self):
        raw=example(); raw['quote']={'symbol':'SYNTHA','price':10,'currency':'USD','asOf':'2026-09-04T16:00:00Z','changePct':2}
        with self.assertRaises(PublicationError): normalize_publication(raw, [])
        raw['quote'].update(period='day',previousAsOf='2026-09-03T16:00:00Z')
        self.assertEqual(normalize_publication(raw, [])['quote']['changePct'],2)
    def test_browser_observed_operational_and_action_fragments_are_withheld(self):
        for text in ('Posture: SELECTIVE / WAIT-FOR-PROOF, not PRESS.', 'The stance remains WAIT-FOR-PROOF.', 'The stance remains WATCH / WAIT.', 'No action-state, research-tier, or daily-monitor-queue change.', 'Updated log.md', 'Regenerated index.md', 'Action: INDEPENDENT WATCH / WAIT FOR MATURE-COHORT ROIC PROOF.', 'Proof-add: Connected power becomes revenue.', 'Max size: add-small only after existing monitor gates.', 'New buys allowed, but cap total aggression around 17%', 'See full War Room.', 'Financing terms remain cu…'):
            self.assertEqual(clean_narrative(text),'',text)
        self.assertEqual(clean_narrative('<!-- earnings-preview-SYNTHG-start -->Revenue grew.'),'Revenue grew.')
        self.assertEqual(clean_narrative('War Room — 2026-08-21'),'Detailed research — 2026-08-21')
        self.assertEqual(clean_narrative('Proceeds were $8.25B. Proof-add: connected capacity converts. Demand increased.'),'Proceeds were $8.25B. Demand increased.')
    def test_final_observed_editorial_leakage(self):
        for text in ('Coverage Tier A; position: common holding per stored AI universe, not live broker verified. Action bucket',
                     'Position: common holding.',
                     'Research tier core-long unchanged; WAIT / read-through only, 0% fresh capital.',
                     'No new recommendation, tier or monitoring promotion.',
                     'Raise attention, not size.',
                     'Proof-add remains quantified example-product evidence.',
                     'Proof-add requires customer funding.',
                     'Research tiers and existing actions unchanged; no monitor-queue promotions.',
                     'Wiki updates: SaaS and AI-capex themes.',
                     'Example Research: completed OCR and saved numeric CSV/JSON.'):
            self.assertEqual(clean_narrative(text), '', text)
        text='Example stance: cautious — fictional demand is uncertain; avoid broad beta pressing or margin-leverage heroics.'
        expected=text.replace('broad beta pressing or margin-leverage heroics', 'taking more broad-market risk or using borrowed money')
        self.assertEqual(clean_narrative(text), expected)
        self.assertEqual(clean_narrative(expected), expected)

    def test_dependent_condition_is_not_stranded_by_withholding(self):
        dependent='A break below ~$41 with one of those facts triggers a thesis downgrade/kill review, not an automatic opportunity.'
        unsafe='**Thesis kill:** Material activation delays; realized payback >18 months. '
        self.assertEqual(clean_narrative(unsafe+dependent), '')
        self.assertEqual(clean_narrative(dependent), '')
        safe='Material activation delays or realized payback >18 months would weaken the business outlook. '+dependent
        self.assertEqual(clean_narrative(safe), safe)
        self.assertEqual(clean_narrative('Revenue reached $12B.\n\n'+unsafe+dependent+'\n\n🟢 Demand improved.'), 'Revenue reached $12B.\n\n🟢 Demand improved.')

    def test_full_source_sections_do_not_repeat_truncated_legacy_cards(self):
        raw={'tickers':[{'symbol':'SYNTHA','title':'Synthetic Alpha','summary':'Demand grew.','detailSections':[{'title':'Thesis','summary':'Broken du…','bullets':['Broken du…']}],'_publicSections':[{'title':'Thesis','content':'Revenue reached $12B.\n\nDemand increased.'}]}]}
        out=adapt_legacy(raw,[])[0]
        text=out['sections'][0]['markdown']
        self.assertNotIn('du…',text); self.assertEqual(text.count('Revenue reached $12B.'),1)
    def test_review_transport_and_asset_scan_reject_unsafe_legacy_content(self):
        import tempfile
        from public_snapshot import build_public_snapshot, canonical_json_bytes, scan_public_assets, validate_public_snapshot_schema
        from publish_wiki_data import parse_snapshot, PublishError
        body=build_public_snapshot({'tickers':[{'symbol':'EXAMPLE','title':'Example','summary':'Revenue increased.'}]},data_as_of='2026-09-04T12:00:00Z',cron_root=Path('/nonexistent'))
        body['publications']=[]
        parse_snapshot(canonical_json_bytes(body))
        body['tickers'][0]['summary']='My account value is $5.'
        validate_public_snapshot_schema(body)
        with self.assertRaises(PublishError) as raised: parse_snapshot(canonical_json_bytes(body))
        self.assertEqual(raised.exception.code, 'privacy_invalid')
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'wiki-data.json').write_bytes(canonical_json_bytes(body))
            self.assertTrue(scan_public_assets([Path(td)]))
    def test_review_private_classification_cannot_reappear_in_publications(self):
        from public_snapshot import build_public_snapshot
        for key in ('privacy_class','privacyClass'):
            raw=example(); raw[key]='private_local_only'
            self.assertEqual(merge_publications([raw],[],[]),[])
            old=normalize_publication(example(),[])
            self.assertEqual(merge_publications([raw],[old],[]),[old])
            raw=example(); raw['sections'][0][key]='private_local_only'
            self.assertEqual(merge_publications([raw],[],[]),[])
            body=build_public_snapshot({'tickers':[{'symbol':'EXAMPLE','title':'Example','summary':'Non-public pending research.',key:'private_local_only'}]},data_as_of='2026-09-04T12:00:00Z',cron_root=Path('/nonexistent'))
            self.assertEqual(body['tickers'],[]); self.assertEqual(body['publications'],[])
    def test_review_source_ids_are_literal_bounded_identifiers(self):
        raw=example(); raw['sources'][0]['id']='My account value is $5'; raw['sections'][0]['sourceIds']=['My account value is $5']
        with self.assertRaises(PublicationError): normalize_publication(raw,[])
    def test_native_identity_privacy_rejected_without_rewriting(self):
        for field in ('id', 'jobId'):
            for identifier in ('account-value-5', 'account-number-12345678'):
                raw=example(); raw[field]=identifier
                with self.assertRaises(PublicationError): normalize_publication(raw, [])
        for section_key in ('sections','thesisHistory','action'):
            raw=example()
            if section_key=='sections': raw['sections'][0]['sourceIds']=['account-value-5']
            elif section_key=='action': raw['action']={'currentView':'Wait for more evidence.', 'why':'Demand uncertain.', 'prerequisites':[], 'sourceIds':['account-value-5']}
            else: raw['thesisHistory']=[{'previousView':'Demand uncertain.','evidence':'Revenue grew.','currentView':'Demand improved.','informationAt':'2026-09-04T12:00:00Z','sourceIds':['account-value-5']}]
            with self.assertRaises(PublicationError): normalize_publication(raw, [])

    def test_sensitive_bounded_source_identifiers_rejected_end_to_end(self):
        import tempfile
        from public_snapshot import build_public_snapshot, canonical_json_bytes, scan_public_assets
        from publish_wiki_data import parse_snapshot, PublishError
        for identifier in ('account-value-5', 'account-number-12345678'):
            raw=example(); raw['sources'][0]['id']=identifier
            raw['sections'][0]['sourceIds']=[identifier]
            old=normalize_publication(example(), [])
            with self.assertRaises(PublicationError): normalize_publication(raw, [])
            self.assertEqual(merge_publications([raw],[old],[]),[old])
            body=build_public_snapshot({}, data_as_of='2026-09-04T12:00:00Z', cron_root=Path('/nonexistent'))
            body['publications']=[raw]
            with self.assertRaises(PublishError): parse_snapshot(canonical_json_bytes(body))
            with tempfile.TemporaryDirectory() as td:
                (Path(td)/'wiki-data.json').write_bytes(canonical_json_bytes(body))
                self.assertTrue(scan_public_assets([Path(td)]))

    def test_review_corporate_transactions_and_ordinary_emerging_preserved(self):
        for text in ('The company plans to sell its warehouse for $12B.','The product is emerging as a leader.','The company plans to purchase a factory for $2B.','Synthetic Booking Holdings reported USD 5 billion in revenue.','Synthetic Lending Holdings operates a lending platform.'):
            self.assertEqual(clean_narrative(text),text)
        self.assertEqual(clean_narrative('Buy $SYNTHA now.'),'')
    def test_generator_preserves_company_figures_not_small_account_values(self):
        import generate_wiki_data as gen
        for fn in (gen.sanitize_private_numbers,gen.redact_private_markdown,gen.scrub_private):
            public='SYNTHE reported revenue of $1.234B. SYNTHF backlog reached $6,000,000,000. 🟢 Gross margin was 52.5%.'
            self.assertEqual(fn(public), public)
            self.assertEqual(fn('My account value is $5. My portfolio weight is 1.2%.'), '')
        self.assertEqual(gen.scrub_private('WAIT_FOR_PROOF'),'WAIT_FOR_PROOF')
    def test_generator_future_job_discovery_inventory_and_updates(self):
        import json
        import tempfile
        import generate_wiki_data as gen
        from contextlib import ExitStack
        from unittest.mock import patch
        from public_snapshot import input_inventory
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            root=Path(td); (root/'wiki/tickers').mkdir(parents=True); (root/'wiki/data/publications').mkdir(parents=True); (root/'cron').mkdir()
            source=root/'wiki/data/publications/new-job.json'; output=root/'snapshot.json'
            raw=example('future-job'); source.write_text(json.dumps(raw))
            for name,value in {'parse_tickers':[],'canonical_macro_posture':None,'plain_report':None,'parse_daily_journal':[],'parse_agentic_trading_reports':[],'load_intraday_equity_watchdog':{},'parse_market_graphs':[],'parse_current_asymmetric_shortlist':None,'parse_ai_projection_exhibits':None,'parse_ai_war_room_complete_data':None,'parse_sources':[],'parse_cron_timeline':[]}.items():
                stack.enter_context(patch.object(gen,name,return_value=value))
            for name in ('WIKI','OUT','CRON_ROOT','OFFLINE'): stack.enter_context(patch.object(gen,name,getattr(gen,name)))
            argv=['--wiki-root',str(root/'wiki'),'--cron-root',str(root/'cron'),'--output',str(output),'--offline','--quiet']
            self.assertTrue(any(e.path==str(source) for e in input_inventory([root/'wiki'])))
            self.assertEqual(gen.main(argv),0); first=json.loads(output.read_text())
            self.assertEqual(gen.main(argv),0); self.assertEqual(json.loads(output.read_text()),first)
            raw['summary']='Revenue and demand increased.'; source.write_text(json.dumps(raw))
            self.assertEqual(gen.main(argv),0)
            published=json.loads(output.read_text())['publications']
            self.assertEqual(len(published),1); self.assertEqual(published[0]['summary'],raw['summary'])
    def test_legacy_company_quote_uses_explicit_currency_and_clock(self):
        raw={'tickers':[{'symbol':'SYNTHA','title':'Synthetic Alpha','summary':'Demand grew.'}], 'aiWarRoomCompleteData':{'rows':[{'symbol':'SYNTHA','price':10,'currency':'USD','quoteAsOf':'2026-09-04 16:00:00+00:00','dayChangePct':2,'ltmRevenue':1234000000}]}}
        out=adapt_legacy(raw, [])[0]
        self.assertEqual(out['quote']['price'],10); self.assertNotIn('changePct',out['quote'])
        self.assertIn('1,234,000,000.00',str(out['sections']))
        raw['aiWarRoomCompleteData']['rows'][0].pop('currency')
        self.assertNotIn('quote',adapt_legacy(raw, [])[0])
    def test_date_precision_and_numeric_exchange_aliases(self):
        raw=example(); raw['informationDate']='2026-09-04'; raw['informationAt']=None
        raw['tickers'] += ['NASDAQ:SYNTHA','0000TW','0000T']
        self.assertEqual(normalize_publication(raw, [])['tickers'],raw['tickers'])
        raw['informationDate']='2026-02-31'
        with self.assertRaises(PublicationError): normalize_publication(raw, [])
    def test_quote_reference_sign_and_clocks(self):
        raw=example(); raw['quote']={'symbol':'SYNTHH','price':10,'currency':'USD','asOf':'2026-09-04T16:00:00Z'}
        with self.assertRaises(PublicationError): normalize_publication(raw, [])
        raw['quote'].update(symbol='SYNTHA',change=1,changePct=-2,period='day',previousAsOf='2026-09-03T16:00:00Z')
        with self.assertRaises(PublicationError): normalize_publication(raw, [])
        raw.pop('quote'); raw['sections'][0]['sourceIds']=['nonexistent']
        with self.assertRaises(PublicationError): normalize_publication(raw, [])
    def test_private_section_and_code_fence_do_not_strand_values(self):
        text='## Our holdings\n| SYNTHA | 400 | $5M |\n## Evidence\nRevenue reached $12B.\n```python\nprint("private")\n```\n🟢 Demand improved.'
        clean=clean_narrative(text)
        self.assertNotIn('$5M',clean); self.assertNotIn('print',clean)
        self.assertIn('$12B',clean); self.assertIn('🟢',clean)
    def test_private_nested_metadata_and_diagnostic_location(self):
        from public_content import sanitize_legacy
        diagnostics=[]
        out=sanitize_legacy({'tickers':[{'symbol':'SYNTHA','status':'SCOUT','detailSections':[{'title':'Private','summary':'hidden','privacy_class':'private_local_only'}]}]}, diagnostics=diagnostics)
        self.assertEqual(out['tickers'][0]['detailSections'],[])
        self.assertEqual(diagnostics[0]['recordId'],'SYNTHA')
        self.assertEqual(diagnostics[0]['field'],'$.tickers[0].status')
        self.assertNotIn('SCOUT', str(diagnostics))
    def test_verified_business_assessment_is_not_buy_recommendation(self):
        raw=example(); raw['assessment']='OWNABLE'
        out=normalize_publication(raw, [])
        self.assertEqual(out['assessment'],'Differentiated business thesis supported')
        self.assertNotIn('action',out)
        self.assertEqual(normalize_publication(out, []),out)
    def test_positive_business_and_conditional_buying_preserved(self):
        raw=example(); raw['action']={'currentView':'Consider a purchase only if margins improve.', 'why':'Business demand is strong; valuation remains a risk.', 'prerequisites':['Margins improve.'], 'horizon':'Next earnings report.', 'context':'New purchase research.', 'sourceIds':['release']}
        self.assertEqual(normalize_publication(raw, [])['action'],raw['action'])
    def test_unsafe_update_retains_real_previous_clocks_and_identity(self):
        old=normalize_publication(example(), [])
        update=example(); update['publishedAt']='2026-09-05T14:00:00Z'; update['sections'][0]['markdown']+=' My holdings are $5M.'
        self.assertEqual(merge_publications([update],[old], []),[old])
        update=example(); update['jobId']='other-owner'
        self.assertEqual(merge_publications([update],[old], []),[old])
    def test_shared_snapshot_boundary_excludes_legacy_leaks(self):
        from public_snapshot import build_public_snapshot
        raw={'tickers':[{'symbol':'SYNTHA','title':'Synthetic Alpha','summary':'Revenue reached $12B.','status':'SCOUT'}], 'cronTimeline':[{'id':'a','jobId':'publisher-a','summary':'Revenue rose.','articleBody':'Best actionable idea/avoid: $SYNTHA = starter watch / add-after-proof, not chase;\nRevenue reached $12B.\nMy P/L is $900.\nFiles written /root/private.txt'}]}
        diagnostics=[]
        out=build_public_snapshot(raw,data_as_of='2026-09-04T12:00:00Z',cron_root=Path('/nonexistent'),diagnostics=diagnostics)
        for forbidden in ('starter watch','SCOUT','/root/','My P/L'): self.assertNotIn(forbidden,str(out))
        self.assertIn('$12B',str(out)); self.assertTrue(diagnostics)
    def test_legacy_fact_sources_highlights_and_unknown_clocks(self):
        raw={'cronTimeline':[{'id':'a','jobId':'publisher-a','summary':'Revenue rose.','articleBody':'Revenue reached $12B. https://example.com/release','highlights':['🟢 $SYNTHA demand improved.'],'runTime':'2026-09-04 14:00'}]}
        out=adapt_legacy(raw, [])[0]
        self.assertEqual(out['sources'][0]['url'],'https://example.com/release')
        self.assertIn('🟢 $SYNTHA demand improved.',out['sections'][0]['markdown'])
        self.assertIsNone(out['publishedAt'])
    def test_legacy_clocks_not_invented(self):
        rows=adapt_legacy({'tickers':[{'symbol':'SYNTHA','title':'Synthetic Alpha','summary':'Revenue grew.','updated':'2026-09-04'}], 'cronTimeline':[{'id':'edition','jobId':'macro-monitor','runTime':'2026-09-04T12:00:00Z','summary':'Rates rose.','articleBody':'📌 Rates rose.'}]}, [])
        self.assertEqual({r['type'] for r in rows},{'company','brief'})
        self.assertIsNone(next(r for r in rows if r['type']=='company')['publishedAt'])

if __name__ == '__main__': unittest.main()
