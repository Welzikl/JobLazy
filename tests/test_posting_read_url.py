import unittest
from joblazy.discovery import posting_read_url


class PostingReadURLTests(unittest.TestCase):
    def test_ashby_application_identity_is_read_on_the_public_description_route(self):
        root='https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc'
        self.assertEqual(posting_read_url(root+'/application?source=example'),root+'?source=example')
        self.assertEqual(posting_read_url(root+'/application/'),root)
        for url in (root,root.replace('jobs.ashbyhq.com','jobs.ashbyhq.com.example.test')+'/application',
                    'https://example.test/jobs/application','https://jobs.ashbyhq.com/example/application'):
            self.assertEqual(posting_read_url(url),url)

    def test_lever_apply_reads_the_public_description_without_changing_other_routes(self):
        root='https://jobs.lever.co/example/12345678-1234-1234-1234-123456789abc'
        self.assertEqual(posting_read_url(root+'/apply?source=example'),root+'?source=example')
        self.assertEqual(posting_read_url(root+'/apply/'),root)
        for url in (root,root.replace('jobs.lever.co','jobs.lever.co.example.test')+'/apply',
                    'https://example.test/jobs/apply','https://jobs.lever.co/example/apply'):
            self.assertEqual(posting_read_url(url),url)
