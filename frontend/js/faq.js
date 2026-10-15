/**
 * FAQ page: articles grouped by category, with search.
 *
 * The server returns each article in the reader's language (Accept-Language),
 * so a language switch reloads the articles instead of translating them here.
 * Searching shows the best matches first, without grouping. IT staff can add
 * and edit articles; the form shows Japanese and English side by side so both
 * versions are written together.
 *
 * faq.html?id=7 opens article 7 (used by links from the chatbot).
 */

import { ApiError, api } from "./api.js";
import { ADMIN_ROLES } from "./asset-fields.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { t, tError } from "./i18n.js";
import { fillSelect } from "./list-page.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";
import { CATEGORIES } from "./ticket-fields.js";

const status = document.getElementById("page-status");
const params = new URLSearchParams(window.location.search);
let user = null;
let articles = [];
let lastQuery = "";
let requestSeq = 0;
let openId = Number.parseInt(params.get("id"), 10) || null;
let message = null;

const isAdmin = () => ADMIN_ROLES.includes(user.role);
const errorCode = (error) => (error instanceof ApiError ? error.code : "UNKNOWN_ERROR");

const CATEGORY_FIELD = [
  {
    name: "category",
    label: "ticket.category",
    type: "select",
    required: true,
    options: CATEGORIES.map((value) => ({ value, label: `category.${value}` })),
  },
];
const LANGUAGE_FIELDS = {
  ja: [
    { name: "title_ja", label: "faq.field.title", type: "text", required: true, maxLength: 200 },
    { name: "body_ja", label: "faq.field.body", type: "textarea", required: true, maxLength: 10000, hint: "faq.body_hint" },
  ],
  en: [
    { name: "title_en", label: "faq.field.title", type: "text", required: true, maxLength: 200 },
    { name: "body_en", label: "faq.field.body", type: "textarea", required: true, maxLength: 10000, hint: "faq.body_hint" },
  ],
};
const ALL_FIELDS = [...CATEGORY_FIELD, ...LANGUAGE_FIELDS.ja, ...LANGUAGE_FIELDS.en];

function renderMessage() {
  const box = document.getElementById("faq-message");
  box.hidden = !message;
  box.textContent = message ? t(message.key, message.params) : "";
}

function articleElement(article) {
  const details = el("details", { class: "faq-item", id: `faq-${article.id}` });
  if (article.id === openId) {
    details.open = true;
  }
  const summary = el("summary", {}, article.title);
  const body = el("div", { class: "faq-body" });
  // Article text is shown exactly as written, never as HTML.
  body.append(el("p", { class: "ticket-text" }, article.body));
  const footer = el("p", { class: "faq-footer muted" });
  footer.append(
    document.createTextNode(`${t("faq.still_stuck")} `),
    el("a", { href: "tickets.html" }, t("faq.create_ticket")),
  );
  body.append(footer);
  if (isAdmin()) {
    const edit = el("button", { type: "button", class: "button button-quiet button-small", "data-edit": String(article.id) },
      t("common.edit"));
    edit.addEventListener("click", () => openEditor(article.id));
    body.append(edit);
  }
  details.append(summary, body);
  return details;
}

function render() {
  const list = document.getElementById("faq-list");
  list.replaceChildren();
  document.getElementById("no-results").hidden = articles.length > 0;
  document.getElementById("result-count").textContent = lastQuery
    ? t("faq.search_count", { count: fmtNumber(articles.length) })
    : t("faq.count", { count: fmtNumber(articles.length) });
  if (lastQuery) {
    // Search results keep the server's ranking: best match first.
    const section = el("section", { class: "panel faq-group" });
    section.append(...articles.map(articleElement));
    if (articles.length) {
      list.append(section);
    }
  } else {
    for (const category of CATEGORIES) {
      const inCategory = articles.filter((a) => a.category === category);
      if (!inCategory.length) {
        continue;
      }
      const section = el("section", { class: "panel faq-group", "aria-labelledby": `cat-${category}` });
      section.append(el("h2", { id: `cat-${category}` }, t(`category.${category}`)), ...inCategory.map(articleElement));
      list.append(section);
    }
  }
  if (openId) {
    document.getElementById(`faq-${openId}`)?.scrollIntoView({ block: "start" });
    openId = null;
  }
}

