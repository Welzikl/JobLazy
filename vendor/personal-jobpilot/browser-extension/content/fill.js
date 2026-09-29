/* Injected on demand. Defines window.__jpafApply(plan) -> Promise<stats>.
 * Sets values React/Vue-safely. NEVER submits the form. */
(() => {
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function visibleOptions() {
    return [...document.querySelectorAll("[role='option'], li[role='menuitem']")]
      .filter((o) => o.getClientRects().length > 0);
  }

  // Tenant vocabularies differ — Workday listbox options aren't visible until the
  // popup opens, so the smart matching has to happen HERE, at fill time (the plan
  // only carries the short answer like "Yes"/"Male"/"No"). Mirrors
  // autofill_mapper._match_choice so EEO answers resolve to verbose option text.
  const OPTION_SYNONYMS = {
    "mobile": ["cellular", "cell", "mobile phone"],
    "united states": ["united states of america", "usa"],
    "male": ["man"], "female": ["woman"],
    "heterosexual": ["straight"],
    "two or more races": ["two or more", "multiracial"],
  };
  // NB: norm() turns "don't" into "don t", so a "dont wish" hint can never fire.
  // "wish to answer" is what actually catches "I don't wish to answer", the most
  // common EEO decline wording.
  const DECLINE_HINTS = ["decline", "do not wish", "prefer not",
                         "not to answer", "not wish", "choose not", "rather not",
                         "wish to answer", "want to answer", "wish to disclose",
                         "not to disclose", "not to identify", "not specified"];
  // How consent questions spell Yes/No: ["Confirmed"], ["I acknowledge"],
  // ["No, I am not a current or former Government Official", …]
  const AFFIRM_HINTS = ["confirmed", "confirm", "i confirm", "i agree", "agree",
                        "i acknowledge", "acknowledge", "i accept", "accept",
                        "i understand", "i consent", "i have read"];
  const NEGATE_HINTS = ["not", "i do not", "i dont", "i have not", "i am not",
                        "i havent", "never", "none"];

  // Choose the best option element for `value` among a list of {el, t:normText}.
  // strict=true keeps only the precise heuristics (exact / synonym / decline /
  // yes-no leading / substring) — the bare token-overlap fallback is for
  // FILTERED lists only. Against an unfiltered vocabulary (a react-select
  // school list opens alphabetically) token overlap happily commits
  // "Adams State University" for "California Polytechnic State University".
  function chooseChoice(value, opts, strict) {
    const nv = norm(value);
    const cands = [nv, ...(OPTION_SYNONYMS[nv] || [])];
    for (const c of cands) { const o = opts.find((x) => x.t === c); if (o) return o.el; }
    if (/^(decline|prefer not|do not wish|dont wish|i do not wish|i dont wish)/.test(nv)) {
      const o = opts.find((x) => DECLINE_HINTS.some((h) => x.t.includes(h)));
      if (o) return o.el;
    }
    if (nv === "yes" || nv === "no") {
      let o = opts.find((x) => x.t.split(" ")[0] === nv);
      if (!o) {
        const hints = nv === "yes" ? AFFIRM_HINTS : NEGATE_HINTS;
        o = opts.find((x) => hints.some((h) => x.t === h || x.t.startsWith(h + " ")));
      }
      if (o) return o.el;
    }
    for (const c of cands) {
      const o = anchoredMatch(c, opts);
      if (o) return o;
    }
    if (strict) return null;
    return tokenOverlap(nv, opts);
  }

  // `long` is `short` plus a trailing qualifier, on a word boundary:
  //   "asian" -> "asian not hispanic or latino"  yes — same answer, spelled longer
  //   "economics" -> "home economics"            NO  — a different subject
  const isAnchored = (short, long) => long === short || long.startsWith(short + " ");

  // The one option that is `c` plus a qualifier (either direction), or null.
  // Two equally-close candidates is a coin flip ("Bachelor of Science" against
  // both "…in Physics" and "…in Economics") — refuse rather than pick a major.
  function anchoredMatch(c, opts) {
    if (!c) return null;
    const hits = opts.filter((x) => x.t && (isAnchored(c, x.t) || isAnchored(x.t, c)));
    if (!hits.length) return null;
    if (hits.length === 1) return hits[0].el;
    // tightest = fewest extra WORDS; character length would rank "…in Physics"
    // above "…in Economics" and quietly commit a major he didn't study
    hits.sort((a, b) => a.t.split(" ").length - b.t.split(" ").length);
    const n0 = hits[0].t.split(" ").length, n1 = hits[1].t.split(" ").length;
    return n0 !== n1 ? hits[0].el : null;
  }

  // Last tier, and the only one that can be confidently WRONG — so it is gated.
  // An option qualifies only if it contains EVERY distinctive (>2 char) word of
  // the target: "Master of Science" shares just "science" with "Bachelor of
  // Science", so it no longer qualifies. Ties return null and the field is
  // flagged for review instead of filled with a plausible wrong answer.
  function tokenOverlap(nv, opts) {
    const dw = nv.split(" ").filter((w) => w.length > 2);
    if (!dw.length) return null;
    const covering = opts.filter((x) => {
      const ow = new Set(x.t.split(" "));
      return dw.every((w) => ow.has(w));
    });
    if (!covering.length) return null;
    if (covering.length === 1) return covering[0].el;
    covering.sort((a, b) => a.t.split(" ").length - b.t.split(" ").length);
    const n0 = covering[0].t.split(" ").length, n1 = covering[1].t.split(" ").length;
    return n0 !== n1 ? covering[0].el : null;
  }

  function bestOption(value) {
    const opts = visibleOptions().map((el) => ({ el, t: norm(el.innerText) }));
    return chooseChoice(value, opts);
  }

  // Options belonging to THIS combobox only. A page can hold several open/
  // hidden option lists at once (react-select portals, intl-tel-input's
  // country list) — matching globally can commit a value into the wrong
  // widget. react-select ids its options "react-select-<inputId>-option-N".
  function comboOptions(el) {
    const id = el.id || "";
    if (id) {
      const own = [...document.querySelectorAll(`[id^="react-select-${CSS.escape(id)}-option"]`)];
      if (own.length) return own;
    }
    const lb = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    if (lb) {
      const box = document.getElementById(lb);
      if (box) {
        const own = [...box.querySelectorAll("[role='option']")];
        if (own.length) return own;
      }
    }
    const shell = el.closest(".select-shell, .select__container, [class*='select']") || el.parentElement;
    if (shell) {
      const own = [...shell.querySelectorAll(".select__menu [role='option'], [role='listbox'] [role='option']")];
      if (own.length) return own;
    }
    return [...document.querySelectorAll("[role='option'], li[role='menuitem']")]
      .filter((o) => o.getClientRects().length > 0 && !(o.className || "").toString().includes("iti__"));
  }

  function bestOptionIn(opts, value, strict) {
    return chooseChoice(value, opts.filter((o) => o.getClientRects().length > 0)
      .map((o) => ({ el: o, t: norm(o.innerText) })), strict);
  }

  // Did the combobox actually COMMIT a value? react-select renders a
  // .select__single-value / multi-value chip; its input keeps transient typed
  // text, so for those the chip is the only truth. Plain autocompletes keep
  // the committed text in the input itself. Walk up level by level (the chip
  // is a SIBLING branch of the input) but stop at the widget boundary so we
  // never read a neighbouring select's chip.
  function comboCommitted(el) {
    let n = el.parentElement;
    for (let hops = 0; n && hops < 6; hops++) {
      if (n.querySelector(".select__single-value, .select__multi-value, " +
                          "[class*='single-value'], [class*='multi-value'], [class*='selectedItem']"))
        return true;
      const cl = n.classList;
      if (cl && (cl.contains("select-shell") || cl.contains("select__container") ||
                 cl.contains("select") || n.tagName === "FORM")) break;
      n = n.parentElement;
    }
    if ((el.className || "").toString().includes("select__input")) return false;
    return !!(el.value || "").trim();
  }

  function realClick(el) {
    // pointer/mouse prelude for React-Select style widgets that act on mousedown
    for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup"])
      el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, composed: true, view: window }));
    // native click() reliably crosses the isolated/main world boundary;
    // a synthetic MouseEvent("click") from a content script does not always.
    if (typeof el.click === "function") el.click();
    else el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, composed: true, view: window }));
  }

  // Workday-style <button aria-haspopup="listbox"> / role=combobox divs:
  // open the popup, click the matching [role=option].
  async function fillAriaSelect(el, value) {
    realClick(el);
    await sleep(400);
    let opt = bestOption(value);
    if (!opt) { await sleep(500); opt = bestOption(value); }  // slow portals
    if (opt) {
      realClick(opt);
      await sleep(150);
      return true;
    }
    // close whatever we opened so we don't leave the page in a weird state
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    if (document.body) document.body.click();  // native click crosses worlds
    return false;
  }

  async function waitFor(fn, timeout = 2500, step = 200) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(step);
    }
    return null;
  }

  // React-Select / autocomplete inputs. Strategy:
  //   1. OPEN the menu first (click the control) — fixed vocabularies list all
  //      options on open, and non-searchable react-selects ignore typing.
  //   2. If nothing matches, TYPE to search (async pickers: Greenhouse school
  //      search, location geo-lookup) and poll for the suggestion.
  //   3. Click the option and VERIFY the value committed (chip rendered) —
  //      typed-but-uncommitted text in a react-select is worthless.
  async function fillCombo(el, value) {
    el.focus();
    const control = el.closest(".select__control") || el;
    const menuOpen = () => comboOptions(el).some((o) => o.getClientRects().length > 0);
    realClick(control);
    // open phase shows the UNFILTERED vocabulary — match strictly, or not at all
    let opt = await waitFor(() => bestOptionIn(comboOptions(el), value, true), 900, 150);
    if (!opt && !menuOpen()) {
      // ONLY when the menu never opened: widgets that open on focus see our
      // click as a TOGGLE — one more click recovers. (Clicking again while a
      // no-strict-match menu is open would CLOSE it and kill the typed search.)
      realClick(control);
      opt = await waitFor(() => bestOptionIn(comboOptions(el), value, true), 900, 150);
    }
    if (!opt && !el.readOnly) {
      // typed phase: the list is now FILTERED by our own query, so the loose
      // token-overlap matcher is safe (async searches return close variants,
      // e.g. "California Polytechnic State University - San Luis Obispo").
      // Comma-form values ("X University, San Luis Obispo", full location
      // lines) return ZERO results from async searches and can wedge them —
      // type the prefix FIRST, like a human would, then fall back to the full
      // value for plain filter-style lists.
      const short = String(value).split(",")[0].trim();
      const queries = short && short !== String(value) ? [short, String(value)] : [String(value)];
      for (const q of queries) {
        setNative(el, q);
        opt = await waitFor(() => bestOptionIn(comboOptions(el), value) ||
                                  bestOptionIn(comboOptions(el), q), 3500, 250);
        if (opt) break;
      }
    }
    if (opt) {
      realClick(opt);
      await sleep(200);
      if (comboCommitted(el)) return true;
    }
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return comboCommitted(el);
  }

  // ---- résumé attach (DataTransfer — same trick JobRight/Simplify use) ----
  function sendBg(msg) {
    return new Promise((resolve) => {
      try {
        if (window.chrome && chrome.runtime && chrome.runtime.sendMessage)
          chrome.runtime.sendMessage(msg, resolve);
        else resolve(null);
      } catch (e) { resolve(null); }
    });
  }

  async function attachFile(el, ctx, cmd) {
    try {
      if (el.files && el.files.length) return true;  // user already attached one
      const f = await sendBg({ cmd, company: (ctx && ctx.company) || "",
                               title: (ctx && ctx.title) || "" });
      if (!f || !f.b64) return false;
      const bytes = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0));
      const name = f.filename || "resume.pdf";
      const mime = f.mime || (/\.pdf$/i.test(name) ? "application/pdf"
        : "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
      const dt = new DataTransfer();
      dt.items.add(new File([bytes], name, { type: mime }));
      el.files = dt.files;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch (e) {
      return false;
    }
  }

  // "Select one" / "--" / "" are all the widget saying nothing is chosen yet.
  const PLACEHOLDER = /^(|select|select one|select an option|choose|choose one|please select|none|n a)$/;

  // Has the USER (or the ATS, from a résumé parse) already answered this?
  // Autofill runs on half-completed forms constantly — Workday step 2, a page
  // you started by hand — and silently replacing a deliberate "No" with "Yes"
  // on a work-authorization question is the worst thing this extension could
  // do. Their answer always wins; we only fill blanks.
  function alreadyAnswered(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.type || "").toLowerCase();
    if (type === "radio" || type === "checkbox") {
      const group = el.name
        ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
      return group.some((r) => r.checked);
    }
    if (tag === "select") {
      const opt = el.selectedOptions && el.selectedOptions[0];
      return !PLACEHOLDER.test(norm(opt ? opt.text : el.value));
    }
    // ARIA dropdowns (Workday) render the choice as the control's own text
    if (!["input", "textarea"].includes(tag)) return !PLACEHOLDER.test(norm(el.innerText || ""));
    // react-select keeps transient typed text in the input — the chip is truth
    if (el.getAttribute("role") === "combobox" ||
        el.getAttribute("aria-autocomplete") === "list") return comboCommitted(el);
    return !!(el.value || "").trim();
  }

  function setNative(el, value) {
    const proto = el.tagName === "TEXTAREA"
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillSelect(el, value) {
    const nv = norm(value);
    let opt = [...el.options].find((o) => norm(o.value) === nv || norm(o.text) === nv);
    if (!opt) {  // EEO-tolerant matching over the option texts
      const chosen = chooseChoice(value, [...el.options].map((o) => ({ el: o, t: norm(o.text) })));
      opt = chosen || null;
    }
    if (opt) {
      el.value = opt.value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    return false;
  }

  function labelText(r) {
    if (r.id) {
      const l = document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
      if (l) return l.innerText;
    }
    const w = r.closest("label");
    return w ? w.innerText : "";
  }

  function fillChoice(el, value) {
    const nv = norm(value);
    const group = el.name ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
    // exact value/label, or yes/no synonyms
    for (const r of group) {
      const lbl = norm(labelText(r));
      const rv = norm(r.value);
      if (rv === nv || lbl === nv ||
          (nv === "yes" && /^(yes|true|1)$/.test(rv)) || (nv === "no" && /^(no|false|0)$/.test(rv))) {
        if (!r.checked) r.click();
        r.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
    }
    // verbose EEO radios: match the option whose label best fits (e.g. "Yes, I
    // have a disability…" for value "Yes"; "Not Hispanic or Latino" for "No").
    if (group.length > 1) {
      const chosen = chooseChoice(value, group.map((r) => ({ el: r, t: norm(labelText(r)) })));
      if (chosen) {
        if (!chosen.checked) chosen.click();
        chosen.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
    }
    if (el.type === "checkbox" && (nv === "yes" || nv === "true")) {
      if (!el.checked) el.click();
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    return false;
  }

  // Outline something the user can SEE. react-select inputs are ~3px wide and
  // ATS file inputs are visually hidden — outlining them paints stray green
  // slivers. Walk to the widget's visible container instead.
  function markTarget(el) {
    if ((el.type || "").toLowerCase() === "file") {
      const wrap = el.closest("div");
      const btn = wrap && wrap.querySelector("button");
      return btn || wrap || el;
    }
    let t = el.closest(".select__control") || el;
    for (let hops = 0; t && hops < 4; hops++) {
      const r = t.getBoundingClientRect();
      if (t.getClientRects().length && r.width >= 40 && r.height >= 10) return t;
      t = t.parentElement;
    }
    return el;
  }

  function mark(el, ok) {
    const t = markTarget(el);
    t.setAttribute("data-jpaf-state", ok ? "verified" : "review");
    t.style.outline = ok ? "2px solid #0a7e07" : "2px solid #c08a00";
    t.style.outlineOffset = "1px";
  }

  // The JobRight moment: bring the field on screen and pulse a mint glow on
  // it for ~600 ms right before the value lands. Pure feedback — mark() still
  // paints the verified/review outline afterwards.
  function flash(el) {
    const t = markTarget(el);
    try {
      const r = t.getBoundingClientRect();
      if (r.bottom < 0 || r.top > (window.innerHeight || document.documentElement.clientHeight))
        t.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) { /* detached */ }
    t.style.transition = "box-shadow .3s";
    t.style.outline = "2px solid #12c98f";
    t.style.boxShadow = "0 0 0 4px rgba(18,201,143,.25)";
    setTimeout(() => { t.style.boxShadow = ""; }, 600);
  }

  function emit(detail) {
    try { window.dispatchEvent(new CustomEvent("jpaf-progress", { detail })); } catch (e) { /* noop */ }
  }

  // Confirm that the value which reached the control is the value we intended.
  // React controls can accept events while silently rejecting state changes;
  // a successful call is therefore not enough. Mismatches remain highlighted
  // for manual review and are never treated as completed.
  function verifyValue(el, desired) {
    const tag = el.tagName.toLowerCase();
    const type = (el.type || "").toLowerCase();
    const nd = norm(desired);
    if (type === "radio" || type === "checkbox") {
      const group = el.name ? [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)] : [el];
      const wanted = type === "checkbox"
        ? String(desired).split(";").map((x) => x.trim()).filter(Boolean)
        : [desired];
      return wanted.every((value) => group.some((r) => r.checked &&
        chooseChoice(value, [{ el: r, t: norm(labelText(r) || r.value) }], true)));
    }
    if (tag === "select") {
      const o = el.selectedOptions && el.selectedOptions[0];
      return !!o && !!chooseChoice(desired, [{ el: o, t: norm(o.text || o.value) }], true);
    }
    if (!['input', 'textarea'].includes(tag)) {
      const got = norm(el.innerText || el.textContent || "");
      return !!got && (got === nd || got.includes(nd) || nd.includes(got));
    }
    if (el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete") === "list")
      return comboCommitted(el);
    return norm(el.value) === nd;
  }

  function toast(msg) {
    // the in-page panel already shows the result — the toast is for the
    // toolbar-popup flow, and it would sit right on top of the pill
    if (document.getElementById("__jpaf_host")) return;
    let t = document.getElementById("__jpaf_toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "__jpaf_toast";
      t.style.cssText =
        "position:fixed;z-index:2147483647;right:16px;bottom:16px;background:#0b1220;color:#fff;" +
        "font:600 13px/1.45 system-ui,sans-serif;padding:12px 16px;border-radius:12px;" +
        "box-shadow:0 14px 40px rgba(0,0,0,.45);max-width:320px";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    clearTimeout(t._h);
    t._h = setTimeout(() => t.remove(), 7000);
  }

  window.__jpafApply = async function (plan) {
    let filled = 0, review = 0, fileFlags = 0, resumeAttached = 0, coverAttached = 0, kept = 0;
    const metaById = new Map((plan._scanMeta || []).map((m) => [m.id, m]));
    const fileFieldCount = (plan.fields || []).filter((x) => x.source === "file").length;
    const comboRetries = [];
    const reviewFields = [];
    const noteReview = (f, el) => {
      const meta = metaById.get(f.id) || {};
      const label = (meta.label ||
        (el && (el.getAttribute("aria-label") || el.name || el.id)) || f.id).toString().slice(0, 70);
      reviewFields.push({ id: f.id, label });
    };
    // One field; true when a value verifiably landed.
    async function fillOne(f, el) {
      if (f.source === "file") {
        const meta = metaById.get(f.id) || {};
        // combine scan meta with the element's own attributes ("Attach" labels
        // carry nothing — the input's id/name is what says resume vs cover)
        const lab = norm((meta.label || "") + " " + (meta.name || "") + " " + (meta.section || "") + " " +
                         (el.getAttribute("aria-label") || "") + " " + (el.name || "") + " " + (el.id || ""));
        const isCover = /cover/.test(lab);
        const isResume = !isCover && (/resume|curriculum|\bcv\b/.test(lab) ||
                         (fileFieldCount === 1 && !/transcript|portfolio|photo/.test(lab)));
        let attached = false;
        if (isResume || isCover) flash(el);
        if (isResume) attached = await attachFile(el, plan._ctx, "resume_file");
        else if (isCover) attached = await attachFile(el, plan._ctx, "cover_letter_file");
        if (attached) {
          mark(el, true); filled++;
          if (isResume) resumeAttached++; else coverAttached++;
        } else if (isCover) {
          // no tailored letter for this company — quietly leave it manual
          fileFlags++;
        } else {
          mark(el, false); fileFlags++; review++; noteReview(f, el);
        }
        return attached;
      }
      if (f.value == null || f.value === "") {
        if (f.needs_review) { mark(el, false); review++; noteReview(f, el); }
        return false;
      }
      // their answer wins — never overwrite one that is already there
      if (alreadyAnswered(el)) { kept++; return false; }
      flash(el);
      try {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || "").toLowerCase();
        const isAria = !["input", "select", "textarea"].includes(tag) ||
                       (metaById.get(f.id) || {}).type === "aria_select";
        const isCombo = tag === "input" && (
          el.getAttribute("role") === "combobox" ||
          el.getAttribute("aria-autocomplete") === "list" ||
          el.getAttribute("aria-haspopup") === "listbox" ||
          (metaById.get(f.id) || {}).combo);
        let ok;
        let target = el;
        if (isAria) ok = await fillAriaSelect(el, f.value);
        else if (tag === "select") ok = fillSelect(el, f.value);
        else if (type === "radio" || type === "checkbox") {
          // multi-value checkbox answers ("Asian; White"): one box per part
          const parts = type === "checkbox"
            ? String(f.value).split(";").map((s) => s.trim()).filter(Boolean) : [];
          if (parts.length > 1) ok = parts.map((v) => fillChoice(el, v)).some(Boolean);
          else ok = fillChoice(el, f.value);
        }
        else if (isCombo) ok = await fillCombo(el, f.value);
        else { setNative(el, f.value); ok = true; }
        if (!ok && isCombo) comboRetries.push(f);
        const verified = !!ok && verifyValue(target, f.value);
        mark(target, verified && !f.needs_review);
        if (verified) filled++;
        if (f.needs_review || !verified) { review++; noteReview(f, target); }
        return verified;
      } catch (e) {
        mark(el, false); review++; noteReview(f, el);
        return false;
      }
    }

    // Sequential (not forEach) — ARIA dropdowns open popups that must close
    // before the next field is touched. The 90 ms stagger is deliberate: it is
    // what makes the fill watchable (and what the widget's progress bar paces).
    const fields = plan.fields || [];
    for (let i = 0; i < fields.length; i++) {
      const f = fields[i];
      const el = document.querySelector(`[data-jpaf-id="${f.id}"]`);
      const ok = el ? await fillOne(f, el) : false;
      const meta = metaById.get(f.id) || {};
      emit({ type: "field", index: i, total: fields.length, ok,
             label: String(meta.label || (el && (el.getAttribute("aria-label") || el.name || el.id)) || f.id).slice(0, 70) });
      await sleep(90);
    }
    // Final retry pass for combos that failed mid-run: résumé uploads and
    // conditional notes re-render the whole React form while we fill — once
    // it settles, a fresh attempt on a freshly-located element usually lands.
    if (comboRetries.length) {
      await sleep(1200);
      for (const f of comboRetries) {
        const meta2 = metaById.get(f.id) || {};
        const el2 = document.querySelector(`[data-jpaf-id="${f.id}"]`) ||
                    (meta2.name && (document.getElementById(meta2.name) ||
                                    document.getElementsByName(meta2.name)[0]));
        if (!el2) continue;
        try {
          if (await fillCombo(el2, f.value) && verifyValue(el2, f.value)) {
            mark(el2, !f.needs_review);
            filled++;
            if (review > 0) review--;
            const ri = reviewFields.findIndex((r) => r.id === f.id);
            if (ri >= 0) reviewFields.splice(ri, 1);
          }
        } catch (e) { /* stays flagged for review */ }
      }
    }

    toast(
      `JobPilot filled ${filled} field(s)` +
      (kept ? ` · kept ${kept} you'd answered` : "") +
      (resumeAttached ? " · résumé attached ✓" : "") +
      (coverAttached ? " · cover letter attached ✓" : "") +
      (fileFlags ? " · attach file manually" : "") +
      (review ? ` · ${review} need review` : "") +
      " — review & click Apply"
    );
    return { filled, needs_review: review, file_flags: fileFlags, kept,
             resume_attached: resumeAttached, cover_attached: coverAttached,
             review_fields: reviewFields.slice(0, 15),
             review_required: review > 0 || fileFlags > 0 };
  };

  // Shared with the per-ATS engines (greenhouse.js) — same isolated world,
  // loaded after this file per the manifest order.
  window.__jpafHelpers = { realClick, setNative, waitFor, fillCombo, comboOptions,
                           bestOptionIn, comboCommitted, chooseChoice, mark };
})();
