# Custos UI Refinement + Score Export Validation

Date: 2026-09-28

## Changes in this build

- Student names, email metadata, and previews in the Messages conversation list are explicitly left aligned.
- The Assessment Catalog action footer now continues the white editing surface.
- Assessment save/delete actions remain equal-sized and side by side.
- Actual delete actions now use a red background with white text across Assessments, Messages, Testing history, and Custom Assessment question deletion.
- Wrapped/two-line button labels are center aligned.
- Added **Export Scores (.xlsx)** to every assessment's More Actions menu in All Assessments and to the Custom Assessment tools menu.
- Added `/admin/assessment/<assessment_id>/export-scores`.
  - Objective assessments export one worksheet per delivery set/batch.
  - Custom/dry-run assessments export their real student sessions and scores.
  - Midterm/Post-test exports include part scores, bonus, automatic total, instructor-adjusted final total, flags, and violations.
  - Programming Lab exports include one column per active task plus total score.
  - Instructor testing/preview sessions are excluded.
- Added `openpyxl>=3.1,<4` to deployment requirements for Excel workbook generation.

## Validation performed

- `python -m py_compile app.py workspace.py db.py item_analysis.py code_runner.py` — passed.
- Parsed all 36 Jinja templates with Jinja2 — passed.
- `node --check` on `admin_messages.js`, `admin_monitor.js`, and `mobile_ui.js` — passed.
- `openpyxl 3.1.5` is available in the build environment.

## Environment limitation

The artifact build container does not include Flask itself, so a full live Flask request/response smoke test was not run here. Render will install Flask and openpyxl from `requirements.txt` during deployment.
