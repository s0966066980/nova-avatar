<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# ER-NeRF／TalkingGaussian 不安全載入
Status: ready-for-agent

[安全強化 08](../../security-hardening/issues/08-safe-loading.md) 只處理 MuseTalk、Wav2Lip、UltraLight。`src/avatars/ernerf` 與 `src/avatars/talkinggaussian` 仍有 `torch.load`／`pickle.load` 未限制。改用 `src/avatars/asset_io.py` 或 `weights_only=True`，保留第三方聲明並加修改聲明；擴充 `tests/test_avatar_safe_loading.py` 的掃描範圍。

## Comments
