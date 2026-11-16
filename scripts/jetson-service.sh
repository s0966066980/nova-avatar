#!/usr/bin/env bash
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

# Nova Avatar Jetson systemd --user service manager and resource preflight CLI.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_NAME="nova-avatar.service"
UNIT_TEMPLATE="$PROJECT_ROOT/integrations/systemd/nova-avatar.service"
SYSTEMD_USER_DIR="${NOVA_SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
UNIT_TARGET="$SYSTEMD_USER_DIR/$UNIT_NAME"

CONFIG_FILE="${NOVA_CONFIG_FILE:-config/config_jetson.yaml}"
CPU_THREADS="${NOVA_AVATAR_CPU_THREADS:-1}"
START_RAGFLOW="${NOVA_START_RAGFLOW:-0}"

# shellcheck source=lib/server-config.sh
. "$PROJECT_ROOT/scripts/lib/server-config.sh"

usage() {
    cat <<EOF
用法：$0 <subcommand> [options]

Subcommands:
  install       安裝並啟用 systemd --user 服務（${UNIT_NAME}）
  uninstall     停止、停用並移除 systemd --user 服務
  start         啟動 ${UNIT_NAME}（先執行前置與資源提示檢查）
  stop          停止 ${UNIT_NAME}
  restart       重啟 ${UNIT_NAME}
  status        檢視服務狀態、健康端點與外部 ollama 記憶體提示
  logs [args]   檢視 journald 服務日誌（預設 -n 100 -f；檔案日誌位於 logs/）
  check         執行非破壞性前置檢查（設定、憑證、web/dist、linger、ollama）
  health        查詢健康端點並驗證 ready: true（成功回傳 0，未就緒回傳 1）
  render-unit   輸出套用目前專案路徑與環境預設值的 systemd unit 內容
  stop-ollama   明確停止並停用系統級 ollama 服務（需使用者手動執行此指令）
EOF
}

resolve_config_path() {
    if [[ "$CONFIG_FILE" = /* ]]; then
        printf '%s\n' "$CONFIG_FILE"
    else
        printf '%s/%s\n' "$PROJECT_ROOT" "$CONFIG_FILE"
    fi
}

read_config_value() {
    local cfg="$1"
    local key="$2"
    [ -f "$cfg" ] || return 0
    awk -v k="$key" '$1 == k ":" {sub(/^[[:space:]]*[^:]+:[[:space:]]*/, ""); gsub(/["'\'' ]/, ""); print; exit}' "$cfg" 2>/dev/null || true
}

health_url() {
    local cfg
    cfg="$(resolve_config_path)"
    local proto port
    proto="$(read_protocol "$cfg")"
    port="$(read_backend_port "$cfg")"
    printf '%s://127.0.0.1:%s/health\n' "$proto" "$port"
}

build_service_path() {
    local base="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    local uv_bin
    uv_bin="$(command -v uv 2>/dev/null || true)"
    if [ -n "$uv_bin" ]; then
        local uv_dir
        uv_dir="$(dirname "$uv_bin")"
        case ":$base:" in
            *":$uv_dir:"*) ;;
            *) base="$uv_dir:$base" ;;
        esac
    fi
    printf '%s\n' "$base"
}

render_unit() {
    if [ ! -f "$UNIT_TEMPLATE" ]; then
        printf '找不到 unit 模板：%s\n' "$UNIT_TEMPLATE" >&2
        return 1
    fi
    local service_path
    service_path="$(build_service_path)"
    awk \
        -v root="$PROJECT_ROOT" \
        -v spath="$service_path" \
        -v threads="$CPU_THREADS" \
        -v ragflow="$START_RAGFLOW" \
        -v cfg="$CONFIG_FILE" \
        '{
            gsub(/%h\/nova-avatar/, root)
            if ($0 ~ /^Environment=PATH=/) {
                print "Environment=PATH=" spath
            } else if ($0 ~ /^Environment=OMP_NUM_THREADS=/) {
                print "Environment=OMP_NUM_THREADS=" threads
            } else if ($0 ~ /^Environment=OPENBLAS_NUM_THREADS=/) {
                print "Environment=OPENBLAS_NUM_THREADS=" threads
            } else if ($0 ~ /^Environment=MKL_NUM_THREADS=/) {
                print "Environment=MKL_NUM_THREADS=" threads
            } else if ($0 ~ /^Environment=OPENCV_FOR_THREADS_NUM=/) {
                print "Environment=OPENCV_FOR_THREADS_NUM=" threads
            } else if ($0 ~ /^Environment=NOVA_START_RAGFLOW=/) {
                print "Environment=NOVA_START_RAGFLOW=" ragflow
            } else if ($0 ~ /^ExecStart=/) {
                print "ExecStart=/usr/bin/env bash scripts/start-server.sh --systemd " cfg
            } else {
                print
            }
        }' "$UNIT_TEMPLATE"
}