async function load() {
  const seq = ++requestSeq;
  const form = document.getElementById("filters");
  lastQuery = form.elements.namedItem("q").value.trim();
  const query = new URLSearchParams({ limit: "200" });
  if (lastQuery) {
    query.set("q", lastQuery);
  }
  const category = form.elements.namedItem("category").value;
  if (category) {
    query.set("category", category);
  }
  document.getElementById("results").setAttribute("aria-busy", "true");
  try {
    const page = await api(`/faq?${query}`);
    if (seq !== requestSeq) {
      return;
    }
    articles = page.items;
    showStatus(status, { state: "done" });
    document.getElementById("results").hidden = false;
    render();
  } catch (error) {
    if (seq === requestSeq) {
      showStatus(status, { state: "error", message: tError(errorCode(error)), onRetry: load });
    }
  } finally {
    if (seq === requestSeq) {
      document.getElementById("results").removeAttribute("aria-busy");
    }
  }
}

// Editor (IT staff)

let editingId = null;
let editError = null;

function renderEditor() {
  const box = document.getElementById("edit-error");
  box.hidden = !editError;
  box.textContent = editError ? tError(editError) : "";
  document.getElementById("edit-heading").textContent = t(editingId ? "faq.edit_heading" : "faq.add_heading");
}

async function openEditor(articleId) {
  editingId = articleId;
  editError = null;
  let values = {};
  if (articleId) {
    try {
      values = await api(`/faq/${articleId}/full`);
    } catch (error) {
      editError = errorCode(error);
    }
  }
  buildFields(document.getElementById("category-field"), CATEGORY_FIELD, values, "edit");
  buildFields(document.getElementById("ja-fields"), LANGUAGE_FIELDS.ja, values, "edit");
  buildFields(document.getElementById("en-fields"), LANGUAGE_FIELDS.en, values, "edit");
  const panel = document.getElementById("edit-panel");
  panel.hidden = false;
  document.getElementById("add-toggle").setAttribute("aria-expanded", "true");
  renderEditor();
  panel.scrollIntoView({ block: "start" });
  document.getElementById("edit-category").focus();
}

function closeEditor() {
  document.getElementById("edit-panel").hidden = true;
  document.getElementById("add-toggle").setAttribute("aria-expanded", "false");
  editingId = null;
}

async function submitEditor(event) {
  event.preventDefault();
  const form = event.target;
  clearFieldErrors(form);
  editError = null;
  const body = readFields(form, ALL_FIELDS, { onlyChanged: Boolean(editingId) });
  if (editingId && Object.keys(body).length === 0) {
    closeEditor();
    return;
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const saved = editingId
      ? await api(`/faq/${editingId}`, { method: "PUT", body })
      : await api("/faq", { method: "POST", body });
    message = { key: editingId ? "faq.saved" : "faq.created", params: {} };
    openId = saved.id;
    closeEditor();
    renderMessage();
    await load();
  } catch (error) {
    editError = errorCode(error);
    if (error instanceof ApiError && error.status === 422) {
      showFieldErrors(form, error.detail);
    }
  } finally {
    submit.disabled = false;
    renderEditor();
  }
}

async function main() {
  user = await startPage("faq.html");
  if (!user) {
    return;
  }
  fillSelect(document.getElementById("faq-category"), CATEGORIES, "category");
  const form = document.getElementById("filters");
  let timer = null;
  form.addEventListener("input", (event) => {
    clearTimeout(timer);
    timer = setTimeout(load, event.target.type === "search" ? 300 : 0);
  });
  form.addEventListener("submit", (event) => event.preventDefault());
  if (isAdmin()) {
    const toggle = document.getElementById("add-toggle");
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      if (document.getElementById("edit-panel").hidden || editingId) {
        openEditor(null);
      } else {
        closeEditor();
      }
    });
    document.getElementById("edit-form").addEventListener("submit", submitEditor);
    document.getElementById("edit-cancel").addEventListener("click", closeEditor);
  }
  // Articles come from the server in the reader's language, so reload on a switch.
  document.addEventListener("langchange", () => {
    renderMessage();
    if (!document.getElementById("edit-panel").hidden) {
      renderEditor();
    }
    load();
  });
  showStatus(status, { state: "loading" });
  await load();
}

main();
