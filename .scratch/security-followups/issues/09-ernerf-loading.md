<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# ER-NeRF／TalkingGaussian 不安全載入
Status: resolved

[安全強化 08](../../security-hardening/issues/08-safe-loading.md) 只處理 MuseTalk、Wav2Lip、UltraLight。`src/avatars/ernerf` 與 `src/avatars/talkinggaussian` 仍有 `torch.load`／`pickle.load` 未限制。改用 `src/avatars/asset_io.py` 或 `weights_only=True`，保留第三方聲明並加修改聲明；擴充 `tests/test_avatar_safe_loading.py` 的掃描範圍。

## Comments
- 2026-11-27：不再適用。ER-NeRF 與 TalkingGaussian 引擎已在 `4ed6db0` 移除，程式碼裡沒有對應的 `torch.load`／`pickle.load`。MuseTalk 的載入由 `avatar/tests/test_avatar_safe_loading.py` 掃描；`avatar/nova_render/musetalk/models/unet.py:44` 的 `torch.load(model_path)` 屬於上游 MuseTalk 模型權重，仍未加 `weights_only`，不在這張工單範圍，若要處理請另開工單。
