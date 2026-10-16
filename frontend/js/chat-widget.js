/**
 * Helpdesk chat widget: a button at the bottom right of every signed-in page.
 *
 * Messages go to POST /api/chat. When the assistant prepares a ticket, the
 * reply carries a pending ticket and the widget shows a confirmation card;
 * only the Confirm button creates the ticket (POST /api/chat/confirm). Typing
 * "yes" does not, because confirmation is enforced by the server.
 *
 * Everything the assistant says is shown as text. The only links created are
 * FAQ and ticket pages of this app (faq.html?id=N, ticket.html?id=N), built
 * from a strict pattern, so a reply can never inject markup or send the user
 * to another site.
 */

import { ApiError, api } from "./api.js";
import { applyTranslations, fmtDate, t, tError } from "./i18n.js";
import { el } from "./page.js";

const SESSION_KEY = "itsm.chatSession";
const SAFE_LINK = /\b((?:faq|ticket)\.html\?id=\d{1,9})\b/g;

let sessionId = null;
let messages = []; // {role, content} or {role: "notice", key, params, link}
let pending = null;
let busy = false;
let root = null;

function readSession() {
  try {
    const value = Number.parseInt(sessionStorage.getItem(SESSION_KEY), 10);
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function saveSession(id) {
  sessionId = id;
  try {
    sessionStorage.setItem(SESSION_KEY, String(id));
  } catch {
    // The conversation still works; it just will not survive a page change.
  }
}

/** Assistant text with this app's FAQ and ticket links made clickable. */
function richText(text) {
  const container = el("p", { class: "chat-text" });
  let last = 0;
  for (const match of text.matchAll(SAFE_LINK)) {
    container.append(document.createTextNode(text.slice(last, match.index)));
    container.append(el("a", { href: match[1] }, match[1].startsWith("faq") ? t("chat.open_faq") : t("chat.open_ticket")));
    last = match.index + match[0].length;
  }
  container.append(document.createTextNode(text.slice(last)));
  return container;
}

function renderMessages() {
  const list = root.querySelector(".chat-messages");
  list.replaceChildren();
  if (messages.length === 0) {
    list.append(el("li", { class: "chat-message assistant" }, t("chat.welcome")));
  }
  for (const message of messages) {
    if (message.role === "notice") {
      const item = el("li", { class: "chat-message notice", role: "status" });
      item.append(el("span", {}, message.code ? tError(message.code) : t(message.key)));
      if (message.link) {
        item.append(document.createTextNode(" "), el("a", { href: "tickets.html" }, t("chat.use_form")));
      }
      list.append(item);
      continue;
    }
    const item = el("li", { class: `chat-message ${message.role}` });
    if (message.role === "assistant") {
      item.append(richText(message.content));
    } else {
      item.append(el("p", { class: "chat-text" }, message.content));
    }
    list.append(item);
  }
  if (busy) {
    list.append(el("li", { class: "chat-message assistant typing", role: "status" }, t("chat.thinking")));
  }
  list.scrollTop = list.scrollHeight;
}

function renderPending() {
  const card = root.querySelector(".chat-confirm");
  card.hidden = !pending;
  if (!pending) {
    return;
  }
  const rows = [
    ["ticket.title", pending.title],
    ["ticket.category", t(`category.${pending.category}`)],
    ["ticket.priority", t(`priority.${pending.priority}`)],
    ["ticket.device", pending.asset_tag || "-"],
    ["ticket.description", pending.description],
  ];
  const details = card.querySelector(".chat-confirm-details");
  details.replaceChildren(...rows.flatMap(([key, value]) => [el("dt", {}, t(key)), el("dd", {}, value)]));
  card.querySelector(".chat-confirm-expiry").textContent = t("chat.confirm_until", {
    time: fmtDate(pending.expires_at, { time: true }),
  });
}

function render() {
  renderMessages();
  renderPending();
  const send = root.querySelector(".chat-send");
  send.disabled = busy;
  for (const button of root.querySelectorAll(".chat-confirm button")) {
    button.disabled = busy;
  }
}

function notice(error) {
  const code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
  // Without the chatbot (no API key, provider down) the ticket form is the way forward.
  const link = ["CHAT_UNAVAILABLE", "CHAT_PROVIDER_ERROR", "RATE_LIMITED"].includes(code);
  messages.push({ role: "notice", code, link });
}

async function sendMessage(text) {
  messages.push({ role: "user", content: text });
  busy = true;
  render();
  try {
    const body = { message: text };
    if (sessionId) {
      body.session_id = sessionId;
    }
    const reply = await api("/chat", { method: "POST", body });
    saveSession(reply.session_id);
    messages.push({ role: "assistant", content: reply.reply });
    pending = reply.pending;
  } catch (error) {
    if (error instanceof ApiError && error.code === "CHAT_SESSION_NOT_FOUND") {
      sessionId = null; // the old conversation is gone; the next message starts a new one
    }
    notice(error);
  } finally {
    busy = false;
    render();
  }
}

async function decide(decision) {
  busy = true;
  render();
  try {
    const reply = await api("/chat/confirm", { method: "POST", body: { session_id: sessionId, decision } });
    messages.push({ role: "assistant", content: reply.reply });
    pending = null;
  } catch (error) {
    notice(error);
    if (error instanceof ApiError && ["CHAT_CONFIRMATION_EXPIRED", "CHAT_NOTHING_TO_CONFIRM", "ASSET_NOT_OWNED"].includes(error.code)) {
      pending = null;
    }
  } finally {
    busy = false;
    render();
  }
}

async function restore() {
  const saved = readSession();
  if (!saved) {
    return;
  }
  try {
    const conversation = await api(`/chat/sessions/${saved}`);
    sessionId = conversation.session_id;
    messages = conversation.messages.map((m) => ({ role: m.role, content: m.content }));
    pending = conversation.pending;
  } catch {
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // nothing stored
    }
  }
}

function build() {
  root = el("div", { class: "chat-widget" });
  const toggle = el("button", {
    type: "button",
    class: "chat-toggle",
    "aria-expanded": "false",
    "aria-controls": "chat-panel",
    "data-i18n": "chat.open",
  });
  const panel = el("section", { id: "chat-panel", class: "chat-panel", role: "dialog", "aria-labelledby": "chat-title", hidden: "" });
  const header = el("div", { class: "chat-header" });
  header.append(
    el("h2", { id: "chat-title", "data-i18n": "chat.title" }),
    el("button", { type: "button", class: "chat-close", "data-i18n": "common.close" }),
  );
  const list = el("ol", { class: "chat-messages", "aria-live": "polite" });
  const card = el("div", { class: "chat-confirm", hidden: "" });
  card.append(
    el("p", { class: "chat-confirm-title", "data-i18n": "chat.confirm_title" }),
    el("dl", { class: "chat-confirm-details" }),
    el("p", { class: "chat-confirm-expiry muted" }),
  );
  const actions = el("div", { class: "form-actions" });
  const confirm = el("button", { type: "button", class: "button button-primary", "data-decision": "confirm", "data-i18n": "chat.confirm" });
  const cancel = el("button", { type: "button", class: "button button-quiet", "data-decision": "cancel", "data-i18n": "chat.cancel" });
  actions.append(confirm, cancel);
  card.append(actions);
  const form = el("form", { class: "chat-form", novalidate: "" });
  const label = el("label", { for: "chat-input", class: "visually-hidden", "data-i18n": "chat.input_label" });
  const input = el("textarea", { id: "chat-input", rows: "2", maxlength: "2000", "data-i18n-placeholder": "chat.placeholder" });
  const send = el("button", { type: "submit", class: "button button-primary chat-send", "data-i18n": "chat.send" });
  form.append(label, input, send);
  panel.append(header, list, card, form, el("p", { class: "chat-privacy muted", "data-i18n": "chat.privacy" }));
  root.append(panel, toggle);
  document.body.append(root);

  const setOpen = async (open) => {
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.hidden = open;
    if (open) {
      render();
      input.focus();
    } else {
      toggle.focus();
    }
  };
  toggle.addEventListener("click", () => setOpen(true));
  header.querySelector(".chat-close").addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setOpen(false);
    }
  });
  input.addEventListener("keydown", (event) => {
    // Enter sends; Shift+Enter adds a line. Ignore Enter while composing Japanese text.
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) {
      return;
    }
    input.value = "";
    sendMessage(text);
  });
  confirm.addEventListener("click", () => decide("confirm"));
  cancel.addEventListener("click", () => decide("cancel"));
  document.addEventListener("langchange", () => {
    applyTranslations(root);
    render();
  });
  applyTranslations(root);
}

/** Add the widget to the page (called once by startPage for signed-in pages). */
export async function mountChatWidget() {
  if (root) {
    return;
  }
  build();
  await restore();
  render();
}
