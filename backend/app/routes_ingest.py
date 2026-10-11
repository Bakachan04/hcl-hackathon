"""POST /ingest (APIRouter). Owner: Lavanya.

Multipart form: a CSV `file` plus a JSON `meta` naming the table, e.g.

    curl -F "file=@data/raw/orders.csv" -F 'meta={"table":"orders"}' http://localhost:8000/ingest

A plain `table` form field is accepted too. Good rows replace the stored table.
"""

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import loader
from app.schemas import LoadResult

router = APIRouter(tags=["data"])


def _table_name(meta: str | None, table: str | None) -> str:
    if meta:
        try:
            parsed = json.loads(meta)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"meta is not valid JSON: {exc.msg}") from None
        if not isinstance(parsed, dict) or "table" not in parsed:
            raise HTTPException(400, 'meta must be a JSON object like {"table": "orders"}')
        table = parsed["table"]
    if not table:
        raise HTTPException(400, 'name the table: meta={"table": "..."} or a table form field')
    if table not in loader.TABLES:
        raise HTTPException(400, f"unknown table {table!r}; expected one of {', '.join(loader.TABLES)}")
    return table


@router.post("/ingest", response_model=LoadResult)
async def ingest(file: Annotated[UploadFile, File()],
                 meta: Annotated[str | None, Form()] = None,
                 table: Annotated[str | None, Form()] = None) -> LoadResult:
    name = _table_name(meta, table)
    return loader.load_table(name, await file.read())
