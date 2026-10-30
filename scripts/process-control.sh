# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# Nova Avatar 啟動腳本共用的程序管理。只終止屬於本專案目錄的程序：
# 占用埠的其他程式一律報錯，不會被誤殺。先設定 PROJECT_ROOT 再 source。

# SIGTERM 後等待程序自行結束的秒數，逾時才 SIGKILL。後端關閉連線、
# llama-server、BreezyVoice（CosyVoice 伺服器）與 Fun-ASR-Nano 最多約 15 秒；SIGKILL 會略過其 atexit 清理。
NOVA_STOP_GRACE_SECONDS="${NOVA_STOP_GRACE_SECONDS:-20}"
if [[ ! "$NOVA_STOP_GRACE_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "NOVA_STOP_GRACE_SECONDS 必須為非負整數秒數" >&2
    exit 1
fi

# 程序存在且不是殭屍。
nova_pid_alive() {
    local line
    { read -r line < "/proc/$1/stat"; } 2>/dev/null || return 1
    line=${line##*) }
    [ "${line%% *}" != Z ]
}

# 程序群組內仍有存活（非殭屍）程序。
nova_group_alive() {
    local pgid=$1 stat line
    local -a fields
    for stat in /proc/[0-9]*/stat; do
        { read -r line < "$stat"; } 2>/dev/null || continue
        # 欄位：state ppid pgrp ...（皆為數字或單一字母，可安全分詞）
        # shellcheck disable=SC2206
        fields=(${line##*) })
        if [ "${fields[2]}" = "$pgid" ] && [ "${fields[0]}" != Z ]; then
            return 0
        fi
    done
    return 1
}

nova_cmdline() {
    local -a args=()
    { mapfile -t -d '' args < "/proc/$1/cmdline"; } 2>/dev/null || return 1
    printf '%s' "${args[*]}"
}

# 指令列符合 $2（glob），且指令列含本專案路徑或工作目錄在本專案內。
nova_owned_pid() {
    local pid=$1 pattern=$2 cmdline cwd
    cmdline=$(nova_cmdline "$pid") || return 1
    # shellcheck disable=SC2053 # $pattern 是刻意的 glob
    [[ $cmdline == $pattern ]] || return 1
    [[ $cmdline == *"$PROJECT_ROOT/"* ]] && return 0
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null) || return 1
    [[ $cwd == "$PROJECT_ROOT" || $cwd == "$PROJECT_ROOT/"* ]]
}

nova_listener_pids() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti:"$port" -sTCP:LISTEN 2>/dev/null || true
    else
        ss -Hltnp "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true
    fi
}

# 等待 $1（函式）對其餘參數全部回報不存活，最多 NOVA_STOP_GRACE_SECONDS 秒。
nova_wait_until_gone() {
    local check=$1 ticks
    shift
    for ((ticks = 0; ticks < NOVA_STOP_GRACE_SECONDS * 2; ticks++)); do
        nova_any_alive "$check" "$@" || return 0
        sleep 0.5
    done
    ! nova_any_alive "$check" "$@"
}

nova_any_alive() {
    local check=$1 item
    shift
    for item in "$@"; do
        "$check" "$item" && return 0
    done
    return 1
}

# 先 SIGTERM，寬限期後仍存活才 SIGKILL。
nova_stop_pids() {
    local pid
    [ "$#" -gt 0 ] || return 0
    kill -TERM "$@" 2>/dev/null || true
    nova_wait_until_gone nova_pid_alive "$@" && return 0
    echo "⚠ 程序 $* 未在 ${NOVA_STOP_GRACE_SECONDS} 秒內結束，強制終止" >&2
    kill -KILL "$@" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        nova_any_alive nova_pid_alive "$@" || return 0
        sleep 0.2
    done
    for pid in "$@"; do
        nova_pid_alive "$pid" && return 1
    done
    return 0
}

# 終止整個程序群組（含已成孤兒的子程序）。
nova_stop_group() {
    local pgid=$1
    nova_group_alive "$pgid" || return 0
    kill -TERM -- "-$pgid" 2>/dev/null || true
    nova_wait_until_gone nova_group_alive "$pgid" && return 0
    echo "⚠ 程序群組 $pgid 未在 ${NOVA_STOP_GRACE_SECONDS} 秒內結束，強制終止" >&2
    kill -KILL -- "-$pgid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        nova_group_alive "$pgid" || return 0
        sleep 0.2
    done
    return 1
}

# 清理埠：只終止本專案符合 $2 的監聽程序；其他程式占用則報錯並回傳 1。
nova_clear_port() {
    local port=$1 pattern=$2 pid
    local -a pids=()
    mapfile -t pids < <(nova_listener_pids "$port")
    [ "${#pids[@]}" -gt 0 ] || return 0
    for pid in "${pids[@]}"; do
        if ! nova_owned_pid "$pid" "$pattern"; then
            echo "❌ 埠 $port 被非本專案 Nova 的程式佔用（PID $pid: $(nova_cmdline "$pid" | cut -c1-160)）" >&2
            echo "   不會自動終止；請關閉該程式或改用其他埠後重試" >&2
            return 1
        fi
    done
    echo "⚠ 停止佔用埠 $port 的舊 Nova 程序（PID ${pids[*]}）"
    nova_stop_pids "${pids[@]}" || true
    mapfile -t pids < <(nova_listener_pids "$port")
    if [ "${#pids[@]}" -gt 0 ]; then
        echo "❌ 無法清理埠 $port（PID ${pids[*]}），請手動處理" >&2
        return 1
    fi
    echo "✓ 埠 $port 已清理"
}

# 後端自行啟動的模型服務以獨立 session 執行：BreezyVoice 的 CosyVoice 伺服器
# （src/tts/cosyvoice_runtime.py）與 Fun-ASR-Nano 辨識服務（src/asr/fun_asr_nano_service.py）。
# 後端被強制終止時它們會成孤兒繼續占用 GPU；停止本專案殘留的這些服務。
nova_stop_model_servers() {
    local proc script
    local -a args pids=()
    local -a scripts=(
        "$PROJECT_ROOT/scripts/cosyvoice_fastapi_server.py"
        "$PROJECT_ROOT/scripts/fun_asr_nano_server.py"
    )
    for proc in /proc/[0-9]*; do
        { mapfile -t -d '' args < "$proc/cmdline"; } 2>/dev/null || continue
        # 只比對「直譯器 腳本路徑 ...」，不誤殺正在檢視該檔的編輯器等程式。
        for script in "${scripts[@]}"; do
            [ "${args[1]:-}" = "$script" ] && pids+=("${proc#/proc/}")
        done
    done
    [ "${#pids[@]}" -gt 0 ] || return 0
    echo "⚠ 停止殘留的模型服務（BreezyVoice／Fun-ASR-Nano，PID ${pids[*]}）"
    if ! nova_stop_pids "${pids[@]}"; then
        echo "❌ 模型服務（PID ${pids[*]}）仍在執行，請手動終止以釋放 GPU" >&2
        return 1
    fi
}
