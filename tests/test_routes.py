import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.common import NeedsInput,read_json
from joblazy.routes import destination,resolve_application


class DestinationTests(unittest.TestCase):
    def test_smartrecruiters_interested_link_requires_matching_company_and_application_marker(self):
        source='https://jobs.smartrecruiters.com/Example/123-growth-lead'
        target='https://jobs.smartrecruiters.com/oneclick-ui/company/Example/publication/436017e2-1894-4ab7-8c04-d01a4f43a829?dcr_ci=Example'
        anchor={'label':"I'm interested",'url':target,'sr_track':'apply'}
        with patch('joblazy.routes.public_url',return_value=True):
            result=destination({'anchors':[anchor,anchor]},source)
            self.assertIsNotNone(result)
            self.assertEqual(result['url'],target)
            self.assertIsNone(destination({'anchors':[{**anchor,'sr_track':'other-job'}]},source))
            for bad in (target.replace('/Example/','/Other/'),target.replace('dcr_ci=Example','dcr_ci=Other'),
                        target.replace('jobs.smartrecruiters.com','unrelated.test'),target.replace('/publication/','/profile/')):
                self.assertIsNone(destination({'anchors':[{**anchor,'url':bad}]},source))
            self.assertIsNone(destination({'anchors':[anchor]},source.replace('jobs.smartrecruiters.com','unrelated.test')))
            with self.assertRaisesRegex(NeedsInput,'Multiple'):
                destination({'anchors':[anchor,{**anchor,'url':target.replace('436017e2','536017e2')}]},source)

    def test_smartrecruiters_route_uses_visible_title_and_links_without_clicking(self):
        target='https://jobs.smartrecruiters.com/oneclick-ui/company/Example/publication/436017e2-1894-4ab7-8c04-d01a4f43a829?dcr_ci=Example'
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context();requests=[]
            def serve(route):
                requests.append((route.request.method,route.request.url))
                if '/oneclick-ui/' in route.request.url:
                    body='<h1>Application</h1><input type="email"><input type="file">'
                else:
                    body=('<h1 style="display:none">Sorry, Internet Explorer 11 is no longer supported</h1>'
                          '<h1>Growth Lead</h1><main>'
                          '<a style="visibility:hidden" data-sr-track="apply" href="https://wrong.test/apply">Apply</a>'
                          '<a aria-hidden="true" data-sr-track="apply" href="https://wrong.test/other">Apply</a>'
                          '<a data-sr-track="apply" href="'+target+'" onclick="fetch(\'/track\',{method:\'POST\'})">I\'m interested</a></main>')
                route.fulfill(status=200,content_type='text/html',body=body)
            context.route('**/*',serve)
            with patch('joblazy.routes.public_url',return_value=True):
                result=resolve_application({'url':'https://jobs.smartrecruiters.com/Example/123-growth-lead'},context,Path(temp))
            self.assertEqual(result['application_url'],target)
            evidence=read_json(Path(temp)/'application-route.json')
            self.assertEqual(evidence['observations'][0]['title'],'Growth Lead')
            self.assertTrue(all(method=='GET' and 'wrong.test' not in url and '/track' not in url for method,url in requests))
            self.assertEqual(len(context.pages),0)
            browser.close()

    def test_muse_data_matches_exact_company_and_posting_and_rejects_conflicting_routes(self):
        source='https://www.themuse.com/jobs/fictional/role'
        item={'company_slug':'fictional','company_short_name':'fictional','job_slug':'role','short_title':'role','id':123,'link':'https://employer.test/123'}
        with patch('joblazy.routes.public_url',return_value=True):
            self.assertEqual(destination({'muse_jobs':[item]},source)['url'],item['link'])
            self.assertIsNone(destination({'muse_jobs':[item]},source+'-other'))
            self.assertIsNone(destination({'muse_jobs':[item]},source.replace('www.themuse.com','unrelated.test')))
            self.assertIsNone(destination({'muse_jobs':[{**item,'company_short_name':'other'}]},source))
            with self.assertRaisesRegex(NeedsInput,'Multiple'):
                destination({'muse_jobs':[item,{**item,'link':'https://other.test/456'}]},source)
        with patch('joblazy.routes.public_url',return_value=False),self.assertRaisesRegex(NeedsInput,'public HTTPS'):
            destination({'muse_jobs':[item]},source)

    def test_muse_public_props_route_without_pressing_the_apply_or_newsletter_controls(self):
        props={'companyShortName':'fictional','jobShortName':'role','company':{'shortName':'fictional'},
            'job':{'type':'external','shortTitle':'role','id':123,'applyLink':'https://employer.test/123'}}
        payload='1d:'+json.dumps(['$', 'main',None,{'children':props}])+'\n'
        # Split a record across serialized chunks, as streamed page data may do.
        # Real pages also place a complete JSON record after a non-newline text
        # record; concatenating all fragments alone loses that JSON boundary.
        scripts=''.join('<script type="text/plain">self.__next_f.push('+json.dumps([1,chunk])+')</script>' for chunk in ('20:T4,','text',payload,payload[:50],payload[50:]))
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context();requests=[]
            def serve(route):
                requests.append((route.request.method,route.request.url))
                body=('<h1>Fictional role</h1>'+scripts+'<button onclick="fetch(\'/tracking\',{method:\'POST\'})">Apply on company site</button><form><input name="newsletter_email"></form>'
                    if 'themuse.com' in route.request.url else '<h1>Employer application</h1><input type="file">')
                route.fulfill(status=200,content_type='text/html',body=body)
            context.route('**/*',serve)
            with patch('joblazy.routes.public_url',return_value=True):
                result=resolve_application({'url':'https://www.themuse.com/jobs/fictional/role'},context,Path(temp))
            self.assertEqual(result['application_url'],'https://employer.test/123')
            self.assertTrue(all(method=='GET' and '/tracking' not in url for method,url in requests))
            record=read_json(Path(temp)/'application-route.json')
            self.assertEqual(record['observations'][0]['destination']['method'],'public Muse job.applyLink')
            browser.close()

    def test_muse_without_an_employer_route_does_not_resolve_to_newsletter_form(self):
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context()
            context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<h1>Fictional listing</h1><form><input type="email" name="newsletter"></form>'))
            with patch('joblazy.routes.public_url',return_value=True),self.assertRaisesRegex(NeedsInput,'No explicit employer'):
                resolve_application({'url':'https://www.themuse.com/jobs/fictional/role'},context,Path(temp))
            self.assertEqual(len(context.pages),0)
            browser.close()

    def test_unavailable_employer_keeps_failed_destination_and_http_status(self):
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context()
            context.route('**/*',lambda route:route.fulfill(status=403,content_type='text/html',body='<h1>Access check</h1>'))
            with patch('joblazy.routes.public_url',return_value=True),self.assertRaisesRegex(NeedsInput,'HTTP 403'):
                resolve_application({'url':'https://employer.test/123'},context,Path(temp))
            observation=read_json(Path(temp)/'application-route.json')['observations'][0]
            self.assertEqual(observation['requested_url'],'https://employer.test/123')
            self.assertEqual(observation['http_status'],403)
            self.assertEqual(observation['boundary'],'http_error')
            browser.close()

    def test_explicit_employer_label_and_duplicate_links(self):
        raw={'anchors':[{'label':' APPLY  AT TIKTOK ','url':'https://employer.test/job/123'}]*2}
        with patch('joblazy.routes.public_url',return_value=True):
            result=destination(raw,'https://listing.test/123')
        self.assertEqual(result['url'],'https://employer.test/job/123')

    def test_ambiguous_unsafe_and_unrelated_links(self):
        raw={'anchors':[{'label':'Apply now','url':u} for u in ['https://one.test/1','https://two.test/2']]}
        with self.assertRaisesRegex(NeedsInput,'Multiple'): destination(raw,'https://listing.test/123')
        raw['anchors']=raw['anchors'][:1]
        with patch('joblazy.routes.public_url',return_value=False),self.assertRaisesRegex(NeedsInput,'public HTTPS'):
            destination(raw,'https://listing.test/123')
        self.assertIsNone(destination({'anchors':[{'label':'Join the Network','url':'https://network.test'}]},'https://listing.test/123'))

    def test_hub_data_must_match_current_posting(self):
        raw={'hub_job':{'id':'abc123','link':'https://employer.test/123'}}
        with patch('joblazy.routes.public_url',return_value=True):
            self.assertIsNone(destination(raw,'https://thehub.io/jobs/other'))
            self.assertIsNone(destination(raw,'https://other.test/jobs/abc123'))
            self.assertEqual(destination(raw,'https://thehub.io/jobs/abc123')['posting_id'],'abc123')

    def test_job_specific_link_takes_precedence_over_generic_account_apply(self):
        raw={'anchors':[{'label':'Apply','url':'https://employer.test/account'},
                        {'label':'Apply to this job','url':'https://employer.test/jobs/123/apply'}]}
        with patch('joblazy.routes.public_url',return_value=True):
            self.assertEqual(destination(raw,'https://employer.test/jobs/123')['url'],'https://employer.test/jobs/123/apply')

    def test_route_uses_read_only_pages_and_records_public_provenance(self):
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context()
            requests=[]
            def serve(route):
                requests.append((route.request.method,route.request.url))
                body=('<h1>Example role</h1><script>window.__NUXT__={state:{jobs:{job:{id:"abc123",link:"https://employer.test/123"}}}};</script>'
                      '<button onclick="fetch(\'/consent\',{method:\'POST\'})">Apply</button>'
                      if 'thehub.io' in route.request.url else '<h1>Employer role</h1><input name="email"><input type="file">')
                route.fulfill(status=200,content_type='text/html',body=body)
            context.route('**/*',serve)
            # The resolver's per-page network guard still runs; only .test fixture
            # hosts are admitted here. No production requests leave this context.
            with patch('joblazy.routes.public_url',return_value=True):
                resolved=resolve_application({'url':'https://thehub.io/jobs/abc123'},context,Path(temp))
            self.assertEqual(resolved['application_url'],'https://employer.test/123')
            self.assertEqual(resolved['url'],'https://thehub.io/jobs/abc123')
            self.assertTrue(all(method=='GET' for method,url in requests))
            self.assertFalse(any('consent' in url for method,url in requests))
            evidence=read_json(Path(temp)/'application-route.json')
            self.assertEqual(len(evidence['observations']),2)
            self.assertEqual(len(context.pages),0)
            browser.close()

    def test_login_navigation_is_an_explicit_boundary(self):
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context()
            def serve(route):
                if route.request.url.endswith('/apply'):
                    route.fulfill(status=200,content_type='text/html',body='<script>location.replace("/login")</script>')
                else:route.fulfill(status=200,content_type='text/html',body='<h1>Sign in</h1><input type="password">')
            context.route('**/*',serve)
            with patch('joblazy.routes.public_url',return_value=True),self.assertRaisesRegex(NeedsInput,'Employer sign-in'):
                resolve_application({'url':'https://employer.test/apply'},context,Path(temp))
            observation=read_json(Path(temp)/'application-route.json')['observations'][-1]
            self.assertEqual(observation['boundary'],'employer_sign_in')
            self.assertEqual(observation['requested_url'],'https://employer.test/apply')
            self.assertEqual(len(context.pages),0)
            browser.close()

    def test_amazon_email_first_gate_stops_before_application_mapping(self):
        with sync_playwright() as pw,tempfile.TemporaryDirectory() as temp:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context();requests=[]
            def serve(route):
                requests.append((route.request.method,route.request.url))
                if route.request.url.endswith('/apply'):
                    route.fulfill(status=302,headers={'location':'https://passport.amazon.jobs/'})
                else:
                    route.fulfill(status=200,content_type='text/html',body=
                        '<h1>Sign in</h1><form action="/continue" method="post">'
                        '<input type="email" name="email"><button>Continue</button></form>')
            context.route('**/*',serve)
            with patch('joblazy.routes.public_url',return_value=True),self.assertRaisesRegex(NeedsInput,'Employer sign-in'):
                resolve_application({'url':'https://www.amazon.jobs/apply'},context,Path(temp))
            observation=read_json(Path(temp)/'application-route.json')['observations'][-1]
            self.assertEqual(observation['boundary'],'employer_sign_in')
            self.assertEqual(observation['page_url'],'https://passport.amazon.jobs/')
            self.assertTrue(all(method=='GET' and '/continue' not in url for method,url in requests))
            self.assertEqual(len(context.pages),0)
            browser.close()