inspect_ollama() {
    local ps_lines=""
    ps_lines="$(ps -eo pid=,rss=,comm=,args= 2>/dev/null | awk '$3 == "ollama" || $4 ~ /(^|\/)ollama$/ {print}' || true)"
    local sys_active="inactive"
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet ollama 2>/dev/null; then
            sys_active="active"
        fi
    fi

    if [ -z "$ps_lines" ] && [ "$sys_active" != "active" ]; then
        printf '✓ 外部 ollama：未執行（無額外記憶體佔用）\n'
        return 0
    fi

    local total_kb=0
    local count=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        local rss_kb
        rss_kb="$(printf '%s\n' "$line" | awk '{print $2}')"
        if [[ "$rss_kb" =~ ^[0-9]+$ ]]; then
            total_kb=$((total_kb + rss_kb))
        fi
        count=$((count + 1))
    done <<< "$ps_lines"

    local mem_desc
    mem_desc="$(awk -v kb="$total_kb" 'BEGIN { printf "%.0f MB (%.2f GB)", kb / 1024.0, kb / 1048576.0 }')"
    if [ "$START_RAGFLOW" = "0" ]; then
        printf '⚠ 偵測到外部 ollama 正在執行（systemd=%s, 程序數=%d, RSS=%s），而 NOVA_START_RAGFLOW=0。\n' \
            "$sys_active" "$count" "$mem_desc"
        printf '  Phase 1 若不使用知識庫/Ollama，建議手動停止並停用外部 ollama 以釋放統一記憶體：\n'
        printf '    sudo systemctl stop ollama\n'
        printf '    sudo systemctl disable --now ollama\n'
        printf '  或執行明確停用指令：bash scripts/jetson-service.sh stop-ollama\n'
    else
        printf 'ℹ 偵測到外部 ollama 正在執行（systemd=%s, 程序數=%d, RSS=%s；NOVA_START_RAGFLOW=%s）。\n' \
            "$sys_active" "$count" "$mem_desc" "$START_RAGFLOW"
    fi
}

check_linger() {
    if ! command -v loginctl >/dev/null 2>&1; then
        printf 'ℹ 無法執行 loginctl，略過 linger 檢查\n'
        return 0
    fi
    local user_name="${USER:-$(id -un)}"
    local linger=""
    linger="$(loginctl show-user "$user_name" -p Linger --value 2>/dev/null || true)"
    if [ "$linger" = "yes" ]; then
        printf '✓ loginctl Linger=yes（開機後可自動維持 user systemd 服務）\n'
    else
        printf '⚠ loginctl Linger=%s：開機未登入桌面時 systemd --user 不會自動啟動。\n' "${linger:-unknown}"
        printf '  若需開機自啟，請手動執行：sudo loginctl enable-linger %s\n' "$user_name"
    fi
}

