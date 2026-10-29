<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 模型與素材安全載入
Status: ready-for-agent
Blocked by: 06

依[規格](../spec.md)。`src/avatars/musetalk/avatar.py:219-226` 以 `torch.load`（torch 2.5 預設 `weights_only=False`）與 `pickle.load` 載入角色素材；ultralight 等同類。可寫目錄 + 這些載入 = 程式碼執行。

- 角色素材的 tensor 改 `torch.load(..., weights_only=True)`。
- `coords`／`mask_coords` 建置時改存 `.npy`（或 JSON）；載入時若只有舊 `.pkl`，以受限 unpickler（只允許 tuple/list/int/float/numpy 標量）一次性轉換後改用新格式。
- 掃描 `src/avatars/{musetalk,ultralight,wav2lip}` 中其餘 `torch.load`／`pickle.load`：能用 `weights_only=True` 的改掉；不能的（第三方權重）在 issue Comments 列出理由。依 AGENTS.md 保留第三方授權聲明並加修改聲明。

完成：惡意 pickle 素材載入失敗的回歸測試；完整 CI 通過。

## Comments
