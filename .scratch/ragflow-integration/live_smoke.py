# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One-off live retrieval smoke test; never print credentials."""

from __future__ import annotations

import base64
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote
from unittest.mock import patch

import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ragflow.client import RagFlowClient, RagFlowConnection, RagFlowError
from src.server.routes.ragflow import list_ragflow_datasets, test_ragflow_retrieval


BASE_URL = "http://127.0.0.1:9380"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArq9XTUSeYr2+N1h3Afl/z8Dse/2yD0ZGrKwx+EEEcdsBLca9Ynmx3nIB5obmLlSfmskLpBo0UACBmB5rEjBp2Q2f3AG3Hjd4B+gNCG6BDaawuDlgANIhGnaTLrIqWrrcm4EMzJOnAOI1fgzJRsOOUEfaS318Eq9OVO3apEyCCt0lOQK6PuksduOjVxtltDav+guVAA068NrPYmRNabVKRNLJpL8w4D44sfth5RvZ3q9t+6RTArpEtc5sh5ChzvqPOzKGMXW83C95TxmXqpbK6olN4RevSfVjEAgCydH6HN6OhtOQEcnrU97r9H0iZOWwbw3pVrZiUkuRD1R56Wzs2wIDAQAB
-----END PUBLIC KEY-----"""


def login() -> str:
    env_text = (ROOT / ".local/ragflow/upstream/docker/.env").read_text()
    password = next(
        line.partition("=")[2].strip().strip('"')
        for line in env_text.splitlines()
        if line.startswith("ADMIN_DEFAULT_PASSWORD=")
    )
    cipher = PKCS1_v1_5.new(RSA.import_key(PUBLIC_KEY))
    encrypted = base64.b64encode(
        cipher.encrypt(base64.b64encode(password.encode()))
    ).decode()
    response = requests.post(
        BASE_URL + "/api/v1/auth/login",
        json={"email": "admin@ragflow.io", "password": encrypted},
        timeout=10,
    )
    payload = response.json()
    if response.status_code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"RAGFlow login failed: HTTP {response.status_code}, code {payload.get('code')}, message {payload.get('message')}")
    token = response.headers.get("Authorization", "")
    if not token:
        raise RuntimeError("RAGFlow login did not return Authorization")
    return token


def main() -> None:
    auth = login()
    print("login=ok")
    session = requests.Session()
    session.headers["Authorization"] = auth
    token = None
    dataset_id = None

    def checked(response: requests.Response, label: str):
        payload = response.json()
        print(f"{label}=HTTP {response.status_code}, code {payload.get('code')}")
        if response.status_code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"{label}: {payload.get('message')}")
        return payload.get("data")

    try:
        token_data = checked(
            session.post(BASE_URL + "/api/v1/system/tokens", timeout=10),
            "temporary_api_key",
        )
        token = token_data["token"]
        session.headers["Authorization"] = f"Bearer {token}"
        dataset_data = checked(
            session.post(
                BASE_URL + "/api/v1/datasets",
                json={
                    "name": "nova_ragflow_live_smoke_20260916",
                    "description": "Temporary Nova Avatar retrieval verification; safe to delete.",
                    "language": "Chinese",
                    "embedding_model": "bge-m3:latest@Ollama",
                    "chunk_method": "naive",
                    "permission": "me",
                },
                timeout=20,
            ),
            "create_dataset",
        )
        dataset_id = dataset_data["id"]
        print("dataset_embedding=", dataset_data.get("embedding_model") or dataset_data.get("embd_id"))
        marker = "NVA-RAG-49317"
        content = (
            "Nova Avatar 知識庫檢索實測文件。\n"
            f"紫色海豚的識別碼是 {marker}。\n"
            "這段資料只用於驗證 BGE-M3 文件解析與 Nova Avatar 的知識庫檢索。\n"
        ).encode()
        upload_data = checked(
            session.post(
                BASE_URL + f"/api/v1/datasets/{dataset_id}/documents",
                files={"file": ("nova-ragflow-smoke.txt", io.BytesIO(content), "text/plain")},
                timeout=20,
            ),
            "upload_document",
        )
        document_id = upload_data[0]["id"]
        checked(
            session.post(
                BASE_URL + f"/api/v1/datasets/{dataset_id}/documents/parse",
                json={"document_ids": [document_id]},
                timeout=20,
            ),
            "start_parse",
        )
        deadline = time.monotonic() + 180
        last_status = None
        while time.monotonic() < deadline:
            documents = checked(
                session.get(
                    BASE_URL + f"/api/v1/datasets/{dataset_id}/documents",
                    params={"id": document_id},
                    timeout=10,
                ),
                "list_documents",
            )
            item = documents["docs"][0]
            status = str(item.get("run"))
            if status != last_status:
                print("parse_status=", status)
                last_status = status
            if status in {"DONE", "3"}:
                print("chunk_count=", item.get("chunk_count"))
                break
            if status in {"FAIL", "4", "CANCEL", "2"}:
                raise RuntimeError(f"Document parsing stopped: {status}")
            time.sleep(2)
        else:
            raise TimeoutError("Document parsing did not finish in 180 seconds")

        question = "紫色海豚的識別碼是什麼？"
        started = time.monotonic()
        raw_result = checked(
            session.post(
                BASE_URL + "/api/v1/retrieval",
                json={
                    "question": question,
                    "dataset_ids": [dataset_id],
                    "page": 1,
                    "page_size": 4,
                    "similarity_threshold": 0.2,
                    "highlight": False,
                },
                timeout=60,
            ),
            "direct_retrieval",
        )
        print("direct_retrieval_seconds=", round(time.monotonic() - started, 3))
        print("direct_source_count=", len(raw_result.get("chunks", [])))

        client = RagFlowClient(RagFlowConnection(BASE_URL, token))
        datasets = asyncio.run(client.list_datasets())
        print("nova_dataset_visible=", any(item["id"] == dataset_id for item in datasets))
        result = None
        for attempt in range(1, 6):
            started = time.monotonic()
            try:
                result = asyncio.run(client.retrieve(question, [dataset_id]))
            except RagFlowError as error:
                print("nova_attempt=", attempt, "error=", str(error), "seconds=", round(time.monotonic() - started, 3))
            else:
                print("nova_attempt=", attempt, "seconds=", round(time.monotonic() - started, 3))
                break
        if result is None:
            raise RuntimeError("All five Nova retrieval attempts failed")
        found = any(marker in item["content"] for item in result["sources"])
        print("nova_retrieval_status=", result["status"])
        print("nova_source_count=", len(result["sources"]))
        print("expected_fact_found=", found)
        if not found:
            raise RuntimeError("Nova retrieval did not find the test fact")

        class ConsoleRequest:
            async def json(self):
                return {"avatar_id": "nova-smoke", "question": question}

        with patch.dict(os.environ, {"NOVA_RAGFLOW_API_KEY": token}), patch(
            "src.server.routes.ragflow.avatar_settings",
            return_value={"enabled": True, "dataset_ids": [dataset_id]},
        ):
            listing = asyncio.run(list_ragflow_datasets(None))
            listing_payload = json.loads(listing.text)
            print("console_list_status=", listing.status)
            print("console_dataset_visible=", any(
                item["id"] == dataset_id
                for item in listing_payload.get("data", {}).get("datasets", [])
            ))
            answer = asyncio.run(test_ragflow_retrieval(ConsoleRequest()))
            answer_payload = json.loads(answer.text)
            console_found = any(
                marker in item.get("content", "")
                for item in answer_payload.get("data", {}).get("sources", [])
            )
            print("console_test_status=", answer.status)
            print("console_expected_fact_found=", console_found)
            if answer.status != 200 or not console_found:
                raise RuntimeError("Nova console retrieval test did not find the test fact")
    finally:
        session.headers["Authorization"] = auth
        if dataset_id:
            cleanup = session.delete(
                BASE_URL + "/api/v1/datasets",
                json={"ids": [dataset_id]},
                timeout=30,
            )
            print("cleanup_dataset=", cleanup.status_code, cleanup.json().get("code"))
        if token:
            cleanup = session.delete(
                BASE_URL + "/api/v1/system/tokens/" + quote(token, safe=""),
                timeout=10,
            )
            print("cleanup_api_key=", cleanup.status_code, cleanup.json().get("code"))


if __name__ == "__main__":
    main()
