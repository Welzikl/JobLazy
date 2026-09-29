/* Injected on demand. Defines window.__jpafScan() and returns the field list
 * (the file's completion value is what chrome.scripting.executeScript returns). */
(() => {
  const txt = (s) => (s || "").replace(/\s+/g, " ").trim();

  function labelFor(el) {
    if (el.getAttribute("aria-label")) return txt(el.getAttribute("aria-label"));
    const lblBy = el.getAttribute("aria-labelledby");
    if (lblBy) {
      // aria-labelledby is an IDREF *list*. Workday, Oracle and many
      // Simplify-style forms split the prompt, required marker and helper text
      // across multiple nodes. Reading only the whole string as one id loses
      // the label completely.
      const label = lblBy.split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((n) => txt(n.innerText || n.textContent))
        .filter(Boolean)
        .join(" ");
      if (label) return label;
    }
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && txt(l.innerText)) return txt(l.innerText);
    }
    const wrap = el.closest("label");
    if (wrap && txt(wrap.innerText)) return txt(wrap.innerText);
    // preceding label-ish sibling
    let p = el.previousElementSibling;
    let hops = 0;
    while (p && hops < 3) {
      if (/^(label|span|div|p|legend)$/i.test(p.tagName) && txt(p.innerText)) return txt(p.innerText);
      p = p.previousElementSibling; hops++;
    }
    const par = el.parentElement;
    if (par) {
      const lab = par.querySelector("label, legend");
      if (lab && txt(lab.innerText)) return txt(lab.innerText);
    }
    // Legacy table layouts (iCIMS, older Taleo) carry the label in the CELL TO
    // THE LEFT with no <label> element at all: <td>Legal Name</td><td><input>.
    // Without this the field falls back to its name ("fields[name]") and no
    // rule matches, so the whole left column of an iCIMS form stays empty.
    const cell = el.closest("td, th");
    if (cell) {
      const prev = cell.previousElementSibling;
      // guard against a layout table whose left cell holds another input
      if (prev && !prev.querySelector("input, select, textarea") && txt(prev.innerText))
        return txt(prev.innerText).slice(0, 80);
    }
    if (el.placeholder) return txt(el.placeholder);
    return el.name || el.id || "";
  }

  // Nearest section heading/legend above the field — lets the mapper
  // disambiguate e.g. an "End Date" inside Education vs Work Experience.
  function sectionFor(el) {
    const fs = el.closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg && txt(lg.innerText)) return txt(lg.innerText).slice(0, 80);
    }
    let node = el, hops = 0;
    while (node && node !== document.body && hops < 12) {
      let sib = node.previousElementSibling;
      while (sib) {
        if (/^h[1-4]$/i.test(sib.tagName) && txt(sib.innerText)) return txt(sib.innerText).slice(0, 80);
        if (sib.querySelectorAll) {
          const hs = sib.querySelectorAll("h1, h2, h3, h4");
          if (hs.length) {
            const last = hs[hs.length - 1];
            if (txt(last.innerText)) return txt(last.innerText).slice(0, 80);
          }
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement; hops++;
    }
    return "";
  }

  window.__jpafScan = function () {
    // Clear ids from any earlier scan: each scan owns the id-space of the fill
    // that follows it. A stale id on a now-skipped element (e.g. a section an
    // engine has since claimed) would otherwise collide with a fresh id and
    // route the fill into the wrong element.
    document.querySelectorAll("[data-jpaf-id]").forEach((el) => el.removeAttribute("data-jpaf-id"));
    const nodes = document.querySelectorAll("input, select, textarea");
    // password: never part of a fill-plan — content/account.js handles sign-up walls
    const SKIP = new Set(["hidden", "submit", "button", "image", "reset", "password"]);
    const out = [];
    const seen = new Set();  // elements already emitted by THIS scan
    let i = 0;
    nodes.forEach((el) => {
      const type = (el.type || el.tagName).toLowerCase();
      if (SKIP.has(type) || el.disabled) return;
      // non-searchable react-selects render a readOnly input — still fillable
      // (open + click); every other readOnly control is off-limits
      if (el.readOnly && el.getAttribute("role") !== "combobox") return;
      // react-select's shadow "required" input and other a11y decoys
      if (el.getAttribute("aria-hidden") === "true") return;
      if (el.tabIndex === -1 && type !== "file" && el.getAttribute("role") !== "combobox") return;
      // fields the Workday wizard engine already handled (or owns the section of)
      if (el.getAttribute("data-jpaf-done") || el.closest("[data-jpaf-owned]")) return;
      const visible = type === "file" || el.getClientRects().length > 0;
      if (!visible) return;
      // group radios/checkboxes: only emit the first of a name-group
      if ((type === "radio" || type === "checkbox") && el.name) {
        if (out.some((f) => f.name === el.name && (f.type === "radio" || f.type === "checkbox"))) return;
      }
      const id = "f" + i++;
      el.setAttribute("data-jpaf-id", id);
      seen.add(el);
      let options = null;
      if (el.tagName.toLowerCase() === "select") {
        options = [...el.options].map((o) => o.label || o.text || o.value).filter(Boolean);
      }
      // radio/checkbox groups: the QUESTION lives on the group (fieldset legend /
      // labelled group), not on the first option's own label ("Male", "Asexual"…)
      let label = labelFor(el);
      if (type === "radio" || type === "checkbox") {
        const fs = el.closest("fieldset");
        const lg = fs && fs.querySelector("legend");
        if (lg && txt(lg.innerText)) label = txt(lg.innerText);
        else {
          const grp = el.closest("[role='group'][aria-labelledby], [role='radiogroup'][aria-labelledby]");
          if (grp) {
            const n = document.getElementById(grp.getAttribute("aria-labelledby"));
            if (n && txt(n.innerText)) label = txt(n.innerText);
          } else {
            const sec = sectionFor(el);
            if (sec) label = sec;
          }
        }
      }
      // React-Select / autocomplete inputs need a type-then-pick fill
      const combo = el.getAttribute("role") === "combobox" ||
                    el.getAttribute("aria-autocomplete") === "list" ||
                    el.getAttribute("aria-haspopup") === "listbox";
      out.push({ id, label, name: el.name || el.id || "", type,
                 options,
                 required: !!el.required || el.getAttribute("aria-required") === "true",
                 section: sectionFor(el),
                 autocomplete: el.getAttribute("autocomplete") || "",
                 inputmode: el.getAttribute("inputmode") || "",
                 automation_id: el.getAttribute("data-automation-id") || "",
                 ...(combo ? { combo: true } : {}) });
    });

    // ARIA dropdowns that are NOT native selects — Workday and other React UIs
    // render these as <button aria-haspopup="listbox"> or role=combobox divs.
    const ariaNodes = document.querySelectorAll(
      "button[aria-haspopup='listbox'], div[aria-haspopup='listbox'], " +
      "[role='combobox']:not(input):not(select):not(textarea)"
    );
    ariaNodes.forEach((el) => {
      if (el.getClientRects().length === 0 || el.getAttribute("aria-disabled") === "true") return;
      if (el.getAttribute("data-jpaf-done") || el.closest("[data-jpaf-owned]")) return;
      // dedupe within THIS scan only — a stale data-jpaf-id from an earlier
      // scan must not exclude the element (scan.js auto-runs once at inject)
      if (seen.has(el)) return;
      const id = "f" + i++;
      el.setAttribute("data-jpaf-id", id);
      seen.add(el);
      out.push({ id, label: labelFor(el),
                 name: el.getAttribute("name") || el.getAttribute("data-automation-id") || el.id || "",
                 type: "aria_select", options: null, section: sectionFor(el),
                 autocomplete: el.getAttribute("autocomplete") || "",
                 automation_id: el.getAttribute("data-automation-id") || "",
                 required: el.getAttribute("aria-required") === "true" });
    });
    return out;
  };

  return window.__jpafScan();
})();
