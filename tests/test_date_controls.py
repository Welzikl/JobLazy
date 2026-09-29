import copy
import unittest
from playwright.sync_api import sync_playwright

from joblazy.browser import scan, fill_plan, verify_fields
from joblazy.mapping import plan_fields
from .test_application_defaults import candidate, field


CALENDAR = '''<form><div class="ashby-application-form-field-entry" data-field-path="start">
<label class="ashby-application-form-question-title">Next available starting date</label>
<div class="react-datepicker-wrapper"><input class="ashby-application-form-input-date" type="text" placeholder="Pick date..."></div>
</div><label>Email<input name="email" type="email"></label></form><script>
let year=2099, month=1, chosen=null;window.dateChanges=0;
const input=document.querySelector('.ashby-application-form-input-date');
function popup() {
 document.querySelector('.ashby-application-form-input-date-popup')?.remove();
 const box=document.createElement('div');box.className='ashby-application-form-input-date-popup';
 const title=document.createElement('h4');title.className='ashby-application-form-input-date-popup-title';
 title.textContent=new Date(year,month,1).toLocaleString('en-US',{month:'long',year:'numeric'});box.append(title);
 for(const [direction,delta] of [['previous',-1],['next',1]]) {
  const button=document.createElement('button');button.type='button';button.dataset.direction=direction;
  button.className='ashby-application-form-input-date-popup-header-button';
  button.onclick=()=>{month+=delta;if(month<0){month=11;year--;}if(month>11){month=0;year++;}popup();};box.append(button);
 }
 for(let day=1;day<=new Date(year,month+1,0).getDate();day++) {
  const option=document.createElement('div');option.className='react-datepicker__day';
  option.setAttribute('role','option');option.textContent=String(day);
  option.setAttribute('aria-selected',String(chosen===`${year}-${month}-${day}`));
  if(window.disableDates)option.setAttribute('aria-disabled','true');
  option.onclick=()=>{if(window.disableDates)return;chosen=`${year}-${month}-${day}`;window.dateChanges++;
   input.value=`${String(month+1).padStart(2,'0')}/${String(day).padStart(2,'0')}/${year}`;box.remove();};box.append(option);
 }
 document.body.append(box);
}
input.onclick=popup;
input.onkeydown=e=>{if(e.key==='Escape')document.querySelector('.ashby-application-form-input-date-popup')?.remove();};
</script>'''


class DateControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()

    def page(self, html=CALENDAR):
        page=self.browser.new_page();self.addCleanup(page.close)
        page.route('**/*',lambda route:route.abort());page.set_content(html)
        return page

    def test_month_only_answer_cannot_fill_an_ashby_calendar_even_when_scoped(self):
        page=self.page();p=candidate();before=copy.deepcopy(p)
        for scoped in (False,True):
            with self.subTest(scoped=scoped):
                p['answers']=[{'question':'Next available starting date','scope':'fixture','value':'Available to start in March 2099.'}] if scoped else []
                plan=plan_fields(scan(page),p,'fixture')
                self.assertFalse(any(f['value']=='Available to start in March 2099.' for f in plan['fields']))
                self.assertTrue(any('exact date' in f['reason'].lower() for f in plan['unresolved']))
                fill_plan(page,plan)
                self.assertEqual(page.locator('.ashby-application-form-input-date').input_value(),'')
        self.assertEqual(p['application_defaults'],before['application_defaults'])

    def test_confirmed_date_is_selected_once_and_later_typing_invalidates_it(self):
        page=self.page();p=candidate();p['application_defaults']['availability']['exact_day']='2099-03-05'
        plan=plan_fields(scan(page),p,'fixture');dates=[f for f in plan['fields'] if f.get('exact_date')]
        self.assertEqual([f['value'] for f in dates],['2099-03-05'])
        for _ in range(2):
            fill_plan(page,plan)
            self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        self.assertEqual(page.evaluate('window.dateChanges'),1)
        picker=page.locator('.ashby-application-form-input-date')
        self.assertEqual(picker.input_value(),'03/05/2099')
        picker.fill('03/06/2099')
        self.assertFalse(next(v['ok'] for v in verify_fields(page,plan) if v['id']==dates[0]['id']))

    def test_calendar_disabled_day_remains_unverified(self):
        page=self.page();page.evaluate('window.disableDates=true')
        p=candidate();p['application_defaults']['availability']['exact_day']='2099-03-05'
        plan=plan_fields(scan(page),p,'fixture');fill_plan(page,plan)
        self.assertEqual(page.evaluate('window.dateChanges'),0)
        self.assertTrue(any(not v['ok'] for v in verify_fields(page,plan)))

    def test_native_and_scoped_dates_require_real_unambiguous_days(self):
        page=self.page('<label>Next available starting date<input type="date" required></label>');p=candidate()
        for value in ('March 2099','2099-02-30','03/05/2099','Available to start in March 2099.'):
            p['answers']=[{'question':'Next available starting date','scope':'fixture','value':value}]
            self.assertEqual(plan_fields(scan(page),p,'fixture')['fields'],[])
        p['answers'][0]['value']='Available to start on 5 March 2099.'
        plan=plan_fields(scan(page),p,'fixture');fill_plan(page,plan)
        self.assertEqual(page.locator('input').input_value(),'2099-03-05')
        self.assertTrue(verify_fields(page,plan)[0]['ok'])

    def test_exact_default_does_not_replace_scoped_answer_or_infer_notice(self):
        p=candidate();p['application_defaults']['availability']['exact_day']='2099-03-05'
        f=field('Next available starting date','date')
        p['answers']=[{'question':f['label'],'scope':'fixture','value':'2099-03-12'}]
        self.assertEqual(plan_fields([f],p,'fixture')['fields'][0]['value'],'2099-03-12')
        self.assertEqual(plan_fields([field('What is your notice period?')],p,'fixture')['fields'],[])
        for day in ('2099-02-30','2099-04-05','2020-03-05'):
            p['application_defaults']['availability']['exact_day']=day
            self.assertEqual(plan_fields([f],p,'new')['fields'],[])


if __name__=='__main__':unittest.main()
