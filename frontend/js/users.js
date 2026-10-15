/**
 * Login accounts (super_admin only): create logins, change role, activate or
 * deactivate, link to an employee record, and reset passwords.
 *
 * The server protects the last active super_admin and refuses changes to the
 * signed-in admin's own role or active state; those refusals are shown here
 * as translated messages. Passwords are never shown or returned by the API.
 */

import { ApiError, api } from "./api.js";
import { buildFields, clearFieldErrors, readFields, showFieldErrors } from "./forms.js";
import { t, tError } from "./i18n.js";
import { createList, fillSelect, setUpAddForm } from "./list-page.js";
import { ROLES } from "./people-fields.js";
import { el, startPage } from "./page.js";

const roleOptions = ROLES.map((value) => ({ value, label: `role.${value}` }));
const languageOptions = ["ja", "en"].map((value) => ({ value, label: `lang.${value}` }));
const PASSWORD_HINT = "users.password_hint";
let me = null;
let list = null;
let editing = null;

async function employeeOptions() {
  const employees = await api("/employees?limit=200");
  return employees.items.map((e) => ({ value: String(e.id), text: `${e.name} (${e.employee_code}, ${e.department})` }));
}

function renderRows(page) {
  document.querySelector("#user-table tbody").replaceChildren(
    ...page.items.map((account) => {
      const row = el("tr", account.is_active ? {} : { class: "inactive" });
      const role = el("td");
      role.append(el("span", { class: `badge badge-role-${account.role}` }, t(`role.${account.role}`)));
      const state = el("td");
      state.append(
        el("span", { class: `badge ${account.is_active ? "badge-ready" : "badge-retired"}` },
          t(account.is_active ? "users.active" : "users.inactive")),
      );
      const action = el("td", { class: "num" });
      const edit = el("button", { type: "button", class: "button button-quiet button-small", "data-edit": String(account.id) },
        t("common.edit"));
      edit.addEventListener("click", () => openEdit(account));
      action.append(edit);
      const email = el("td", { class: "nowrap" }, account.email);
      if (account.id === me.id) {
        email.append(el("span", { class: "badge you-badge" }, t("users.you")));
      }
      row.append(
        email,
        role,
        el("td", {}, account.employee ? `${account.employee.name} (${account.employee.department})` : "-"),
        el("td", {}, t(`lang.${account.language}`)),
        state,
        action,
      );
      return row;
    }),
  );
}

// Edit one account

let editFields = [];
let editError = null;

function renderEdit() {
  const box = document.getElementById("edit-error");
  box.hidden = !editError;
  box.textContent = editError ? tError(editError) : "";
  if (editing) {
    document.getElementById("edit-heading").textContent = t("users.edit_heading", { email: editing.email });
  }
}

async function openEdit(account) {
  editing = account;
  editError = null;
  const panel = document.getElementById("edit-panel");
  panel.hidden = false;
  renderEdit();
  try {
    editFields = [
      { name: "role", label: "field.role", type: "select", required: true, options: roleOptions },
      { name: "is_active", label: "users.is_active", type: "checkbox" },
      { name: "employee_id", label: "field.employee", type: "select", options: await employeeOptions(), nullable: true },
      { name: "language", label: "field.language", type: "select", required: true, options: languageOptions },
      { name: "password", label: "users.new_password", type: "password", maxLength: 72, hint: "users.reset_hint" },
    ];
  } catch (error) {
    editError = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
    renderEdit();
    return;
  }
  buildFields(
    document.getElementById("edit-fields"),
    editFields,
    { ...account, employee_id: account.employee ? String(account.employee.id) : "" },
    "edit",
  );
  const password = document.getElementById("edit-password");
  password.autocomplete = "new-password";
  panel.scrollIntoView({ block: "nearest" });
  document.getElementById("edit-role").focus();
}

function closeEdit() {
  document.getElementById("edit-panel").hidden = true;
  editing = null;
}

async function submitEdit(event) {
  event.preventDefault();
  const form = event.target;
  clearFieldErrors(form);
  editError = null;
  const body = readFields(form, editFields, { onlyChanged: true });
  if (body.password === null) {
    delete body.password; // an empty password box means "keep the current password"
  }
  if ("employee_id" in body && body.employee_id !== null) {
    body.employee_id = Number(body.employee_id);
  }
  if (Object.keys(body).length === 0) {
    closeEdit();
    return;
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const saved = await api(`/users/${editing.id}`, { method: "PUT", body });
    closeEdit();
    const box = document.getElementById("add-success");
    box.hidden = false;
    box.textContent = t("users.saved", { email: saved.email });
    await list.load();
  } catch (error) {
    editError = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
    if (error instanceof ApiError && error.status === 422) {
      showFieldErrors(form, error.detail);
    }
    const field = {
      CANNOT_CHANGE_OWN_ROLE: "role",
      CANNOT_DEACTIVATE_SELF: "is_active",
      LAST_SUPER_ADMIN: "role",
      EMPLOYEE_ALREADY_LINKED: "employee_id",
    }[editError];
    if (field) {
      showFieldErrors(form, { fields: [{ field }] });
    }
  } finally {
    submit.disabled = false;
    renderEdit();
  }
}

async function main() {
  me = await startPage("users.html", ["super_admin"]);
  if (!me) {
    return;
  }
  fillSelect(document.getElementById("filter-role"), ROLES, "role");
  list = createList({
    path: "/users",
    filters: ["q", "role"],
    renderRows,
    countKey: "users.count",
    tableId: "user-table",
  });
  setUpAddForm({
    fields: [],
    prepare: async () => [
      { name: "email", label: "field.email", type: "email", required: true, maxLength: 254 },
      { name: "password", label: "users.initial_password", type: "password", required: true, maxLength: 72, hint: PASSWORD_HINT },
      { name: "role", label: "field.role", type: "select", required: true, options: roleOptions },
      { name: "employee_id", label: "field.employee", type: "select", options: await employeeOptions() },
      { name: "language", label: "field.language", type: "select", required: true, options: languageOptions },
    ],
    initial: () => ({ role: "employee", language: "ja" }),
    toBody: (values) => ({ ...values, employee_id: values.employee_id ? Number(values.employee_id) : null }),
    path: "/users",
    success: (account) => ({ key: "users.created", params: { email: account.email } }),
    after: (account) => list.showOnly({ q: account.email }),
    fieldForCode: { EMAIL_ALREADY_EXISTS: "email", EMPLOYEE_ALREADY_LINKED: "employee_id" },
  });
  document.getElementById("add-toggle").addEventListener("click", closeEdit);
  document.getElementById("edit-form").addEventListener("submit", submitEdit);
  document.getElementById("edit-cancel").addEventListener("click", closeEdit);
  document.addEventListener("langchange", renderEdit);
  await list.start();
}

main();
