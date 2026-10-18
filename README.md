# ITSM Device Management

A bilingual (Japanese / English) web app for tracking company PCs and phones through
their whole life: purchase, kitting, handing out, loans, returns, wipe, and disposal. It also
covers the helpdesk work around them: tickets, an FAQ, and a chatbot that can open tickets.

[日本語のREADMEはこちら](README.ja.md)

![Dashboard](docs/screenshots/02-dashboard.png)

## Live demo

Not deployed yet. The server code, Terraform, and deployment guide are ready
([docs/構築手順書.md](docs/構築手順書.md)); the link will go here once the site is live and checked.

Demo logins (the password is set by `DEMO_PASSWORD` when the demo data is loaded):

| Login | Role | What it can do |
| --- | --- | --- |
| `admin@demo` | super_admin | Everything, plus login accounts and the audit log |
| `it@demo` | it_admin | Devices, kitting, loans, employees, tickets, FAQ |
| `manager@demo` | manager | Read-only view of their own department, dashboard |
| `employee@demo` | employee | Own devices, own tickets, FAQ, chatbot |

## Why I built this

I work in IT helpdesk in Japan. A large part of the job is kitting PCs and phones with Windows
Autopilot and Intune, keeping the asset list correct, lending out spare devices and chasing
the overdue ones, and answering the same questions again and again. In practice that
information is spread over a spreadsheet, an MDM console, a ticket tool, and people's memory.

This project puts the device side of that work in one place, built around the steps I actually
follow: a kitting checklist per device type, a lifecycle that does not let a device skip the
wipe step, a leaver flow that lists everything an employee still holds, and an audit trail of
who changed what.

## Screenshots

All screenshots are from the running app with the demo data.

| | |
| --- | --- |
| ![Device list](docs/screenshots/03-devices.png) Device list with filters | ![Device in kitting](docs/screenshots/04-device-kitting.png) Device page: allowed status changes only, kitting checklist |
| ![Kitting board](docs/screenshots/05-kitting-board.png) Kitting board by person | ![Loans](docs/screenshots/06-loans.png) Loans, overdue in red |
| ![Leaver flow](docs/screenshots/07-employee-leaver.png) Employee page: devices to collect when someone leaves | ![Ticket](docs/screenshots/09-ticket.png) Ticket with comments |
| ![FAQ](docs/screenshots/10-faq.png) FAQ in the reader's language | ![English dashboard](docs/screenshots/12-dashboard-en.png) English UI, manager view |

## Features

**Devices and kitting**
- Device register (laptops, smartphones, tablets, monitors) with technical details: OS, IMEI,
  phone number, SIM, MDM enrolment, encryption, compliance.
- Lifecycle with fixed rules: `ordered → in_stock → kitting → ready → assigned / on_loan →
  returned → wiped → in_stock`, plus `repair` and `retired`. Any other change is refused.
- Kitting checklists copied from a template per device type (Windows Autopilot / Intune,
  iPhone and iPad, Android, shared device re-kit). A device cannot be marked ready until every
  step is ticked. Re-kits keep the earlier run as history.

**Loans and leavers**
- Lend a device with a due date; overdue loans are highlighted. Returning a device records its
  condition and whether it was wiped.
- Employee page lists every device the person still holds, with a way to return each one
  (assigned devices directly, loaned devices through the loan record).

**Helpdesk**
- Tickets with status, priority, assignee, comments, and a linked device. Employees see only
  their own tickets; managers see their department.
- 20 FAQ articles in both languages, searched in the reader's language. IT staff edit both
  languages side by side.
- Chatbot (OpenAI tool calling) that searches the FAQ, looks up the user's own devices and
  tickets, and drafts a ticket that the user must confirm before it is created.

**Everything else**
- Dashboard: devices by type and status, kitting progress, overdue loans, non-compliant devices,
  warranties ending in 60 days, open tickets by category.
- Japanese and English UI, switchable per user. Japanese is the default.
- Audit log of every change, and a per-device history on the device page.

**API only for now (no page yet):** CSV import and export of devices, password change, and the
audit log list (`GET /api/audit-logs`). They are covered by tests and the Postman collection.

### What this version does not do

- Autopilot and Intune fields are typed in by hand. There is no Microsoft Graph connection.
- "Wipe confirmed" records that an operator wiped the device. The app does not erase anything.
- Names, ticket text, serial numbers, and notes are not translated; only the interface is.
- The chatbot is tested in pytest with a scripted model, and I checked it by hand against the live
  OpenAI API (`gpt-6-luna` with `OPENAI_REASONING_EFFORT=none`): an FAQ answer, and a ticket drafted,
  confirmed, and created. It is switched off on the public demo to keep the running cost at zero.

## Tech stack

| Area | Choice |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| Auth | JWT (PyJWT), bcrypt, rate limits with slowapi |
| Database | PostgreSQL 16 |
| Frontend | Plain HTML, CSS, and JavaScript modules; Chart.js |
| Chatbot | OpenAI API (tool calling) |
| Tests and quality | pytest, Ruff, pip-audit, Postman / newman |
| Delivery | Docker Compose, GitHub Actions, Caddy (HTTPS) |
| Cloud | AWS Lightsail and S3, Terraform |

