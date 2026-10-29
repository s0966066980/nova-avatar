<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 後端被 SIGKILL 時 llama-server 成孤兒
Status: ready-for-agent

`src/llm/llamacpp.py` 以獨立 session 啟動 llama-server；後端正常結束會停止它，但被 SIGKILL 時不會，GPU 記憶體持續被占用。CosyVoice 已在啟動腳本中處理（[安全強化 16](../../security-hardening/issues/16-launcher-processes.md)）。

比照 CosyVoice：啟動腳本在啟動與結束時停止本 checkout 留下的 llama-server（以 cmdline 比對，不誤殺其他程序），或在 Linux 上讓子程序設 `PR_SET_PDEATHSIG`。完成：`tests/test_startup_scripts.py` 以假程序覆蓋。

## Comments
