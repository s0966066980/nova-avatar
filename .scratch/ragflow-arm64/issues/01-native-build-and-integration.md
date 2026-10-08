<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# Native build and startup integration

Status: resolved

Build the pinned ARM64 image, fix native dependency failures, preserve data,
restore startup integration and verify actual ingestion/retrieval.

## Evidence

- Host: aarch64; existing RAGFlow image: linux/amd64.
- Existing RAGFlow main container repeatedly exits with exec format error.
- Four supporting service images are already linux/arm64 and healthy.
- Jetson startup explicitly disables RAGFlow by default.

## Answer

Native image built and running at the pinned v0.27.2 source commit. All five
containers are healthy. Text and scanned PDF OCR ingestion and real Nova
retrieval passed; the temporary dataset was removed. Native Ollama/BGE-M3 and
private API credentials are configured. Normal Jetson startup now uses auto.

The local database was uninitialized before this work, so no PC knowledge base
was present to migrate; existing avatar selections remain but need reselecting
after the user's documents are imported. Full validation ran: one pre-existing
Orin image-composite timing threshold fails; other required checks passed.

See [deployment report](../../../docs/reports/ragflow-arm64.md) and local
verification.json/build.log for evidence.
