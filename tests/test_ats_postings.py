import copy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from joblazy.ats_postings import _NoRedirect, fetch_json, parse_posting_url, verify_posting


ID = '12345678-1234-1234-1234-123456789abc'
DESCRIPTION = 'Help our fictional operations team improve processes and measure outcomes. ' * 5
ASHBY = f'https://jobs.ashbyhq.com/fictional/{ID}'
LEVER = f'https://jobs.lever.co/fictional/{ID}'
GREENHOUSE = 'https://job-boards.greenhouse.io/fictional/jobs/12345'
NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def ashby():
    return {'jobs': [{'id': ID, 'jobUrl': ASHBY, 'applyUrl': ASHBY + '/application',
                     'title': 'Operations Associate', 'descriptionPlain': DESCRIPTION,
                     'isListed': True, 'location': 'London',
                     'address': {'postalAddress': {'addressLocality': 'London', 'addressCountry': 'GB'}},
                     'secondaryLocations': [{'location': 'Berlin', 'address': {'postalAddress': {'addressCountry': 'DE'}}}],
                     'publishedAt': '2026-09-20T12:00:00Z'}]}


def lever(url=LEVER):
    return {'id': ID, 'hostedUrl': url, 'applyUrl': url + '/apply', 'text': 'GTM Associate',
            'descriptionPlain': DESCRIPTION, 'lists': [{'text': 'Requirements', 'content': '<ul><li>Two years of experience</li></ul>'}],
            'additionalPlain': 'Equal opportunity employer.', 'categories': {'location': 'London', 'allLocations': ['London', 'Paris']},
            'country': 'GB', 'workplaceType': 'hybrid', 'salaryRange': {'min': 1, 'max': 2, 'currency': 'GBP'}}


def greenhouse():
    return {'id': 12345, 'internal_job_id': 98, 'requisition_id': 'OPS-12', 'company_name': 'Fictional Company',
            'title': 'Strategy Associate', 'content': '&lt;p&gt;' + DESCRIPTION + '&lt;/p&gt;',
            'location': {'name': 'Hybrid'}, 'offices': [{'name': 'London', 'location': 'London, United Kingdom'}],
            'absolute_url': GREENHOUSE, 'updated_at': '2026-09-28T12:00:00Z'}


