"""Pinned public PDF ingestion; publisher bytes/text never enter release evidence."""

from __future__ import annotations

import io
import time
from pathlib import Path
from urllib.request import build_opener

from .contracts import fingerprint, require, sha256
from .delivery_azure import NoRedirect, ensure, project_shape
from .delivery_contracts import PDF_URL

SEARCH_API = "2026-10-01"
MCP_API = "2026-11-01-preview"


def acquire_source(directory: Path, expected: str | None = None) -> tuple[str, list[dict]]:
    from pypdf import PdfReader

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "microsoft-copilot-studio-faq.pdf"
    if path.exists():
        data = path.read_bytes()
    else:
        with build_opener(NoRedirect()).open(PDF_URL, timeout=30) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        require(data.startswith(b"%PDF-") and len(data) <= 20 * 1024 * 1024, "Invalid or oversized PDF")
        if expected is not None:
            require(sha256(data) == expected, "Publisher PDF changed; explicit source revision required")
        with path.open("xb") as stream:
            stream.write(data)
    digest = sha256(data)
    require(expected is None or digest == expected, "Cached PDF differs from release")
    reader = PdfReader(io.BytesIO(data))
    require(not reader.is_encrypted and 0 < len(reader.pages) <= 200, "Unsupported PDF")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        content = page.extract_text()
        require(bool(content.strip()), "PDF extraction is empty; OCR/manual review required")
        pages.append({"page_id": f"p{number:04d}", "page_number": number, "content": content,
                      "source_url": PDF_URL, "title": "Microsoft Copilot Studio FAQ"})
    return digest, pages


def desired_knowledge(source_hash: str) -> dict:
    suffix = source_hash[:20]
    index, source, kb = f"pdf-{suffix}", f"source-{suffix}", f"kb-{suffix}"
    index_definition = {
        "name": index, "fields": [
            {"name": "page_id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "page_number", "type": "Edm.Int32", "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "source_url", "type": "Edm.String"},
        ],
        "semantic": {"defaultConfiguration": "default", "configurations": [{
            "name": "default", "prioritizedFields": {
                "titleField": {"fieldName": "title"},
                "prioritizedContentFields": [{"fieldName": "content"}],
            },
        }]},
    }
    source_definition = {
        "name": source, "kind": "searchIndex",
        "searchIndexParameters": {
            "searchIndexName": index, "semanticConfigurationName": "default",
            "searchFields": [{"name": "content"}],
            "sourceDataFields": [{"name": key} for key in ("page_id", "page_number", "source_url", "content")],
        },
    }
    kb_definition = {"name": kb, "knowledgeSources": [{"name": source}],
                     "retrievalReasoningEffort": {"kind": "minimal"}, "outputMode": "extractiveData"}
    return {"index": index_definition, "source": source_definition, "kb": kb_definition}


def content_readback(search, index_name: str, pages: list[dict], *, wait_for_indexing: bool = False) -> str:
    deadline = time.monotonic() + 30
    while True:
        result = search.request("POST", f"/indexes/{index_name}/docs/search?api-version={SEARCH_API}", {
            "search": "*", "select": "page_id,page_number,content,source_url,title", "top": 1000, "count": True,
        })
        if not wait_for_indexing or result["@odata.count"] >= len(pages):
            break
        require(time.monotonic() < deadline, "Indexed page count not ready within bounded wait")
        time.sleep(1)
    require(result["@odata.count"] == len(pages), "Indexed page count differs")
    observed = sorted([{key: row[key] for key in pages[0]} for row in result["value"]],
                      key=lambda row: row["page_id"])
    require(observed == pages, "Indexed content differs from pinned PDF; no mutation fallback")
    return fingerprint(observed)


def materialize(foundry, source_hash: str, pages: list[dict]) -> dict:
    desired = desired_knowledge(source_hash)
    index = desired["index"]
    path = f"/indexes/{index['name']}?api-version={SEARCH_API}"
    existed = foundry.search.request("GET", path, absent_ok=True)
    ensure(foundry.search, path, index)
    if existed is None:
        result = foundry.search.request("POST", f"/indexes/{index['name']}/docs/index?api-version={SEARCH_API}", {
            "value": [{"@search.action": "upload", **page} for page in pages],
        })
        require(len(result["value"]) == len(pages) and all(row["status"] for row in result["value"]),
                "PDF ingestion partially failed; do not publish")
    watermark = content_readback(foundry.search, index["name"], pages, wait_for_indexing=existed is None)
    for key, collection in (("source", "knowledgesources"), ("kb", "knowledgebases")):
        ensure(foundry.search, f"/{collection}/{desired[key]['name']}?api-version={SEARCH_API}", desired[key])
    return {"source_hash": source_hash, "content_watermark": watermark,
            "configuration_digest": fingerprint(desired), "page_ids": [page["page_id"] for page in pages],
            "index": index["name"], "kb": desired["kb"]["name"], "source": desired["source"]["name"]}


def verify_knowledge(foundry, evidence: dict, pages: list[dict] | None = None):
    desired = desired_knowledge(evidence["source_hash"])
    for key, collection in (("index", "indexes"), ("source", "knowledgesources"), ("kb", "knowledgebases")):
        observed = foundry.search.request(
            "GET", f"/{collection}/{desired[key]['name']}?api-version={SEARCH_API}")
        require(project_shape(observed, desired[key]) == desired[key], "Knowledge configuration drift")
    if pages is not None:
        watermark = content_readback(foundry.search, evidence["index"], pages)
    else:
        # Rollback verifies retained indexed bytes, not today's bytes at a mutable publisher URL.
        keys = ("page_id", "page_number", "content", "source_url", "title")
        result = foundry.search.request("POST", f"/indexes/{evidence['index']}/docs/search?api-version={SEARCH_API}", {
            "search": "*", "select": ",".join(keys), "top": 1000, "count": True,
        })
        observed = sorted([{key: row[key] for key in keys} for row in result["value"]],
                          key=lambda row: row["page_id"])
        require(result["@odata.count"] == len(evidence["page_ids"])
                and [row["page_id"] for row in observed] == evidence["page_ids"],
                "Retained indexed page set differs")
        watermark = fingerprint(observed)
    require(watermark == evidence["content_watermark"], "Knowledge watermark drift")
