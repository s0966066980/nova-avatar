<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 模型與素材安全載入
Status: resolved
Blocked by: 06

依[規格](../spec.md)。`src/avatars/musetalk/avatar.py:219-226` 以 `torch.load`（torch 2.5 預設 `weights_only=False`）與 `pickle.load` 載入角色素材；ultralight 等同類。可寫目錄 + 這些載入 = 程式碼執行。

- 角色素材的 tensor 改 `torch.load(..., weights_only=True)`。
- `coords`／`mask_coords` 建置時改存 `.npy`（或 JSON）；載入時若只有舊 `.pkl`，以受限 unpickler（只允許 tuple/list/int/float/numpy 標量）一次性轉換後改用新格式。
- 掃描 `src/avatars/{musetalk,ultralight,wav2lip}` 中其餘 `torch.load`／`pickle.load`：能用 `weights_only=True` 的改掉；不能的（第三方權重）在 issue Comments 列出理由。依 AGENTS.md 保留第三方授權聲明並加修改聲明。

完成：惡意 pickle 素材載入失敗的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29 實作結果（分支 `sh/08-safe-loading`）

- 新增 `src/avatars/asset_io.py`：`load_coords`／`save_coords` 以 JSON 存取臉框（驗證為「每筆 4 個有限數值」、檔案上限 16 MiB）；`load_avatar_tensors` 以 `weights_only=True` 載入。
- 舊 `coords.pkl`／`mask_coords.pkl` 只在沒有 `.json` 時以受限 unpickler 讀取：只重建 list／tuple／int／float 與數值型 NumPy 標量（`numpy.dtype`、`numpy[._]core.multiarray.scalar` 以驗證用替身取代，不呼叫 NumPy 的 `__setstate__`，拒絕 object／結構化 dtype），之後原子寫出 `.json`，往後只讀 JSON。舊 `.pkl` 保留不刪；目錄唯讀時照常載入，只記警告。
- 以主 checkout 真實角色的**副本**（未動原檔）驗證：8 個舊 `.pkl`（含 `wav2lip256_avatar1` 的 NumPy 標量）全部轉換成功；兩個 `latents.pt` 以 `weights_only=True` 可載入。
- 改用新格式：MuseTalk／Wav2Lip／UltraLight 的 `load_avatar`、`builder.py`（輸出 `coords.json`／`mask_coords.json`）、三個 `genavatar*` 腳本、`catalog.detect_avatar_type`（`.json` 或舊 `.pkl` 皆可辨識）。
- 其餘 `torch.load`／`load_url` 全部加 `weights_only=True`：Wav2Lip `_load`、兩個 SFD 偵測器（含 `load_url` 下載路徑）、face-parsing `__init__`／`resnet.py`、Whisper `load_model`、`training_utils.py` 兩處、UltraLight `ultralight.pth`／`get_landmark.py`／`genavatar-bak.py`。已用真實 `wav2lip256.pth`、`79999_iter.pth`、`resnet18-5c106cde.pth`、`s3fd-619a316812.pth`、`unet.pth` 確認可載入。範圍內沒有必須保留 `weights_only=False` 的第三方權重。無標頭的第三方檔已補上游來源與 `Modified by HongXian0903` 聲明。
- 測試：新增 `tests/test_avatar_safe_loading.py`（20 項）：惡意 pickle 臉框／latents 不執行、非數值或錯誤形狀被拒、一次性轉換、唯讀目錄、MuseTalk `load_avatar` 整合、builder 輸出 JSON，以及 AST 靜態守門（追蹤中的三個引擎原始碼不得有 `pickle.load(s)`／`Unpickler`，`torch.load`／`load_url` 必須 `weights_only=True`）。
- 驗證：ruff、check-integration、pytest（僅既知 2 項 worktree 基準失敗）、web lint／test／build 全過。
- 未處理（範圍外）：`.gitignore` 的 `models/` 規則也忽略了 `src/avatars/musetalk/models/` 與 `src/avatars/wav2lip/models/` 原始碼；主 checkout 的 `musetalk/models/unet.py` 仍以不帶 `weights_only` 的 `torch.load` 載入 `unet.pth`，無法在版本庫內修正，建議改成 `/models/` 後納入追蹤再補。`ernerf`、`talkinggaussian` 中的 `torch.load`／`np.load(allow_pickle=True)` 不在本票範圍。