class AtsPostingTests(unittest.TestCase):
    def read(self, url, payload):
        calls = []
        def fake(api_url, *, timeout):
            calls.append((api_url, timeout))
            return copy.deepcopy(payload)
        result = verify_posting(url, fetch_json=fake, timeout=7, now=NOW)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 7)
        return result, calls[0][0]

    def test_ashby_exact_application_url_retains_identity_source_and_countries(self):
        result, api = self.read(ASHBY + '/application?utm_source=test', ashby())
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(api, 'https://api.ashbyhq.com/posting-api/job-board/fictional?includeCompensation=true')
        job = result['job']
        self.assertEqual(job['url'], ASHBY + '/application?utm_source=test')
        self.assertEqual(job['application_url'], ASHBY + '/application')
        self.assertEqual(job['company'], 'Employer unverified')
        self.assertEqual(job['title'], 'Operations Associate')
        self.assertIn('DE', job['location'])
        self.assertIn('GB', job['location'])
        self.assertEqual(job['source_metadata']['jobLocation'][0]['address']['addressCountry'], 'GB')
        self.assertEqual(job['observed_at'], NOW.isoformat())
        self.assertEqual(job['source_provenance']['identity'], f'ashby:fictional:{ID}')
        self.assertNotIn('datePosted', job['source_metadata'])
        self.assertEqual(job['source_metadata']['publishedAt'], '2026-09-20T12:00:00Z')

    def test_greenhouse_keeps_posting_and_internal_requisition_distinct(self):
        result, api = self.read(GREENHOUSE, greenhouse())
        self.assertEqual(result['status'], 'verified')
        job = result['job']
        self.assertEqual(api, 'https://boards-api.greenhouse.io/v1/boards/fictional/jobs/12345')
        self.assertEqual(job['company'], 'Fictional Company')
        self.assertEqual(job['source_metadata']['posting_id'], '12345')
        self.assertEqual(job['source_metadata']['requisition_id'], 'OPS-12')
        self.assertEqual(job['source_metadata']['internal_job_id'], 98)
        self.assertIn('United Kingdom', job['location'])
        self.assertNotIn('<p>', job['description'])
        self.assertNotIn('datePosted', job['source_metadata'])

    def test_greenhouse_embed_and_eu_observed_urls(self):
        for url in ('https://boards.greenhouse.io/embed/job_app?for=fictional&token=12345',
                    'https://job-boards.eu.greenhouse.io/fictional/jobs/12345'):
            result, api = self.read(url, greenhouse())
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(api, 'https://boards-api.greenhouse.io/v1/boards/fictional/jobs/12345')

    def test_lever_includes_lists_and_additional_in_description(self):
        result, api = self.read(LEVER + '/apply', lever())
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(api, f'https://api.lever.co/v0/postings/fictional/{ID}?mode=json')
        self.assertIn('Two years of experience', result['job']['description'])
        self.assertIn('Equal opportunity employer.', result['job']['description'])
        self.assertIn('Paris', result['job']['location'])
        self.assertEqual(result['job']['source_metadata']['salaryRange']['currency'], 'GBP')

    def test_lever_eu_stays_on_eu_api_and_has_separate_identity(self):
        url = LEVER.replace('jobs.lever.co', 'jobs.eu.lever.co')
        result, api = self.read(url, lever(url))
        self.assertEqual(result['status'], 'verified')
        self.assertTrue(api.startswith('https://api.eu.lever.co/'))
        self.assertEqual(result['job']['source_provenance']['identity'], f'lever-eu:fictional:{ID}')
        self.assertNotEqual(parse_posting_url(url)['identity'], parse_posting_url(LEVER)['identity'])

    def test_unrecognized_or_unsafe_urls_never_fetch(self):
        urls = ['http://jobs.lever.co/fictional/' + ID, 'https://127.0.0.1/jobs/12345',
                ASHBY.replace('/fictional/', '/%2e%2e/'), ASHBY.replace('/fictional/', '/a%2Fb/'),
                ASHBY.replace('jobs.', 'jobs.evil.'), ASHBY.replace('https://', 'https://user@'),
                ASHBY.replace('.com/', '.com:8443/'), ASHBY + '/unknown', ASHBY + '\\anything',
                'https://jobs.ashbyhq.com/fictional', ASHBY + '\n',
                'https://boards.greenhouse.io/embed/job_app?for=a&for=b&token=12345']
        for url in urls:
            with self.subTest(url=url):
                with patch('joblazy.ats_postings.fetch_json') as fetch:
                    self.assertEqual(verify_posting(url)['status'], 'unsupported')
                    fetch.assert_not_called()

    def test_missing_is_unavailable_but_malformed_response_is_failed(self):
        for payload, status in [({'jobs': []}, 'unavailable'), ({}, 'failed'),
                                ({'jobs': [None]}, 'failed'), ({'jobs': [{'jobUrl': 'https://evil.test/x'}]}, 'failed')]:
            result, _ = self.read(ASHBY, payload)
            self.assertEqual(result['status'], status)
            self.assertNotIn('job', result)

    def test_unlisted_is_excluded_and_duplicate_identity_is_rejected(self):
        data = ashby()
        data['jobs'][0]['isListed'] = False
        result, _ = self.read(ASHBY, data)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['observation']['state'], 'unlisted')
        data['jobs'].append(copy.deepcopy(data['jobs'][0]))
        result, _ = self.read(ASHBY, data)
        self.assertEqual(result['status'], 'failed')

    def test_identity_disagreement_never_returns_job(self):
        wrong = lever(); wrong['hostedUrl'] = LEVER.replace('fictional', 'someone-else')
        wrong_gh = greenhouse(); wrong_gh['id'] = 999
        wrong_ashby = ashby(); wrong_ashby['jobs'][0]['id'] = 'wrong'
        for url, data in [(LEVER, wrong), (GREENHOUSE, wrong_gh), (ASHBY, wrong_ashby)]:
            result, _ = self.read(url, data)
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('job', result)

    def test_application_url_cannot_point_to_unrelated_job_or_host(self):
        for url in ('https://127.0.0.1/apply', LEVER.replace('fictional', 'other')):
            data = lever(); data['applyUrl'] = url
            result, _ = self.read(LEVER, data)
            self.assertEqual(result['status'], 'verified')
            self.assertNotIn('application_url', result['job'])

    def test_short_or_missing_description_requires_fallback(self):
        for description in ('Apply now', '', 'x' * 80001):
            data = greenhouse(); data['content'] = description
            result, _ = self.read(GREENHOUSE, data)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['observation']['state'], 'invalid_source')

    def test_http_failures_distinguish_missing_from_temporary_and_access(self):
        for code, status, state in [(404, 'unavailable', 'page_unavailable'), (410, 'unavailable', 'page_unavailable'),
                                    (429, 'failed', 'temporary_failure'), (503, 'failed', 'temporary_failure'),
                                    (403, 'failed', 'access_unverified'), (302, 'failed', 'access_unverified')]:
            def fake(url, *, timeout):
                raise HTTPError(url, code, 'fixture', {}, None)
            result = verify_posting(LEVER, fetch_json=fake)
            self.assertEqual((result['status'], result['observation']['state']), (status, state))
            self.assertEqual(result['observation']['http_status'], code)
            self.assertNotIn('job', result)

    def test_timeout_and_invalid_json_are_failed_not_closed(self):
        for error, state in [(TimeoutError(), 'temporary_failure'),
                              (json.JSONDecodeError('bad JSON', 'x', 0), 'invalid_source')]:
            def fake(url, *, timeout):
                raise error
            result = verify_posting(LEVER, fetch_json=fake)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['observation']['state'], state)

    def test_stdlib_fetch_disallows_untrusted_host_and_redirects(self):
        with patch('joblazy.ats_postings.build_opener') as opener:
            for url in ('https://localhost/data', 'https://api.lever.co@localhost/data', 'http://api.lever.co/data'):
                with self.assertRaises(ValueError):
                    fetch_json(url)
            opener.assert_not_called()
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://localhost/'))

    def test_timeout_configuration_is_bounded(self):
        for value in (0, -1, 61, float('nan'), float('inf'), True, '20'):
            with self.assertRaises(ValueError):
                verify_posting(ASHBY, timeout=value)


if __name__ == '__main__':
    unittest.main()