run_check() {
    local cfg
    cfg="$(resolve_config_path)"
    local ok=1

    printf '=== Nova Avatar Jetson 服務前置檢查 ===\n'
    printf '專案目錄：%s\n' "$PROJECT_ROOT"
    printf '設定檔案：%s\n' "$cfg"
    printf 'Phase 1 RAGFlow：NOVA_START_RAGFLOW=%s\n' "$START_RAGFLOW"
    printf '健康端點：%s\n' "$(health_url)"
    printf '日誌路徑：journalctl --user -u %s 及 %s/logs/\n' "$UNIT_NAME" "$PROJECT_ROOT"

    if [ -f "$cfg" ]; then
        printf '✓ 設定檔存在\n'
    else
        printf '✗ 找不到設定檔：%s\n' "$cfg" >&2
        ok=0
    fi

    if command -v uv >/dev/null 2>&1; then
        printf '✓ uv：%s\n' "$(command -v uv)"
    else
        printf '✗ 找不到 uv（請將 ~/.local/bin 加入 PATH）\n' >&2
        ok=0
    fi

    if [ -d "$PROJECT_ROOT/.venv" ] || [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then
        printf '✓ Python 虛擬環境已就緒\n'
    else
        printf '✗ 找不到 %s/.venv\n' "$PROJECT_ROOT" >&2
        ok=0
    fi

    if [ -f "$PROJECT_ROOT/web/dist/index.html" ] && [ -f "$PROJECT_ROOT/web/dist/stage.html" ]; then
        printf '✓ 前端建置產物 web/dist 已就緒\n'
    else
        printf '⚠ web/dist 不完整，請執行：cd web && npm run build\n'
    fi

    if [ -f "$cfg" ] && grep -Eq '^[[:space:]]*ssl:[[:space:]]*true([[:space:]]|$)' "$cfg"; then
        local cert_rel key_rel
        cert_rel="$(read_config_value "$cfg" "ssl_cert")"
        key_rel="$(read_config_value "$cfg" "ssl_key")"
        cert_rel="${cert_rel:-ssl_certs/localhost.crt}"
        key_rel="${key_rel:-ssl_certs/localhost.key}"
        if [ -f "$PROJECT_ROOT/$cert_rel" ] && [ -f "$PROJECT_ROOT/$key_rel" ]; then
            printf '✓ HTTPS 憑證已就緒（%s, %s）\n' "$cert_rel" "$key_rel"
        else
            printf '⚠ 找不到 HTTPS 憑證（%s / %s），請執行 bash scripts/create_ssl_certs.sh\n' "$cert_rel" "$key_rel"
        fi
    fi

    check_linger
    inspect_ollama

    if command -v systemctl >/dev/null 2>&1; then
        local active_state
        active_state="$(systemctl --user is-active "$UNIT_NAME" 2>/dev/null || true)"
        printf '服務狀態（%s）：%s\n' "$UNIT_NAME" "${active_state:-unknown}"
    fi

    [ "$ok" -eq 1 ]
}

check_health() {
    local url
    url="$(health_url)"
    local body=""
    if ! body="$(curl -skf --max-time 3 "$url" 2>/dev/null)"; then
        printf '健康檢查失敗：無法連線 %s\n' "$url" >&2
        return 1
    fi
    printf '%s\n' "$body"
    if printf '%s' "$body" | grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'; then
        return 0
    fi
    printf '服務尚未就緒（ready != true）：%s\n' "$url" >&2
    return 1
}

require_systemctl_user() {
    if ! command -v systemctl >/dev/null 2>&1; then
        printf '找不到 systemctl。\n' >&2
        return 1
    fi
}

cmd_install() {
    require_systemctl_user
    mkdir -p "$SYSTEMD_USER_DIR" "$PROJECT_ROOT/logs"
    render_unit >"$UNIT_TARGET"
    chmod 0644 "$UNIT_TARGET"
    systemctl --user daemon-reload
    systemctl --user enable "$UNIT_NAME"
    printf '✓ 已安裝並啟用 %s -> %s\n' "$UNIT_NAME" "$UNIT_TARGET"
    check_linger
    inspect_ollama
    printf '下一步：\n'
    printf '  啟動服務：bash scripts/jetson-service.sh start\n'
    printf '  查看狀態：bash scripts/jetson-service.sh status\n'
    printf '  即時日誌：bash scripts/jetson-service.sh logs\n'
}

cmd_uninstall() {
    require_systemctl_user
    systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT_TARGET"
    systemctl --user daemon-reload
    printf '✓ 已停止、停用並移除 %s\n' "$UNIT_TARGET"
}

cmd_start() {
    require_systemctl_user
    run_check
    systemctl --user start "$UNIT_NAME"
    printf '✓ 已送出啟動指令；可用 bash scripts/jetson-service.sh status 或 health 確認就緒\n'
}

cmd_stop() {
    require_systemctl_user
    systemctl --user stop "$UNIT_NAME"
    printf '✓ 已停止 %s\n' "$UNIT_NAME"
}

cmd_restart() {
    require_systemctl_user
    run_check
    systemctl --user restart "$UNIT_NAME"
    printf '✓ 已送出重啟指令；可用 bash scripts/jetson-service.sh status 或 health 確認就緒\n'
}

cmd_status() {
    require_systemctl_user
    systemctl --user status "$UNIT_NAME" --no-pager || true
    printf '\n--- 健康與資源檢查 ---\n'
    check_health || true
    inspect_ollama
    printf '檔案日誌目錄：%s/logs/（systemd 日誌：journalctl --user -u %s）\n' "$PROJECT_ROOT" "$UNIT_NAME"
}

cmd_logs() {
    if ! command -v journalctl >/dev/null 2>&1; then
        printf '找不到 journalctl；可改檢視 %s/logs/\n' "$PROJECT_ROOT" >&2
        return 1
    fi
    printf '提示：systemd 日誌來自 journald；後端與 llama-server 檔案日誌位於 %s/logs/\n' "$PROJECT_ROOT" >&2
    if [ "$#" -gt 0 ]; then
        exec journalctl --user -u "$UNIT_NAME" "$@"
    fi
    exec journalctl --user -u "$UNIT_NAME" -n "${NOVA_LOG_LINES:-100}" -f
}

cmd_stop_ollama() {
    if ! command -v systemctl >/dev/null 2>&1; then
        printf '找不到 systemctl。\n' >&2
        return 1
    fi
    if [ "$(id -u)" -eq 0 ]; then
        systemctl disable --now ollama
    else
        sudo systemctl disable --now ollama
    fi
    printf '✓ 已停止並停用系統級 ollama 服務（若日後啟用 RAGFlow 共用模型可執行 sudo systemctl enable --now ollama）\n'
}

case "${1:-}" in
    --help|-h|help)
        usage
        ;;
    render-unit)
        render_unit
        ;;
    check)
        run_check
        ;;
    health)
        check_health
        ;;
    install)
        cmd_install
        ;;
    uninstall)
        cmd_uninstall
        ;;
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        shift
        cmd_logs "$@"
        ;;
    stop-ollama)
        cmd_stop_ollama
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
