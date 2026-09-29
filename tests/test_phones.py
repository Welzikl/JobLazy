import copy
import unittest
from playwright.sync_api import sync_playwright
from joblazy.phones import phone_info
from joblazy.mapping import plan_fields
from joblazy.browser import scan,fill_plan,verify_fields
from .support import example_profile

class PhoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def page(self,html):
        page=self.browser.new_page();self.addCleanup(page.close);page.set_content(html);return page
    def profile(self,number='+12025550123'):
        p=example_profile();p['applicant']['identity']['phone']=number;p['resume']['candidate']['phone']=number
        p['applicant']['address']['country']='United Kingdom';return p
    def native(self,extra_options=''):
        return '''<fieldset><legend>Phone</legend><label>Country*<select name="country">
          <option value="GB">United Kingdom (+44)</option><option value="CA">Canada (+1)</option>
          <option value="US">United States (+1)</option>'''+extra_options+'''</select></label>
          <label>Phone*<input type="tel" name="phone"></label></fieldset>
          <fieldset><legend>Address</legend><label>Country<select name="residence"><option>Canada</option><option>United Kingdom</option></select></label></fieldset>'''
    def test_us_phone_and_uk_residence_stay_separate_and_resume_is_idempotent(self):
        page=self.page(self.native());p=self.profile();before=copy.deepcopy(p)
        fields=scan(page);plan=plan_fields(fields,p,'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('[name=country]').input_value(),'US')
        self.assertEqual(page.locator('[name=phone]').input_value(),'2025550123')
        self.assertEqual(page.locator('[name=residence]').input_value(),'United Kingdom')
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        page.locator('[name=phone]').fill('(202) 555-0123')
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        fill_plan(page,plan);self.assertEqual(p,before)
        self.assertEqual(page.locator('[name=phone]').input_value(),'(202) 555-0123')
        page.locator('[name=country]').select_option('CA')
        self.assertFalse(any(v['ok'] for v in verify_fields(page,plan)[:2]))
    def test_canadian_number_does_not_select_us_from_shared_calling_code(self):
        page=self.page(self.native());plan=plan_fields(scan(page),self.profile('+14165550123'),'fixture')
        fill_plan(page,plan);self.assertEqual(page.locator('[name=country]').input_value(),'CA')
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
    def test_plain_text_phone_in_the_same_group_uses_the_national_number(self):
        page=self.page(self.native().replace('type="tel"','type="text"'))
        plan=plan_fields(scan(page),self.profile(),'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('[name=phone]').input_value(),'2025550123')
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
    def test_ambiguous_shared_number_and_invalid_number_do_not_guess_residence(self):
        self.assertIsNone(phone_info('+18005550123')['region'])
        for phone in ('+18005550123','2025550123','+1','+12025550123 ext 12'):
            page=self.page(self.native());plan=plan_fields(scan(page),self.profile(phone),'fixture');fill_plan(page,plan)
            self.assertEqual(page.locator('[name=country]').input_value(),'GB')
            self.assertEqual(page.locator('[name=phone]').input_value(),'')
    def test_duplicate_country_options_leave_phone_blank(self):
        page=self.page(self.native('<option value="US">United States (+1)</option>'))
        plan=plan_fields(scan(page),self.profile(),'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('[name=country]').input_value(),'GB');self.assertEqual(page.locator('[name=phone]').input_value(),'')
    def test_plain_calling_code_and_formatted_uk_number_are_verified_together(self):
        page=self.page('''<fieldset><legend>Phone</legend><label>Country code<input autocomplete="tel-country-code"></label><label>Phone<input type="tel"></label></fieldset>''')
        plan=plan_fields(scan(page),self.profile('+442083661177'),'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('input').nth(0).input_value(),'+44')
        page.locator('input').nth(1).fill('020 8366 1177')
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        page.locator('input').nth(1).fill('020 8366 1178')
        self.assertFalse(verify_fields(page,plan)[1]['ok'])
    def test_aria_country_requires_its_own_committed_option(self):
        page=self.page('''<fieldset><legend>Phone</legend><div class="select__container">
          <label for="country">Country*</label><input id="country" role="combobox" class="select__input" aria-controls="phone-options">
          <div class="select__single-value">United Kingdom (+44)</div><div role="listbox" id="phone-options">
          <div role="option">Canada (+1)</div><div role="option" onclick="document.querySelector('.select__single-value').textContent=this.textContent">United States (+1)</div></div></div>
          <label>Phone*<input name="phone" type="tel"></label></fieldset>
          <div role="listbox"><div role="option">United States (+1)</div></div>''')
        plan=plan_fields(scan(page),self.profile(),'fixture');fill_plan(page,plan)
        self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        page.locator('.select__single-value').evaluate('e=>e.remove()')
        self.assertFalse(any(v['ok'] for v in verify_fields(page,plan)))
    def test_scoped_phone_answer_is_used_without_changing_canonical_number(self):
        page=self.page(self.native());p=self.profile();p['answers']=[{'question':'Phone*','scope':'fixture','value':'+14165550123'}]
        plan=plan_fields(scan(page),p,'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('[name=country]').input_value(),'CA')
        self.assertEqual(page.locator('[name=phone]').input_value(),'4165550123')
        self.assertEqual(p['applicant']['identity']['phone'],'+12025550123')
    def test_another_widgets_selected_label_cannot_verify_phone_country(self):
        page=self.page('''<fieldset><legend>Phone</legend><label>Country<input role="combobox" value="United States (+1)"></label>
          <div class="select__container"><div class="select__single-value">United States (+1)</div></div>
          <label>Phone<input type="tel" value="2025550123"></label></fieldset>''')
        plan=plan_fields(scan(page),self.profile(),'fixture')
        self.assertFalse(any(v['ok'] for v in verify_fields(page,plan)))
