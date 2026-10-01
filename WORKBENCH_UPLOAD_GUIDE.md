# Custos Jupyter Workbench Upload Guide

Custos can attach a Jupyter notebook to **any custom assessment**. The notebook is stored with the assessment in SQLite or PostgreSQL, so the same workflow works locally, on Render, and on Vercel.

## Fastest workflow

1. Open **Instructor View → Workspace**.
2. Create or open a custom assessment under the subject you want, for example **CSEC303**.
3. Open the assessment builder and find **Jupyter Workbench**.
4. Upload either:
   - one `.ipynb` notebook; or
   - one `.zip` containing the notebook plus relative images/data files.
5. Add questions normally or import a CSV. The optional `workbench_section` column determines which notebook section opens with each question.
6. Use **Testing** before activating the assessment.

## How notebook sections are detected

Use Markdown headings in the notebook. H1 is treated as the notebook title/guide. H2 headings become workbench sections.

Example:

```markdown
# Laboratory Exercise

## CASE 00 · Evidence Intake
...

## CASE 01 · Contrast Recovery
...
```

For `CASE 00`, `CASE 01`, and similar headings, Custos generates stable section keys such as `CASE00` and `CASE01`.

For ordinary headings, Custos creates a normalized key. For example:

```text
## Histogram Investigation
→ HISTOGRAM_INVESTIGATION
```

In a question CSV, use:

```csv
item_number,topic,...,workbench_section
1,CASE 01 · Contrast Recovery,...,CASE01
```

If `workbench_section` is blank, Custos also tries to match the question topic to the notebook section title automatically.

## Notebook ZIP format

A minimal ZIP can look like:

```text
my-lab.zip
├── my_lab.ipynb
├── reference.png
├── degraded.png
└── custos-workbench.json   (optional)
```

Relative notebook references such as `reference.png` remain available to browser Python after the package is uploaded.

An optional `custos-workbench.json` can customize the workbench:

```json
{
  "notebook": "my_lab.ipynb",
  "title": "My Image Investigation",
  "subtitle": "Scientific Python Workbench",
  "setup_cells": [2],
  "previews": {
    "CASE00": "reference.png",
    "CASE01": "degraded.png"
  }
}
```

`setup_cells` uses the notebook's zero-based cell indexes. Those cells run automatically when the Python runtime starts.

## Python support

The browser workbench uses Pyodide. Custos scans notebook imports and loads compatible Pyodide packages when Python starts. Common CSEC303 packages such as NumPy, pandas, SciPy, Matplotlib, Pillow, and scikit-image are supported. Python cells have syntax highlighting, line numbers, persistent font sizing, and lightweight completion suggestions. `Ctrl+Space` or `Cmd+Space` opens suggestions manually.

The original notebook remains downloadable as a backup. Workbench code edits are saved per student attempt, but the Python process itself is recreated after a page reload, so students rerun setup/working cells when returning later.


## GitHub/static workbench option

For notebooks you want to deploy with the application source itself, create:

```text
static/workbenches/<assessment-slug>/
├── custos-workbench.json
├── notebook.ipynb
├── optional-case-kit.zip
└── supporting files...
```

The folder name must exactly match the assessment `slug`. Custos automatically discovers this manifest when the assessment has no database-uploaded notebook. A database upload takes priority, so you can replace a GitHub-shipped notebook later from Instructor View without changing code.

This is how PHANTOM-303 is packaged in the repository:

```text
static/workbenches/csec303-midterm-laboratory-case-files/
```

The manifest can include a `package` filename in addition to `notebook`, `title`, `subtitle`, `setup_cells`, and `previews`.

## Deployment notes

- Notebook data is stored in the Custos database, so uploads made in the deployed Instructor View persist with that deployment's PostgreSQL database.
- `.ipynb` upload limit: 5 MB.
- Individual supporting asset limit: 12 MB.
- Total supporting assets in one workbench ZIP: 24 MB.
- Custos request limit is configured to allow these workbench packages.
- Do not put answer keys into public notebook cells if the repository or notebook is student-accessible.

## PHANTOM-303 on GitHub

The student notebook/case kit for PHANTOM-303 is safe to keep in the repository under `static/workbenches/csec303-midterm-laboratory-case-files/`. The real question bank and answer key remain under `private_banks/csec303_midterm/`, which `.gitignore` excludes.

For production, set your PostgreSQL `DATABASE_URL` locally and run:

```bash
python seed_csec303_midterm.py
```

This writes the private question bank to the production database without committing the answer key to GitHub.

## Included dry run

The repository includes a public test package at:

```text
samples/csec303_workbench_dry_run/
```

For a complete local test assessment, run:

```bash
python seed_csec303_workbench_test.py
```

The created assessment intentionally reveals its score and answer review after submission so you can test the entire student flow.
