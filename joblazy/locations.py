"""Select only an exact, country-qualified location in its own autocomplete."""
import time


def fill_location(page,field,timeout=3.5):
    loc=page.locator(f'[data-jpaf-id="{field["id"]}"]')
    loc.evaluate("e=>{e.removeAttribute('data-joblazy-location-choice-value');e.removeAttribute('data-joblazy-location-choice-label')}")
    loc.fill(str(field['value']))
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        matched=loc.evaluate('''(e,wanted)=>{
          const norm=s=>String(s??'').trim().replace(/\\s+/g,' ').toLocaleLowerCase();
          let options=[];
          const controlled=(e.getAttribute('aria-controls')||e.getAttribute('aria-owns')||'').split(/\\s+/).filter(Boolean);
          for(const id of controlled) options.push(...(document.getElementById(id)?.querySelectorAll('[role=option]')||[]));
          if(!options.length && e.id) options=[...document.querySelectorAll(`[id^="react-select-${CSS.escape(e.id)}-option"]`)];
          if(!options.length) {
            const shell=e.closest('.select-shell,.select__container,.ashby-application-form-field-entry');
            options=[...(shell?.querySelectorAll('[role=listbox] [role=option]')||[])];
          }
          options=[...new Set(options)].filter(o=>o.getClientRects().length && o.getAttribute('aria-disabled')!=='true');
          for(const o of options)o.removeAttribute('data-joblazy-location-option');
          // Observed Ashby label adds the administrative county. Keep aliases
          // explicit: substring/fuzzy matching would also admit foreign Londons.
          const labels=new Set([norm(wanted)]);
          if(norm(wanted)==='london, england, united kingdom')
            labels.add('london, greater london, england, united kingdom');
          const matches=options.filter(o=>labels.has(norm(o.innerText)));
          if(matches.length===1)matches[0].setAttribute('data-joblazy-location-option',e.getAttribute('data-jpaf-id'));
          return matches.length;
        }''',str(field['value']))
        if matched==1:
            choice=page.locator(f'[data-joblazy-location-option="{field["id"]}"]')
            if choice.count()!=1:return False
            selected_label=choice.inner_text().strip()
            choice.click(timeout=2000)
            loc.evaluate("(e,value)=>e.setAttribute('data-joblazy-location-choice-value',value)",str(field['value']))
            loc.evaluate("(e,value)=>e.setAttribute('data-joblazy-location-choice-label',value)",selected_label)
            return True
        if matched>1:return False
        page.wait_for_timeout(100)
    return False
