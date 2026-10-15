/**
 * Dashboard page: KPI cards, two charts, and warranties ending soon.
 *
 * All figures come from one call to GET /api/dashboard/summary, which is
 * already scoped by the server (managers see their own department only).
 * The data is kept after loading, so a language switch only re-renders
 * labels and dates without calling the API again.
 */

import { ApiError, api } from "./api.js";
import { fmtDate, parseDate, t, tError } from "./i18n.js";
import { el, fmtNumber, showStatus, startPage } from "./page.js";

const STAFF_ROLES = ["super_admin", "it_admin", "manager"];
// Warranties ending within this many days are highlighted.
const URGENT_DAYS = 14;

const status = document.getElementById("page-status");
const content = document.getElementById("dashboard");
const charts = {};
let summary = null;

/**
 * Whole days from today (local calendar) until a plain date.
 * @param {string} isoDate "YYYY-MM-DD"
 * @returns {number}
 */
function daysUntil(isoDate) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((parseDate(isoDate).getTime() - today.getTime()) / 86_400_000);
}

/**
 * Translated labels and values for a count map, keeping the server's order.
 * @param {Record<string, number>} counts
 * @param {string} prefix Translation namespace, for example "type".
 */
function series(counts, prefix) {
  const keys = Object.keys(counts);
  return { labels: keys.map((key) => t(`${prefix}.${key}`)), values: keys.map((key) => counts[key]) };
}

/**
 * Fill a two-column count table. These tables carry the same figures as the
 * charts, for screen readers and for when the chart library is unavailable.
 */
function fillCountTable(tableId, counts, prefix) {
  const body = document.querySelector(`#${tableId} tbody`);
  const { labels, values } = series(counts, prefix);
  body.replaceChildren(
    ...labels.map((label, index) => {
      const row = el("tr");
      row.append(el("td", {}, label), el("td", { class: "num" }, fmtNumber(values[index])));
      return row;
    }),
  );
}

/** Colors come from CSS variables, so the charts follow the stylesheet. */
function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Draw or update one bar chart. Returns quietly when Chart.js did not load.
 * @param {string} id Canvas id.
 * @param {Record<string, number>} counts
 * @param {string} prefix Translation namespace for the labels.
 * @param {"x"|"y"} indexAxis "y" draws horizontal bars (long category names).
 */
function drawChart(id, counts, prefix, indexAxis) {
  if (!window.Chart) {
    return;
  }
  const { labels, values } = series(counts, prefix);
  const existing = charts[id];
  if (existing) {
    existing.data.labels = labels;
    existing.data.datasets[0].data = values;
    existing.update();
    return;
  }
  const valueAxis = {
    beginAtZero: true,
    ticks: { precision: 0, color: cssColor("--color-muted") },
    grid: { color: cssColor("--color-border") },
  };
  const labelAxis = { ticks: { color: cssColor("--color-text") }, grid: { display: false } };
  charts[id] = new window.Chart(document.getElementById(id), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: cssColor("--color-chart"),
          borderRadius: 4,
          maxBarThickness: 36,
        },
      ],
    },
    options: {
      indexAxis,
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: indexAxis === "y" ? { x: valueAxis, y: labelAxis } : { x: labelAxis, y: valueAxis },
    },
  });
}

function renderWarranties() {
  document.getElementById("warranty-heading").textContent = t("dashboard.warranty_heading", {
    days: summary.warranty_window_days,
  });
  const items = summary.warranties_ending;
  document.getElementById("warranty-empty").hidden = items.length > 0;
  document.getElementById("table-warranty").hidden = items.length === 0;
  const body = document.querySelector("#table-warranty tbody");
  body.replaceChildren(
    ...items.map((item) => {
      const days = daysUntil(item.warranty_end);
      const row = el("tr", days <= URGENT_DAYS ? { class: "urgent" } : {});
      const tagCell = el("td", { class: "nowrap" });
      tagCell.append(el("a", { href: `device.html?id=${encodeURIComponent(item.asset_id)}` }, item.asset_tag));
      row.append(
        tagCell,
        el("td", {}, item.model),
        el("td", { class: "nowrap" }, fmtDate(item.warranty_end)),
        el("td", { class: "num" }, fmtNumber(days)),
      );
      return row;
    }),
  );
}

/** Draw everything from the stored summary in the current language. */
function render() {
  if (!summary) {
    return;
  }
  const values = {
    total_devices: summary.total_devices,
    kitting: summary.kitting.length,
    overdue_loans: summary.overdue_loans,
    non_compliant_devices: summary.non_compliant_devices,
    open_tickets: summary.open_tickets,
  };
  for (const node of content.querySelectorAll("[data-field]")) {
    node.textContent = fmtNumber(values[node.dataset.field]);
  }
  // Problems that need action stand out when there are any.
  document.getElementById("kpi-overdue").classList.toggle("kpi-alert", summary.overdue_loans > 0);
  document
    .getElementById("kpi-noncompliant")
    .classList.toggle("kpi-alert", summary.non_compliant_devices > 0);

  fillCountTable("table-types", summary.devices_by_type, "type");
  fillCountTable("table-categories", summary.open_tickets_by_category, "category");
  drawChart("chart-types", summary.devices_by_type, "type", "x");
  drawChart("chart-categories", summary.open_tickets_by_category, "category", "y");
  document.getElementById("chart-unavailable").hidden = Boolean(window.Chart);
  renderWarranties();
}

async function load() {
  showStatus(status, { state: "loading" });
  try {
    summary = await api("/dashboard/summary");
  } catch (error) {
    const code = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
    showStatus(status, { state: "error", message: tError(code), onRetry: load });
    return;
  }
  showStatus(status, { state: "done" });
  content.hidden = false;
  render();
}

async function main() {
  const user = await startPage("dashboard.html", STAFF_ROLES);
  if (!user) {
    return;
  }
  if (user.role === "manager") {
    // Managers have no kitting page, and their figures cover one department.
    const kitting = document.getElementById("kpi-kitting");
    kitting.removeAttribute("href");
    const note = document.getElementById("scope-note");
    const renderNote = () => {
      note.textContent = t("dashboard.scope_department", {
        department: user.employee ? user.employee.department : "",
      });
    };
    note.hidden = false;
    renderNote();
    document.addEventListener("langchange", renderNote);
  }
  document.addEventListener("langchange", render);
  await load();
}

main();
