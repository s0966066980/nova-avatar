<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->

# RAGFlow ARM64 deployment

Build and run RAGFlow v0.27.2 natively on this Jetson AGX Orin, preserve existing
data and credentials, restore Jetson startup integration, and verify document
parsing and retrieval through Nova Avatar.

The pinned source commit is a024bea0cd93f39e6652a42bf84dd20c55bc560b.
Do not upgrade the RAGFlow database schema or delete existing volumes.
Keep the existing Elasticsearch, MySQL, MinIO-compatible and Valkey services.
Publish only the existing loopback management/API ports.

Acceptance: linux/arm64 image, healthy API and task executor, successful test
document ingestion and retrieval, Nova client connectivity, reproducible build
instructions, focused tests and required project validation.