## Architecture

![Architecture](docs/architecture.png)

Only Caddy is reachable from the internet. The API and the database sit on separate Docker
networks, and the database network has no route out. Diagram source:
[docs/diagrams/architecture.dot](docs/diagrams/architecture.dot).

## Data model

![ER diagram](docs/er-diagram.png)

Generated from the SQLAlchemy models by
[docs/diagrams/er_diagram.py](docs/diagrams/er_diagram.py), so it matches the real schema.

## Run it locally

You need Docker Desktop and Python 3 (only to serve the frontend files).

```bash
git clone https://github.com/amishanita/itsm-platform.git
cd itsm-platform
cp .env.example .env
```

Edit `.env`: set `POSTGRES_PASSWORD` (and the same value inside `DATABASE_URL` and
`TEST_DATABASE_URL`), a random `JWT_SECRET`
(`python3 -c "import secrets; print(secrets.token_urlsafe(64))"`), and a `DEMO_PASSWORD` of at
least 8 characters. Then:

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
python3 -m http.server 8080 -d frontend
```

Open http://localhost:8080 and sign in as `it@demo` with your `DEMO_PASSWORD`. The API docs are at
http://localhost:8000/api/docs. To try the chatbot, put your own `OPENAI_API_KEY` and a model that
supports tool calling in `OPENAI_MODEL`, then `docker compose up -d` again. Newer OpenAI models also
need `OPENAI_REASONING_EFFORT=none`; without it they refuse tool calls on this endpoint.

## Tests

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://itsm:<password>@localhost:5432/itsm
export TEST_DATABASE_URL=postgresql+psycopg://itsm:<password>@localhost:5432/itsm_test
pytest -q
ruff check . && ruff format --check .
```

The test suite refuses to start unless `TEST_DATABASE_URL` ends in `_test` and differs from
`DATABASE_URL`, so it cannot wipe real data. At the time of writing it has 684 tests: every
lifecycle rule, every role and scope check, demo-mode locks, CSV limits, the chatbot flow with
a scripted model, and the FAQ search.

**CI** (GitHub Actions) runs Ruff, migrations on an empty database, the seed twice (it must give
the same counts), pytest, pip-audit, a Docker build that must run as a non-root user,
validation of the production Compose file and Caddyfile, shellcheck on the server scripts,
and `terraform fmt` / `validate`.

**API tests in Postman:** import [docs/postman/itsm.postman_collection.json](docs/postman/itsm.postman_collection.json)
and the `ITSM local` environment, set `demo_password`, and run the collection (44 requests,
76 assertions including the 403 role checks). From the command line:
`npx newman run docs/postman/itsm.postman_collection.json -e docs/postman/itsm-local.postman_environment.json --env-var demo_password=...`

**Browser checks:** while building each page I ran Playwright scripts against the real API
(navigation by role, 375 px mobile layout, language switch, error states). They are not part of
CI yet.

## Security notes

- Passwords hashed with bcrypt; 8 to 72 bytes, never truncated. Login limited to 5 tries a
  minute per IP, chat to 20 messages an hour per user.
- The JWT carries only the user id. Role and active state are read from the database on every
  request, so a deactivated user is locked out at once.
- Data scoping is done in the SQL query. A record outside your scope answers 404, not 403, so
  its existence is not revealed.
- Errors always come back as `{"detail": {"code", "message"}}` with no stack traces.
- CORS allows one origin. Pages use a Content Security Policy without `unsafe-inline`; all data
  is written with `textContent`.
- Caddy adds HSTS and the other security headers and is the only open port. SSH is open to one
  IP address only.
- Secrets live in `.env` on the server and are never committed. Terraform state and
  `terraform.tfvars` are excluded from Git, and the backup access key is created outside
  Terraform so it never lands in the state file.
- Backups: nightly encrypted upload to S3, deleted after 30 days, and a weekly job that restores
  the newest backup into a scratch database to prove it works. The backup user cannot delete.
- In demo mode the four demo logins cannot be changed, and the data resets every night.

## What I would improve next

1. Read device compliance from Intune through Microsoft Graph instead of typing it in.
2. Sign-in with Microsoft Entra ID, and move the token from sessionStorage to an HttpOnly cookie.
3. Pages for CSV import, password change, and the audit log.
4. Email reminders for overdue loans and warranties ending soon.
5. Run the Playwright browser checks in CI, and add uptime monitoring with alerts.
6. Terraform state in S3 with locking, so more than one person can work on it.
7. A command to create the first admin account, so the app can run with `APP_ENV=production`
   (today the seed refuses production, so the server is built in demo mode).

## Documents (Japanese)

- [構築手順書](docs/構築手順書.md): building the server from scratch
- [運用手順書](docs/運用手順書.md): backup, restore, restart, adding users, updates
- [障害対応手順書](docs/障害対応手順書.md): site down, disk full, certificate errors, chatbot not answering

## Author

Tamang Amish ([GitHub](https://github.com/amishanita))
