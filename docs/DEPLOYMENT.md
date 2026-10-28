# Weekly-report V2 — GitHub Actions deployment

Workflow: `.github/workflows/weekly-report.yml` (job `offline-regression`, then
`production`). Secrets are read only by the production CLI step.

## Repository secrets

GitHub → repository → Settings → Secrets and variables → Actions → *Secrets* →
New repository secret. Enter each value directly in GitHub; never commit it.

| Name | Value |
| --- | --- |
| `MAIAGENT_API_BASE` | MaiAgent API origin, `https://…` with no path |
| `MAIAGENT_API_KEY` | MaiAgent API key |
| `MAIAGENT_CHATBOT_ID` | Writer chatbot ID |
| `MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID` | Structured Helper chatbot ID (must differ from the Writer) |
| `GMAIL_USER` | Sending Gmail address |
| `GMAIL_APP_PASS` | Gmail app password for that address (not the account password) |
| `DEFAULT_RECIPIENTS` | Recipients, comma-separated plain addresses, no trailing comma |

## Repository variables (explicit opt-ins)

Same page → *Variables* → New repository variable.

| Name | Value | Effect |
| --- | --- | --- |
| `WEEKLY_REPORT_SCHEDULE` | `enabled` | Runs every Monday 01:00 UTC (09:00 Taipei) for the preceding Monday–Sunday |
| `LIVE_EMAIL_SEND` | `1` | Scheduled runs email the report (PDF attached); any other value stages only |

The schedule fires only from the workflow on `main`. A manual run
(Actions → *Weekly-report V2 production* → Run workflow) can target any branch
and emails only when `send_email` is ticked.

## Behaviour

* Exit 0: complete success. Exit 2 (`SUCCESS_WITH_TECHNICAL_GAPS`): report
  produced and delivered with disclosed gaps; the job passes with a warning
  and the run summary on the job page. Exit 1: configuration, application,
  PDF or delivery failure; the job fails.
* The Markdown, PDF and run summary are kept as the run artifact for 90 days.
* Duplicate sends: a hashed delivery record is kept in the Actions cache
  (`.delivery/ledger.json`); a later run for the same period and recipients
  records `DUPLICATE` instead of emailing. Runs never overlap.
* Cost per weekly run (no journal in the cloud): about 720 MaiAgent calls and
  1,600 HTTP requests (Google News and publisher pages), roughly 1–2 hours.

## Launch order

1. Set the seven secrets.
2. Manual run on the chosen branch: `run_production` ticked, `send_email`
   unticked, period empty (preceding week). Check the artifact PDF.
3. Merge to `main`, set `WEEKLY_REPORT_SCHEDULE=enabled`; set
   `LIVE_EMAIL_SEND=1` when the emailed report is approved.
