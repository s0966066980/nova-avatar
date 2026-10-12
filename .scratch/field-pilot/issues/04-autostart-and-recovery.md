# 開機自啟、自動重啟、更新與監控

Type: task
Status: needs-triage
Trigger: 確定版本後

目前沒有 Nova 自己的 systemd 服務，當機或斷電後要人手動恢復。
建議方向：開機自動啟動 llama-server、後端、前端、RAGFlow 與 kiosk 瀏覽器；服務當掉自動重啟；補更新流程與遠端監控。
