"""Select a confirmed full date through Ashby's observed calendar controls."""
import calendar
import re
from datetime import date
from playwright.sync_api import Error as BrowserError


def select_ashby_date(page, field):
    wanted=date.fromisoformat(field['value'])
    picker=page.locator(f'[data-jpaf-id="{field["id"]}"]')
    months={name:i for i,name in enumerate(calendar.month_name) if name}
    try:
        if picker.count()!=1 or picker.is_disabled():return False
        picker.evaluate('''e=>{
          e.removeAttribute('data-joblazy-date-choice');
          if(!e.__joblazyDateObserver) {
            e.__joblazyDateObserver=true;
            for(const event of ['input','change'])e.addEventListener(event,()=>e.removeAttribute('data-joblazy-date-choice'));
          }
        }''')
        picker.click()
        popup=page.locator('.ashby-application-form-input-date-popup').filter(visible=True)
        popup.wait_for(state='visible',timeout=2000)
        if popup.count()!=1:return False
        for _ in range(25):
            title=popup.locator('.ashby-application-form-input-date-popup-title')
            if title.count()!=1:return False
            match=re.fullmatch(r'([A-Za-z]+) (\d{4})',title.inner_text().strip())
            if not match or match[1] not in months:return False
            current=(int(match[2]),months[match[1]])
            delta=(wanted.year-current[0])*12+wanted.month-current[1]
            if abs(delta)>24:return False
            if not delta:break
            button=popup.locator(f'button[data-direction="{"next" if delta>0 else "previous"}"]')
            if button.count()!=1 or not button.is_enabled():return False
            previous=title.inner_text();button.click()
            for _ in range(10):
                if title.inner_text()!=previous:break
                picker.page.wait_for_timeout(50)
            else:return False
        else:return False
        day=popup.locator('.react-datepicker__day:not(.react-datepicker__day--outside-month)').filter(has_text=re.compile(rf'^{wanted.day}$'))
        if day.count()!=1 or day.get_attribute('aria-disabled')=='true' or 'react-datepicker__day--disabled' in (day.get_attribute('class') or ''):return False
        if day.get_attribute('aria-selected')!='true':
            day.click()
            picker.click()
            popup.wait_for(state='visible',timeout=2000)
        if day.get_attribute('aria-selected')!='true':return False
        value=picker.input_value()
        if not value.strip():return False
        # Bind the rendered value to the actual selected calendar day. Ordinary
        # typing or a later change clears this evidence and cannot pass as saved.
        picker.press('Escape')
        picker.evaluate('(e,choice)=>e.setAttribute("data-joblazy-date-choice",JSON.stringify(choice))',
                        {'iso':wanted.isoformat(),'value':value})
        return True
    except BrowserError:
        return False
    finally:
        if picker.count()==1:
            try:picker.press('Escape',timeout=1000)
            except BrowserError:pass
