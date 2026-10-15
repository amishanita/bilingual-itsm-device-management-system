/**
 * Shared behavior for list pages: filters kept in the URL, debounced search,
 * paging, stale-answer protection, and loading and error states.
 *
 * Each page supplies the API path, the filter names, and a function that
 * draws the rows. The page's HTML provides #filters, #filter-reset,
 * #page-status, #results, #result-count, #no-results, #page-info,
 * #page-prev, and #page-next.
 */

import { ApiError, api } from "./api.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus } from "./page.js";

export const PAGE_SIZE = 50;

/** Fill a filter select with "All" plus choices; prefix makes labels translation keys. */
export function fillSelect(select, values, prefix) {
  select.replaceChildren(el("option", { value: "", "data-i18n": "common.all" }, t("common.all")));
  for (const value of values) {
    const attributes = prefix ? { value, "data-i18n": `${prefix}.${value}` } : { value };
    select.append(el("option", attributes, prefix ? t(`${prefix}.${value}`) : value));
  }
}

/**
 * @param {object} options
 * @param {string} options.path API path, for example "/employees".
 * @param {string[]} options.filters Filter names; each is a field in #filters and a query parameter.
 * @param {(page: {items: object[], total: number}) => void} options.renderRows Draws the table body.
 * @param {string} options.countKey Translation key for the total, with a {total} placeholder.
 * @param {string} [options.tableId] Table hidden when there are no rows.
 * @param {() => Record<string, string>} [options.fixedParams] Extra query parameters not shown as filters.
 * @param {(params: URLSearchParams) => void} [options.transform] Turns page-only filters into API parameters.
 */
export function createList({ path, filters, renderRows, countKey, tableId, fixedParams, transform }) {
  const form = document.getElementById("filters");
  const status = document.getElementById("page-status");
  const results = document.getElementById("results");
  let state = readUrl();
  let lastPage = null;
  let seqNo = 0;

  function readUrl() {
    const params = new URLSearchParams(window.location.search);
    const next = { page: Math.max(1, Number.parseInt(params.get("page"), 10) || 1) };
    for (const name of filters) {
      if (params.get(name)) {
        next[name] = params.get(name);
      }
    }
    return next;
  }

  function writeUrl() {
    const params = new URLSearchParams();
    for (const name of filters) {
      if (state[name]) {
        params.set(name, state[name]);
      }
    }
    if (state.page > 1) {
      params.set("page", String(state.page));
    }
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }

  /** Put the state into the form; unknown values from the URL fall back to "All". */
  function syncForm() {
    for (const name of filters) {
      const input = form.elements.namedItem(name);
      if (!input) {
        continue;
      }
      if (input.type === "checkbox") {
        input.checked = state[name] === "true";
        continue;
      }
      input.value = state[name] || "";
      if (input.value !== (state[name] || "")) {
        delete state[name];
        input.value = "";
      }
    }
  }

  function render() {
    if (!lastPage) {
      return;
    }
    renderRows(lastPage);
    const empty = lastPage.items.length === 0;
    if (tableId) {
      document.getElementById(tableId).hidden = empty;
    }
    document.getElementById("no-results").hidden = !empty;
    const from = empty ? 0 : (state.page - 1) * PAGE_SIZE + 1;
    const to = (state.page - 1) * PAGE_SIZE + lastPage.items.length;
    document.getElementById("result-count").textContent = t(countKey, { total: fmtNumber(lastPage.total) });
    document.getElementById("page-info").textContent = t("common.page_info", {
      from: fmtNumber(from),
      to: fmtNumber(to),
      total: fmtNumber(lastPage.total),
    });
    document.getElementById("page-prev").disabled = state.page <= 1;
    document.getElementById("page-next").disabled = to >= lastPage.total;
  }

  async function load() {
    const seq = ++seqNo;
    writeUrl();
    results.setAttribute("aria-busy", "true");
    if (!lastPage) {
      showStatus(status, { state: "loading" });
    }
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String((state.page - 1) * PAGE_SIZE),
      ...(fixedParams ? fixedParams() : {}),
    });
    for (const name of filters) {
      if (state[name]) {
        params.set(name, state[name]);
      }
    }
    if (transform) {
      transform(params);
    }
    try {
      const page = await api(`${path}?${params}`);
      if (seq !== seqNo) {
        return; // a newer request has started
      }
      lastPage = page;
      showStatus(status, { state: "done" });
      results.hidden = false;
      render();
    } catch (error) {
      if (seq === seqNo) {
        const code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
        showStatus(status, { state: "error", message: tError(code), onRetry: load });
      }
    } finally {
      if (seq === seqNo) {
        results.removeAttribute("aria-busy");
      }
    }
  }

  function start() {
    syncForm();
    let timer = null;
    form.addEventListener("input", (event) => {
      const { name } = event.target;
      if (!filters.includes(name)) {
        return;
      }
      const value = event.target.type === "checkbox" ? (event.target.checked ? "true" : "") : event.target.value;
      if (value) {
        state[name] = value;
      } else {
        delete state[name];
      }
      state.page = 1;
      clearTimeout(timer);
      timer = setTimeout(load, event.target.type === "search" ? 300 : 0);
    });
    form.addEventListener("submit", (event) => event.preventDefault());
    document.getElementById("filter-reset").addEventListener("click", () => {
      state = { page: 1 };
      syncForm();
      load();
    });
    document.getElementById("page-prev").addEventListener("click", () => {
      state.page -= 1;
      load();
    });
    document.getElementById("page-next").addEventListener("click", () => {
      state.page += 1;
      load();
    });
    document.addEventListener("langchange", render);
    return load();
  }

  /** Show a specific search (for example right after creating a record). */
  function showOnly(values) {
    state = { page: 1, ...values };
    syncForm();
    return load();
  }

  return { start, load, showOnly, syncForm };
}

