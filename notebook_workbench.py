from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import zipfile
from pathlib import PurePosixPath

from db import iso_now

MAX_NOTEBOOK_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 12 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 24 * 1024 * 1024


def _safe_path(value: str) -> str:
    value = str(value or "").replace("\\", "/").lstrip("/")
    p = PurePosixPath(value)
    if not value or any(part in {"", ".", ".."} for part in p.parts):
        raise ValueError(f"Unsafe notebook asset path: {value or '(empty)'}")
    return str(p)


def _validate_notebook(raw: bytes) -> dict:
    if len(raw) > MAX_NOTEBOOK_BYTES:
        raise ValueError("Notebook is too large. Keep the .ipynb file under 5 MB and place images/data beside it in the ZIP.")
    try:
        notebook = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise ValueError("The selected notebook is not valid UTF-8 Jupyter JSON.") from exc
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise ValueError("The selected file is not a valid Jupyter notebook.")
    return notebook


def read_workbench_upload(filename: str, payload: bytes) -> dict:
    """Parse an .ipynb or ZIP package entirely in memory.

    ZIP packages may contain one notebook plus any relative image/data files used by
    the notebook. A root-level ``custos-workbench.json`` can optionally name the
    notebook and provide display metadata without changing the notebook itself.
    """
    filename = os.path.basename(str(filename or "workbench.ipynb"))
    lower = filename.lower()
    if lower.endswith(".ipynb"):
        notebook = _validate_notebook(payload)
        meta = notebook.get("metadata", {}).get("custos", {})
        return {
            "filename": filename,
            "package_name": filename,
            "notebook": notebook,
            "metadata": meta if isinstance(meta, dict) else {},
            "assets": [],
        }
    if not lower.endswith(".zip"):
        raise ValueError("Upload a Jupyter .ipynb file or a .zip containing one notebook and its evidence files.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded ZIP could not be opened.") from exc

    names = [_safe_path(n) for n in archive.namelist() if n and not n.endswith("/")]
    descriptor = {}
    if "custos-workbench.json" in names:
        try:
            descriptor = json.loads(archive.read("custos-workbench.json").decode("utf-8-sig"))
        except Exception as exc:
            raise ValueError("custos-workbench.json is not valid JSON.") from exc
        if not isinstance(descriptor, dict):
            raise ValueError("custos-workbench.json must contain a JSON object.")

    notebook_name = str(descriptor.get("notebook") or "").strip()
    notebooks = [n for n in names if n.lower().endswith(".ipynb")]
    if notebook_name:
        notebook_name = _safe_path(notebook_name)
        if notebook_name not in names:
            raise ValueError(f"Notebook '{notebook_name}' named by custos-workbench.json was not found.")
    elif len(notebooks) == 1:
        notebook_name = notebooks[0]
    elif not notebooks:
        raise ValueError("The ZIP does not contain a Jupyter .ipynb notebook.")
    else:
        raise ValueError("The ZIP contains multiple notebooks. Add custos-workbench.json with a 'notebook' filename.")

    notebook_raw = archive.read(notebook_name)
    notebook = _validate_notebook(notebook_raw)
    nb_meta = notebook.get("metadata", {}).get("custos", {})
    metadata = {}
    if isinstance(nb_meta, dict):
        metadata.update(nb_meta)
    for key in ("title", "subtitle", "packages", "previews", "setup_cells"):
        if key in descriptor:
            metadata[key] = descriptor[key]

    base_dir = str(PurePosixPath(notebook_name).parent)
    if base_dir == ".":
        base_dir = ""
    assets = []
    total = 0
    for name in names:
        if name == notebook_name or name == "custos-workbench.json" or name.lower().endswith(".ipynb"):
            continue
        data = archive.read(name)
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError(f"Asset '{name}' is larger than 12 MB.")
        total += len(data)
        if total > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("Workbench package assets exceed the 24 MB limit.")
        rel = name
        if base_dir and name.startswith(base_dir + "/"):
            rel = name[len(base_dir) + 1:]
        rel = _safe_path(rel)
        mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        assets.append({"path": rel, "mime_type": mime, "data": data})

    return {
        "filename": os.path.basename(notebook_name),
        "package_name": filename,
        "notebook": notebook,
        "metadata": metadata,
        "assets": assets,
    }


def store_workbench(conn, assessment_id: int, package: dict) -> None:
    conn.execute("DELETE FROM assessment_notebook_assets WHERE assessment_id=?", (assessment_id,))
    conn.execute("DELETE FROM assessment_notebooks WHERE assessment_id=?", (assessment_id,))
    conn.execute(
        """INSERT INTO assessment_notebooks(assessment_id,filename,notebook_json,package_name,metadata_json,updated_at)
           VALUES(?,?,?,?,?,?)""",
        (
            assessment_id,
            package["filename"],
            json.dumps(package["notebook"], ensure_ascii=False),
            package.get("package_name") or package["filename"],
            json.dumps(package.get("metadata") or {}, ensure_ascii=False),
            iso_now(),
        ),
    )
    for asset in package.get("assets") or []:
        conn.execute(
            """INSERT INTO assessment_notebook_assets(assessment_id,asset_path,mime_type,content_b64)
               VALUES(?,?,?,?)""",
            (
                assessment_id,
                _safe_path(asset["path"]),
                asset.get("mime_type") or "application/octet-stream",
                base64.b64encode(asset["data"]).decode("ascii"),
            ),
        )


def load_workbench_record(conn, assessment_id: int):
    notebook = conn.execute("SELECT * FROM assessment_notebooks WHERE assessment_id=?", (assessment_id,)).fetchone()
    if not notebook:
        return None
    assets = conn.execute(
        "SELECT asset_path,mime_type,content_b64 FROM assessment_notebook_assets WHERE assessment_id=? ORDER BY asset_path",
        (assessment_id,),
    ).fetchall()
    return notebook, assets


def remove_workbench(conn, assessment_id: int) -> None:
    conn.execute("DELETE FROM assessment_notebook_assets WHERE assessment_id=?", (assessment_id,))
    conn.execute("DELETE FROM assessment_notebooks WHERE assessment_id=?", (assessment_id,))
