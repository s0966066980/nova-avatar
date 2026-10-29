<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 模型原始碼被 `models/` 規則排除於版控
Status: ready-for-human

`.gitignore` 的 `models/` 同時排除 `src/avatars/musetalk/models/` 與 `src/avatars/wav2lip/models/`，這些是程式碼而非權重。乾淨 checkout 與 CI 沒有它們；本機 `src/avatars/musetalk/models/unet.py` 仍以 `torch.load` 載入且未設 `weights_only=True`，任何 repo 內的修正都碰不到。

需人決定：這些檔案的來源與授權（MuseTalk MIT／Tencent、Wav2Lip 研究非商用），是否納入版控。若納入：規則改為 `/models/`，加入檔案並依 AGENTS.md 保留上游聲明、加修改聲明，`torch.load` 改 `weights_only=True`，並讓 `tests/test_avatar_safe_loading.py` 的掃描涵蓋它們。

## Comments
