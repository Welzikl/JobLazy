import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from joblazy.coverage import audit_rows,location_class,timestamp
from joblazy.common import read_json,write_json
from joblazy.store import Store
from .support import job


class CoverageTests(unittest.TestCase):
    def test_london_namesakes_and_remote_jurisdictions_stay_separate(self):
        cases={'London, Ontario, Canada':'other_london','New London, Connecticut':'other_london',
            'East London, South Africa':'other_london','London':'london_country_unverified',
            'East London, England, United Kingdom':'london_uk_explicit','East London, UK':'london_uk_explicit',
            'East London':'london_country_unverified','East London, ZA':'other_london',
            'East London, ZAF':'other_london','London, CA':'other_london','London, CAN':'other_london',
            'London, US':'other_london','London, GBR':'london_uk_explicit','GB-London':'london_uk_explicit',
            'London, U.K.':'london_uk_explicit','London, U.K. (Hybrid)':'london_uk_explicit',
            'London, CA | East London, UK':'london_uk_explicit','East London, ZA | Manchester, UK':'other_london',
            'GBR · London · Canada':'london_country_unverified','London · GBR':'london_country_unverified',
            'London, England, United Kingdom':'london_uk_explicit','London, UK | Toronto, Canada':'london_uk_explicit',
            'London, UK\nToronto, Canada':'london_uk_explicit',
            'London \u00b7 New York \u00b7 New York City \u00b7 United States':'london_country_unverified',
            'United Kingdom \u00b7 London \u00b7 Canada':'london_country_unverified',
            'London, Canada \u00b7 Manchester, United Kingdom':'other_london',
            'London, United States':'other_london',
            'Remote, United Kingdom':'uk_remote_candidate','Remote, United States':'remote_eligibility_unverified',
            'Anywhere':'remote_eligibility_unverified','United Kingdom':'uk_city_unspecified_or_elsewhere','':'location_missing'}
        for label,expected in cases.items():
            with self.subTest(label=label):self.assertEqual(location_class(label),expected)

    def test_posting_age_is_not_scan_freshness_or_liveness(self):
        now=datetime(2026,9,12,tzinfo=timezone.utc)
        entries=[('recent','London, UK','2026-09-10'),('old','London, UK','2025-01-01'),
            ('unknown','London',None),('future','London, UK','2027-01-01')]
        rows=[{'id':key,'data':{**job('https://example.test/'+key),'location':location,
            'postedAt':date,'observed_at':now.isoformat()}} for key,location,date in entries]
        report=audit_rows(rows,now=now)
        self.assertEqual(report['summary']['explicit_london_uk_records'],3)
        self.assertEqual(report['summary']['explicit_london_within_posting_age_threshold'],1)
        self.assertEqual(report['summary']['explicit_closed_flags'],0)
        self.assertEqual(report['summary']['current_employer_availability_unverified'],4)
        self.assertEqual(report['observation_age'],{'observed_within_48h':4})
        for value in [now.timestamp(),now.timestamp()*1000,str(int(now.timestamp()*1000)),now.isoformat(),'2026-09-12']:
            self.assertEqual(timestamp(value),now)
        for value in [None,True,0,'invalid',10**40]:self.assertIsNone(timestamp(value))

    def test_cross_url_candidates_do_not_merge_records_or_invent_source_success(self):
        rows=[{'id':str(i),'data':{**job(url),'location':'London, UK','description':description,'ats':provider}}
            for i,(url,description,provider) in enumerate([
                ('https://example.test/one?utm_source=a','', 'feed'),
                ('https://example.test/one','tiny','feed'),
                ('https://employer.test/one','x'*500,'ashby')])]
        report=audit_rows(rows,boards={'boards':[{'name':'Feed query A','provider':'feed'},{'name':'Feed query B','provider':'feed'}]},
            last_scan={'errors':[{'board':'Feed query B','error':'429'}]})
        self.assertEqual(report['summary']['saved_queue_records'],3)
        self.assertEqual(report['summary']['distinct_canonical_urls'],2)
        self.assertEqual(report['summary']['possible_duplicate_groups'],1)
        self.assertEqual(report['description_length'],{'missing':1,'shorter_than_200_characters':1,'at_least_200_characters':1})
        self.assertIsNone(report['source_registry'][0]['last_successful_scan'])
        self.assertIsNone(report['source_registry'][0]['new_unique_jobs'])
        self.assertEqual(report['source_registry'][1]['reported_failures'][0]['error'],'429')

    def test_cli_writes_coverage_without_modifying_queue_or_usage(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            store.ingest(job('https://example.test/one'))
            before=store.list();usage=store.daily_usage('2026-09-12')
            boards=Path(temp)/'boards.json';write_json(boards,{'boards':[]})
            result=subprocess.run([sys.executable,'-m','joblazy','--data',temp,'coverage','--boards',str(boards)],
                capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['saved_queue_records'],1)
            self.assertEqual(read_json(Path(temp)/'coverage.json')['locations'],{'london_country_unverified':1})
            self.assertEqual(store.list(),before);self.assertEqual(store.daily_usage('2026-09-12'),usage)


if __name__=='__main__':unittest.main()
