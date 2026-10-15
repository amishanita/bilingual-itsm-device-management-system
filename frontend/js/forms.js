/**
 * Small form builder shared by the add and edit forms.
 *
 * A form is described by a list of field specs, so labels, input types,
 * length limits, and the way values are sent to the API stay in one place.
 * Labels are translation keys; values typed by people are never translated.
 *
 * Field spec:
 *   { name, label, type: "text"|"textarea"|"number"|"date"|"datetime"|"select"|"checkbox",
 *     required?, maxLength?, min?, max?, step?, pattern?, options?: [{value, label|text}],
 *     nullable? (empty input is sent as null), hint? }
 */

import { t } from "./i18n.js";
import { el } from "./page.js";

/** "2026-10-15T09:30:00+00:00" -> "2026-10-15T18:30" in the browser's time zone. */
function toLocalInput(iso) {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/**
 * Build the inputs for a list of fields inside a container.
 * @param {HTMLElement} container
 * @param {object[]} fields
 * @param {object} [values] Current values (for edit forms).
 * @param {string} [idPrefix] Keeps ids unique when a page has several forms.
 */
export function buildFields(container, fields, values = {}, idPrefix = "f") {
  container.replaceChildren();
  for (const field of fields) {
    const id = `${idPrefix}-${field.name}`;
    const wrapper = el("div", { class: `field field-${field.type}` });
    const label = el("label", { for: id, "data-i18n": field.label }, t(field.label));
    let input;
    if (field.type === "textarea") {
      input = el("textarea", { id, name: field.name, rows: "3" });
    } else if (field.type === "select") {
      input = el("select", { id, name: field.name });
      if (!field.required) {
        input.append(el("option", { value: "", "data-i18n": "common.none" }, t("common.none")));
      } else if (values[field.name] === undefined || values[field.name] === null) {
        // A required choice starts empty, so nothing is picked by accident.
        input.append(el("option", { value: "", "data-i18n": "form.choose" }, t("form.choose")));
      }
      for (const option of field.options) {
        const attributes = option.label ? { value: option.value, "data-i18n": option.label } : { value: option.value };
        // option.label is a translation key; option.text is data shown as stored.
        input.append(el("option", attributes, option.label ? t(option.label) : (option.text ?? option.value)));
      }
    } else if (field.type === "checkbox") {
      input = el("input", { id, name: field.name, type: "checkbox" });
    } else {
      const type = { datetime: "datetime-local" }[field.type] || field.type;
      input = el("input", { id, name: field.name, type });
    }
    if (field.required) {
      input.required = true;
      label.classList.add("required");
    }
    for (const attr of ["maxLength", "min", "max", "step", "pattern"]) {
      if (field[attr] !== undefined) {
        input[attr] = field[attr];
      }
    }
    const value = values[field.name];
    if (field.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (field.type === "datetime") {
      input.value = toLocalInput(value);
    } else if (value !== null && value !== undefined) {
      input.value = String(value);
    }
    input.dataset.initial = field.type === "checkbox" ? String(input.checked) : input.value;

    if (field.type === "checkbox") {
      wrapper.append(input, label);
    } else {
      wrapper.append(label, input);
    }
    if (field.hint) {
      wrapper.append(el("p", { class: "hint", "data-i18n": field.hint }, t(field.hint)));
    }
    wrapper.append(el("p", { class: "field-error", id: `${id}-error`, hidden: "" }));
    // Once the person changes a marked field, its old error no longer applies.
    input.addEventListener("input", () => {
      if (input.getAttribute("aria-invalid") === "true") {
        input.removeAttribute("aria-invalid");
        input.removeAttribute("aria-describedby");
        const box = document.getElementById(`${id}-error`);
        box.hidden = true;
        box.textContent = "";
      }
    });
    container.append(wrapper);
  }
}

/**
 * Read the form into a request body.
 * @param {HTMLFormElement} form
 * @param {object[]} fields
 * @param {{onlyChanged?: boolean}} [options] onlyChanged=true sends just the edited fields (PUT).
 * @returns {object}
 */
export function readFields(form, fields, { onlyChanged = false } = {}) {
  const body = {};
  for (const field of fields) {
    const input = form.elements.namedItem(field.name);
    const current = field.type === "checkbox" ? String(input.checked) : input.value;
    if (onlyChanged && current === input.dataset.initial) {
      continue;
    }
    if (field.type === "checkbox") {
      body[field.name] = input.checked;
      continue;
    }
    const raw = input.value.trim();
    if (raw === "") {
      // Required fields are left to the server to reject, so the message is consistent.
      if (field.nullable || onlyChanged) {
        body[field.name] = null;
      }
      continue;
    }
    if (field.type === "number") {
      body[field.name] = field.step === "0.01" ? raw : Number(raw);
    } else if (field.type === "datetime") {
      body[field.name] = new Date(raw).toISOString();
    } else {
      body[field.name] = raw;
    }
  }
  return body;
}

/** Remove the error marks left by a previous submit. */
export function clearFieldErrors(form) {
  for (const box of form.querySelectorAll(".field-error")) {
    box.hidden = true;
    box.textContent = "";
  }
  for (const input of form.querySelectorAll("[aria-invalid]")) {
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
  }
}

/**
 * Mark the fields named in a 422 response ({"fields": [{"field": "body.asset_tag"}]}).
 * @returns {number} How many fields were marked.
 */
export function showFieldErrors(form, detail) {
  let marked = 0;
  for (const item of detail.fields || []) {
    const name = String(item.field || "").split(".").pop();
    const input = form.elements.namedItem(name);
    if (!input || !input.id) {
      continue;
    }
    const box = document.getElementById(`${input.id}-error`);
    input.setAttribute("aria-invalid", "true");
    if (box) {
      box.textContent = t("form.invalid_value");
      box.hidden = false;
      input.setAttribute("aria-describedby", box.id);
    }
    marked += 1;
  }
  return marked;
}
