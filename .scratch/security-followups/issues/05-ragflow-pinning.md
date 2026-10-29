<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# RAGFlow 原始碼與附屬映像固定版本
Status: ready-for-agent

RAGFlow 主映像已固定 digest，但上游原始碼只固定 tag（`v0.27.2`，commit `a024bea0…`），Compose 的 MySQL、Elasticsearch、MinIO、Redis 映像未固定 digest。見 [安全強化 17](../../security-hardening/issues/17-pinning-offline.md) Comments。

`scripts/ragflow_prepare.py`：checkout 後驗證 commit；改寫 Compose 的附屬映像為 `tag@sha256`，`validate` 拒絕未固定者。既有部署重跑 `prepare` 不得改動密碼。

## Comments