/**
 * Wire an "add" toggle, its panel, and form to POST a new record.
 * @param {object} options
 * @param {object[]} options.fields Field specs for forms.js.
 * @param {() => object} [options.initial] Starting values.
 * @param {(values: object) => object} [options.toBody] Turns form values into the request body.
 * @param {string} options.path API path for the POST.
 * @param {(record: object) => {key: string, params: object}} options.success Message after saving.
 * @param {(record: object) => void} options.after Called after a successful save.
 * @param {Record<string, string>} [options.fieldForCode] Error code to the field it concerns.
 * @param {(fields: object[]) => Promise<object[]>|object[]} [options.prepare] Adjust fields when opened.
 */
export function setUpAddForm({ fields, initial, toBody, path, success, after, fieldForCode = {}, prepare }) {
  const toggle = document.getElementById("add-toggle");
  const panel = document.getElementById("add-panel");
  const form = document.getElementById("add-form");
  const errorBox = document.getElementById("add-error");
  const successBox = document.getElementById("add-success");
  let code = null;
  let message = null;
  let activeFields = fields;

  const renderMessages = () => {
    errorBox.hidden = !code;
    errorBox.textContent = code ? tError(code) : "";
    successBox.hidden = !message;
    successBox.textContent = message ? t(message.key, message.params) : "";
  };
  document.addEventListener("langchange", renderMessages);

  const open = async (show) => {
    panel.hidden = !show;
    toggle.setAttribute("aria-expanded", String(show));
    if (show) {
      code = null;
      renderMessages();
      try {
        activeFields = prepare ? await prepare(fields) : fields;
      } catch (error) {
        code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
        renderMessages();
        return;
      }
      buildFields(document.getElementById("add-fields"), activeFields, initial ? initial() : {}, "add");
      form.querySelector("input, select, textarea").focus();
    }
  };
  toggle.hidden = false;
  toggle.addEventListener("click", () => open(panel.hidden));
  document.getElementById("add-cancel").addEventListener("click", () => {
    open(false);
    toggle.focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    code = null;
    message = null;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const values = readFields(form, activeFields);
      const record = await api(path, { method: "POST", body: toBody ? toBody(values) : values });
      message = success(record);
      open(false);
      await after(record);
    } catch (error) {
      code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
      if (error instanceof ApiError && error.status === 422) {
        showFieldErrors(form, error.detail);
      }
      if (fieldForCode[code]) {
        showFieldErrors(form, { fields: [{ field: fieldForCode[code] }] });
      }
    } finally {
      submit.disabled = false;
      renderMessages();
    }
  });
}
