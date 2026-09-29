import unittest
from joblazy.shortlist_selection import diversify_candidates


class ShortlistSelectionTests(unittest.TestCase):
    def profile(self):
        return {'search_location':{'city':'London','country':'United Kingdom'},
                'discovery_preferences':{'title_filter':{'deprioritized':['SDR']},
                    'employer_rotation_groups':{'Group A':['A','A subsidiary']}}}

    def row(self,key,company,title='Business Operations',location='London, UK',url=None):
        return {'id':key,'data':{'company':company,'title':title,'location':location,
                               'url':url or 'https://example.test/jobs/'+key}}

    def test_large_employer_does_not_occupy_first_five_and_all_rows_survive(self):
        rows=[self.row(str(i),'A' if i%2 else 'A subsidiary') for i in range(6)]
        rows += [self.row('b','B'),self.row('c','C'),self.row('d','D')]
        ordered=diversify_candidates(rows,self.profile())
        self.assertEqual([r['id'] for r in ordered[:5]],['0','1','b','c','d'])
        self.assertEqual({r['id'] for r in ordered},{r['id'] for r in rows})
        self.assertEqual(len(ordered),len(rows))

    def test_explicit_choices_location_and_fallback_preferences_outrank_diversity(self):
        rows=[self.row(str(i),'A') for i in range(4)]
        rows += [self.row('fallback','B','SDR'),self.row('elsewhere','C',location='Manchester, UK')]
        ordered=diversify_candidates(rows,self.profile())
        self.assertEqual([r['id'] for r in ordered],['0','1','2','3','fallback','elsewhere'])
        selected=diversify_candidates(rows,self.profile(),pursued_ids=['elsewhere','3'])
        self.assertEqual([r['id'] for r in selected[:2]],['3','elsewhere'])

    def test_unknown_employers_use_observed_board_identity_without_guessing_names(self):
        rows=[self.row(str(i),'Employer unverified',url=f'https://job-boards.greenhouse.io/unknown-a/jobs/{i+1}')
              for i in range(4)]
        rows += [self.row('b','Employer unverified',url='https://job-boards.greenhouse.io/unknown-b/jobs/9')]
        ordered=diversify_candidates(rows,self.profile())
        self.assertEqual([r['id'] for r in ordered[:3]],['0','1','b'])
        self.assertTrue(all(r['data']['company']=='Employer unverified' for r in ordered))

    def test_invalid_limit_cannot_create_nonterminating_selection(self):
        for limit in (0,-1,True,1.5):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                diversify_candidates([self.row('one','A')],self.profile(),per_employer=limit)
