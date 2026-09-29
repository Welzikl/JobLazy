import unittest
import copy
from playwright.sync_api import sync_playwright
from joblazy.browser import scan,fill_plan,verify_fields
from joblazy.mapping import plan_fields,SENSITIVE
from .support import example_profile


class LocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def exercise(self,options,extra=''):
        page=self.browser.new_page();self.addCleanup(page.close)
        page.set_content('''<div class="select__container"><label>Current Location
          <input role="combobox" class="select__input" aria-controls="locations"></label>
          <div class="select__single-value">London, Ontario, Canada</div>
          <div id="locations" role="listbox">'''+''.join(
              '<div role="option" onclick="window.chosen.push(this.textContent);document.querySelector(\'.select__single-value\').textContent=this.textContent">'+o+'</div>' for o in options)+
          '</div></div>'+extra+'<script>window.chosen=[]</script>')
        profile=example_profile();profile['applicant']['address'].update(city='London',state_full='England',country='United Kingdom')
        plan=plan_fields(scan(page),profile,'fixture')
        self.assertEqual(plan['fields'][0]['value'],'London, England, United Kingdom')
        fill_plan(page,plan)
        return page,plan

    def test_country_qualified_selection_corrects_canada_and_ignores_first_result(self):
        page,plan=self.exercise(['London, Ontario, Canada','London, England, United Kingdom'])
        self.assertEqual(page.evaluate('window.chosen'),['London, England, United Kingdom'])
        self.assertTrue(verify_fields(page,plan)[0]['ok'])
        fill_plan(page,plan)
        self.assertEqual(page.evaluate('window.chosen'),['London, England, United Kingdom'])
        page.locator('.select__single-value').evaluate("e=>e.textContent='London, Ontario, Canada'")
        self.assertFalse(verify_fields(page,plan)[0]['ok'])

    def test_foreign_duplicate_and_other_widget_options_never_commit(self):
        cases=[(['London, Ontario, Canada'],''),
            (['London, England, United Kingdom']*2,''),
            (['London, Ontario, Canada'],'<div role="listbox"><div role="option" onclick="window.chosen.push(\'wrong-widget\')">London, England, United Kingdom</div></div>')]
        for options,extra in cases:
            with self.subTest(options=options,extra=bool(extra)):
                page,plan=self.exercise(options,extra)
                self.assertEqual(page.evaluate('window.chosen'),[])
                self.assertFalse(verify_fields(page,plan)[0]['ok'])
                # Typed text alone cannot establish a committed selection.
                page.locator('.select__single-value').evaluate('e=>e.remove()')
                self.assertFalse(verify_fields(page,plan)[0]['ok'])

    def test_observed_london_county_label_is_selected_and_actual_value_checked(self):
        label='London, Greater London, England, United Kingdom'
        page,plan=self.exercise(['London, Ontario, Canada',label,'England, United Kingdom'])
        self.assertEqual(page.evaluate('window.chosen'),[label])
        self.assertTrue(verify_fields(page,plan)[0]['ok'])
        fill_plan(page,plan)
        self.assertEqual(page.evaluate('window.chosen'),[label])
        page.locator('.select__single-value').evaluate("e=>e.textContent='London, Ontario, Canada'")
        self.assertFalse(verify_fields(page,plan)[0]['ok'])
        for choices in ([label,label],[label,'London, England, United Kingdom']):
            page,plan=self.exercise(choices)
            self.assertEqual(page.evaluate('window.chosen'),[])
            self.assertFalse(verify_fields(page,plan)[0]['ok'])

    def test_unknown_country_is_not_guessed_and_plain_city_is_unchanged(self):
        profile=example_profile();profile['applicant']['address'].pop('country',None)
        field={'id':'city','label':'Current Location','type':'text','combo':True}
        self.assertEqual(plan_fields([field],profile,'fixture')['fields'],[])
        field['combo']=False
        self.assertEqual(plan_fields([field],profile,'fixture')['fields'][0]['value'],'London')

    def test_current_country_of_residence_never_maps_city_or_phone_country(self):
        page=self.browser.new_page();self.addCleanup(page.close)
        page.set_content('''<div class="select__container"><label>Please let us know your current country of residence
          <input role="combobox" class="select__input" aria-controls="countries"></label>
          <div class="select__single-value"></div><div id="countries" role="listbox">
          <div role="option">United States</div><div role="option" onclick="document.querySelector('.select__single-value').textContent=this.textContent">United Kingdom</div></div></div>''')
        profile=example_profile();profile['applicant']['address'].update(city='London',state_full='England',country='United Kingdom')
        profile['applicant']['identity']['phone']='+17607040000'
        plan=plan_fields(scan(page),profile,'fixture')
        self.assertEqual(plan['fields'][0]['value'],'United Kingdom')
        self.assertEqual(plan['fields'][0]['source_ref'],'/applicant/address/country')
        fill_plan(page,plan);self.assertTrue(verify_fields(page,plan)[0]['ok'])
        profile['applicant']['address'].pop('country')
        self.assertEqual(plan_fields(scan(page),profile,'fixture')['fields'],[])

    def test_preferred_work_location_uses_targeting_separately_from_residence(self):
        self.assertIsNone(SENSITIVE.search('Preferred location?'))
        for text in ('Were you referred by an employee?','referred_by','was_referred'):
            self.assertIsNotNone(SENSITIVE.search(text))
        page=self.browser.new_page();self.addCleanup(page.close)
        page.set_content('<label>Current city<input></label><label>Preferred location?<input></label>')
        profile=example_profile();profile['applicant']['address'].update(city='Toronto',country='Canada')
        profile['targeting']['config']={'location':{'city':'London','country':'United Kingdom'}}
        before=copy.deepcopy(profile);fields=scan(page);plan=plan_fields(fields,profile,'fixture')
        preferred=next(f for f in fields if f['label']=='Preferred location?')
        answer=next(f for f in plan['fields'] if f['id']==preferred['id'])
        self.assertEqual(answer['value'],'London, United Kingdom')
        self.assertEqual(answer['source_ref'],'/targeting/config/location')
        fill_plan(page,plan)
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        self.assertEqual(page.locator('input').nth(0).input_value(),'Toronto')
        self.assertEqual(page.locator('input').nth(1).input_value(),'London, United Kingdom')
        self.assertEqual(profile,before)
        for targeting in ({},{'config':{'location':{'city':'London'}}},'London, UK'):
            profile['targeting']=targeting
            self.assertEqual(plan_fields([preferred],profile,'fixture')['fields'],[])
        profile=before
        for change in ({'description':'Only choose a location if you agree to relocate.'},{'combo':True},{'type':'select','options':['London']}):
            self.assertEqual(plan_fields([{**preferred,**change}],profile,'fixture')['fields'],[])
        profile['answers']=[{'question':'Preferred location?','scope':'fixture','value':'Manchester, United Kingdom'}]
        self.assertEqual(plan_fields([preferred],profile,'fixture')['fields'][0]['value'],'Manchester, United Kingdom')
        profile['answers']*=2
        self.assertEqual(plan_fields([preferred],profile,'fixture')['fields'],[])


if __name__=='__main__':unittest.main()
