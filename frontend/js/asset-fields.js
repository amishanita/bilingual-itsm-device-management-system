/**
 * Device vocabulary shared by the device list and the device page: types,
 * statuses, OS choices, and the field specs for the add and edit forms.
 * Limits match the API schemas, so most mistakes are caught before sending.
 */

import { t } from "./i18n.js";
import { el } from "./page.js";

export const ASSET_TYPES = ["laptop", "desktop", "smartphone", "tablet", "monitor", "printer"];
export const ASSET_STATUSES = [
  "ordered",
  "in_stock",
  "kitting",
  "ready",
  "assigned",
  "on_loan",
  "returned",
  "wiped",
  "repair",
  "retired",
];
export const COMPLIANCE = ["compliant", "non_compliant", "unknown"];
// OS names are product names, shown as stored in both languages.
export const OS_CHOICES = ["Windows 11 Pro", "macOS", "iOS", "iPadOS", "Android"];
export const ADMIN_ROLES = ["super_admin", "it_admin"];

const options = (values, prefix) => values.map((value) => ({ value, label: `${prefix}.${value}` }));

/** Fields of the add-device form (POST /api/assets). */
export const CREATE_FIELDS = [
  { name: "asset_tag", label: "field.asset_tag", type: "text", required: true, maxLength: 30 },
  { name: "type", label: "field.type", type: "select", required: true, options: options(ASSET_TYPES, "type") },
  {
    name: "status",
    label: "field.initial_status",
    type: "select",
    required: true,
    options: options(["ordered", "in_stock"], "status"),
  },
  { name: "serial_number", label: "field.serial_number", type: "text", required: true, maxLength: 100 },
  { name: "manufacturer", label: "field.manufacturer", type: "text", required: true, maxLength: 100 },
  { name: "model", label: "field.model", type: "text", required: true, maxLength: 100 },
  { name: "purchase_date", label: "field.purchase_date", type: "date" },
  { name: "warranty_end", label: "field.warranty_end", type: "date" },
  { name: "cost", label: "field.cost", type: "number", min: "0", step: "0.01" },
  { name: "location", label: "field.location", type: "text", maxLength: 100 },
  { name: "notes", label: "field.notes", type: "textarea", maxLength: 2000 },
];

/** Fields of the asset edit form (PUT /api/assets/{id}); status changes elsewhere. */
export const EDIT_FIELDS = CREATE_FIELDS.filter((field) => field.name !== "status");

/** Fields of the technical details form (PUT /api/assets/{id}/details). */
export const DETAIL_FIELDS = [
  { name: "os", label: "field.os", type: "text", maxLength: 50, nullable: true },
  { name: "os_version", label: "field.os_version", type: "text", maxLength: 50, nullable: true },
  { name: "cpu", label: "field.cpu", type: "text", maxLength: 100, nullable: true },
  { name: "ram_gb", label: "field.ram_gb", type: "number", min: "0", max: "4096", step: "1", nullable: true },
  { name: "storage_gb", label: "field.storage_gb", type: "number", min: "0", step: "1", nullable: true },
  {
    name: "mac_address",
    label: "field.mac_address",
    type: "text",
    pattern: "([0-9A-Fa-f]{2}[:\\-]){5}[0-9A-Fa-f]{2}",
    hint: "hint.mac_address",
    nullable: true,
  },
  { name: "imei", label: "field.imei", type: "text", pattern: "\\d{14,16}", nullable: true },
  { name: "phone_number", label: "field.phone_number", type: "text", pattern: "[0-9+\\-() ]{6,20}", nullable: true },
  { name: "carrier", label: "field.carrier", type: "text", maxLength: 50, nullable: true },
  { name: "sim_iccid", label: "field.sim_iccid", type: "text", pattern: "\\d{18,22}", nullable: true },
  { name: "compliance", label: "field.compliance", type: "select", required: true, options: options(COMPLIANCE, "compliance") },
  { name: "autopilot_registered", label: "field.autopilot_registered", type: "checkbox" },
  { name: "mdm_enrolled", label: "field.mdm_enrolled", type: "checkbox" },
  { name: "encryption_on", label: "field.encryption_on", type: "checkbox" },
  { name: "last_check_in", label: "field.last_check_in", type: "datetime", nullable: true },
];

/**
 * A colored status label. The color is a hint only; the text always says the status.
 * @param {string} status
 * @returns {HTMLElement}
 */
export function statusBadge(status) {
  return el("span", { class: `badge badge-${status}` }, t(`status.${status}`));
}

/** @param {string} compliance */
export function complianceBadge(compliance) {
  return el("span", { class: `badge badge-${compliance}` }, t(`compliance.${compliance}`));
}

/** Holder as "Name (Department)", or a dash when nobody holds the device. */
export function holderText(holder) {
  return holder ? `${holder.name} (${holder.department})` : "-";
}
