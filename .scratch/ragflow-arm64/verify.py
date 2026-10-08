#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Verify real text/scanned-PDF ingestion and Nova retrieval; remove fixtures."""
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ragflow_connection import read_key, BASE_URL
from src.ragflow.client import RagFlowClient, RagFlowConnection

HERE = Path(__file__).resolve().parent


def scanned_pdf():
    program = r'''
from io import BytesIO
import sys, pdfplumber
from reportlab.pdfgen import canvas
source = BytesIO()
c = canvas.Canvas(source)
c.setFont("Helvetica", 20)
c.drawString(60, 740, "Nova ARM64 native document test")
c.drawString(60, 690, "Maintenance code: ORIN-PDF-4815")
c.drawString(60, 640, "Calibration temperature: 43 degrees Celsius")
c.save()
source.seek(0)
with pdfplumber.open(source) as doc:
    image = doc.pages[0].to_image(resolution=150).original
scan = BytesIO()
image.convert("RGB").save(scan, format="PDF", resolution=150)
sys.stdout.buffer.write(scan.getvalue())
'''
    result = subprocess.run(
        ["docker", "exec", "-i", "nova-ragflow-ragflow-cpu-1", "python", "-"],
        input=program.encode(), capture_output=True, check=True,
    )
    assert result.stdout.startswith(b"%PDF")
    return result.stdout


async def main():
    key = read_key()
    client = RagFlowClient(RagFlowConnection(BASE_URL, key))
    report = {"before_dataset_count": len(await client.list_datasets())}
    dataset_id = None
    async with aiohttp.ClientSession(
        headers={"Authorization": "Bearer " + key},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as session:
        async def api(method, path, **kwargs):
            async with session.request(method, BASE_URL + "/api/v1" + path, **kwargs) as response:
                payload = await response.json()
                if response.status >= 400 or payload.get("code") != 0:
                    raise RuntimeError(f"{method} {path}: {payload.get('message', response.status)}")
                return payload.get("data")
        try:
            dataset = await api("POST", "/datasets", json={
                "name": "Nova ARM64 verification " + uuid.uuid4().hex[:8],
                "embedding_model": "bge-m3@nova-arm64@Ollama", "chunk_method": "naive",
                "parser_config": {"layout_recognize": "DeepDOC", "chunk_token_num": 256},
            })
            dataset_id = dataset["id"]
            print("Created temporary verification dataset", flush=True)
            fixtures = {
                "native-text.txt": "玄武站冷卻水溫度為 76 攝氏度，檢修代碼為 ORIN-RAG-7329。".encode(),
                "native-scan.pdf": scanned_pdf(),
            }
            document_ids = []
            for name, content in fixtures.items():
                form = aiohttp.FormData()
                form.add_field("file", content, filename=name, content_type="application/octet-stream")
                uploaded = await api("POST", f"/datasets/{dataset_id}/documents", data=form)
                document_ids.extend(document["id"] for document in uploaded)
            print("Uploaded text and image-only PDF", flush=True)
            start = time.monotonic()
            await api("POST", f"/datasets/{dataset_id}/documents/parse", json={"document_ids": document_ids})
            deadline = start + 600
            last_state = None
            while time.monotonic() < deadline:
                payload = await api("GET", f"/datasets/{dataset_id}/documents")
                documents = payload["docs"]
                state = [(d["name"], d.get("run"), d.get("progress"), d.get("chunk_count")) for d in documents]
                if state != last_state:
                    print("Parsing:", json.dumps(state), flush=True)
                    last_state = state
                failed = [d for d in documents if float(d.get("progress") or 0) < 0 or str(d.get("run")) in {"4", "FAIL", "FAILED"}]
                if failed:
                    raise RuntimeError("Parser failed: " + str([(d["name"],d.get("progress_msg")) for d in failed]))
                if len(documents) == 2 and all(str(d.get("run")) in {"3", "DONE"} for d in documents):
                    break
                await asyncio.sleep(3)
            else:
                raise RuntimeError("Document parsing timed out")
            report["parsing_seconds"] = round(time.monotonic() - start, 3)
            report["documents"] = [{k:d.get(k) for k in ("name", "run", "progress", "chunk_count")} for d in documents]
            assert dataset_id in {d["id"] for d in await client.list_datasets()}
            queries = [
                ("玄武站的冷卻水溫度與檢修代碼是什麼？", "ORIN-RAG-7329", "native-text.txt"),
                ("What is the maintenance code and calibration temperature?", "ORIN-PDF-4815", "native-scan.pdf"),
            ]
            report["nova_retrieval"] = []
            for question, expected, document_name in queries:
                start = time.monotonic()
                result = await client.retrieve(question, [dataset_id])
                elapsed = round(time.monotonic() - start, 3)
                assert result["status"] == "matched", result
                assert any(expected in s["content"] and s["document_name"] == document_name for s in result["sources"]), result
                item = {"document": document_name, "status": result["status"], "elapsed_seconds": elapsed, "source_count": len(result["sources"])}
                report["nova_retrieval"].append(item)
                print("Nova retrieval:", json.dumps(item), flush=True)
            async with session.get(BASE_URL + "/api/v1/system/healthz") as response:
                report["health"] = await response.json()
                assert response.status == 200
            report["success"] = True
        finally:
            if dataset_id:
                await api("DELETE", "/datasets", json={"ids": [dataset_id]})
                report["temporary_dataset_removed"] = True
            report["after_dataset_count"] = len(await client.list_datasets())
            (HERE / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("ARM64 ingestion, scanned PDF OCR and Nova retrieval passed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
