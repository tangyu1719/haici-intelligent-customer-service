#!/usr/bin/env bash
# HaiChi 服务管理公共库（Linux / macOS 生产级）
# 被 start.sh / stop.sh / restart.sh source 使用，请勿直接执行。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${PROJECT_ROOT}/backend"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
RUN_DIR="${PROJECT_ROOT}/.run"
LOG_DIR="${RUN_DIR}/logs"
LOCK_FILE="${RUN_DIR}/service.lock"

# ── 可覆盖默认值（亦可通过 .env / 环境变量配置） ──
: "${HAICI_DEPLOY_MODE:=dev}"          # dev | prod
: "${HAICI_BIND_HOST:=127.0.0.1}"      # prod 建议 0.0.0.0
: "${HAICI_BACKEND_PORT:=8012}"
: "${HAICI_FRONTEND_PORT:=5173}"
: "${HAICI_CHROMA_PORT:=8001}"
: "${HAICI_MYSQL_PORT:=${MYSQL_PORT:-3307}}"
: "${UVICORN_WORKERS:=2}"
: "${HAICI_GRACEFUL_STOP_SEC:=20}"
: "${HAICI_HEALTH_TIMEOUT_SEC:=120}"
: "${HAICI_CHROMA_PERSIST_PATH:=${CHROMA_PERSIST_PATH:-}}"

# prod 模式默认对外绑定
if [[ "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
  : "${HAICI_BIND_HOST:=0.0.0.0}"
fi

# ── 日志 ──
_haici_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_info()  { echo "[$(_haici_ts)] [INFO ] $*"; }
log_ok()    { echo "[$(_haici_ts)] [ OK  ] $*" >&2; }
log_warn()  { echo "[$(_haici_ts)] [WARN ] $*" >&2; }
log_err()   { echo "[$(_haici_ts)] [ERROR] $*" >&2; }
log_fail()  { echo "[$(_haici_ts)] [FAIL ] $*" >&2; }

log_event() {
  # 结构化单行日志（对齐项目 logging-spec）
  local chain="$1" module="$2" obj="$3" kind="$4" phase="$5" msg="$6"
  shift 6
  local kv=""
  for arg in "$@"; do kv+="${kv:+; }${arg}"; done
  echo "[$(_haici_ts)] [${chain}|${module}|${obj}|${kind}|${phase}] ${msg}${kv:+; ${kv}}"
}

# ── 目录 / 环境 ──
ensure_run_dirs() {
  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
}

load_env_files() {
  local f
  for f in "${PROJECT_ROOT}/.env" "${BACKEND_DIR}/.env"; do
    if [[ -f "${f}" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "${f}"
      set +a
      log_info "已加载环境: ${f}"
    fi
  done
  # 再次应用 HAICI_* 默认（.env 可能覆盖 MYSQL_PORT 等）
  : "${HAICI_MYSQL_PORT:=${MYSQL_PORT:-3307}}"
  : "${HAICI_CHROMA_PERSIST_PATH:=${CHROMA_PERSIST_PATH:-}}"
  if [[ -z "${HAICI_CHROMA_PERSIST_PATH}" && "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
    HAICI_CHROMA_PERSIST_PATH="${RUN_DIR}/chroma_persist"
  fi
  export HAICI_DEPLOY_MODE HAICI_BIND_HOST HAICI_BACKEND_PORT HAICI_FRONTEND_PORT
  export HAICI_CHROMA_PORT HAICI_MYSQL_PORT UVICORN_WORKERS
  export HAICI_CHROMA_PERSIST_PATH CHROMA_PERSIST_PATH="${HAICI_CHROMA_PERSIST_PATH}"
}

# ── 互斥锁（防并发启停） ──
LOCK_FD=200
acquire_service_lock() {
  ensure_run_dirs
  eval "exec ${LOCK_FD}>\"${LOCK_FILE}\""
  if ! flock -n "${LOCK_FD}"; then
    log_err "另一服务管理操作进行中（${LOCK_FILE}），请稍后重试"
    exit 1
  fi
}

release_service_lock() {
  flock -u "${LOCK_FD}" 2>/dev/null || true
}

# ── 进程 / 端口工具 ──
get_port_pid() {
  local port="$1"
  local pid=""
  if command -v ss >/dev/null 2>&1; then
    pid="$(ss -ltnp 2>/dev/null | grep -E ":${port}[[:space:]]" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)"
  elif command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | head -1)"
  elif command -v netstat >/dev/null 2>&1; then
    pid="$(netstat -tlnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {gsub(/\/.*/, "", $7); print $7; exit}')"
  fi
  if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
    echo "${pid}"
    return 0
  fi
  return 1
}

is_pid_alive() {
  local pid="$1"
  [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null
}

stop_pid_graceful() {
  local pid="$1" label="$2" timeout="${3:-${HAICI_GRACEFUL_STOP_SEC}}"
  if ! is_pid_alive "${pid}"; then
    return 0
  fi
  log_info "STOP  ${label} 发送 SIGTERM (PID ${pid})"
  kill -TERM "${pid}" 2>/dev/null || true
  local i=0
  while is_pid_alive "${pid}" && (( i < timeout )); do
    sleep 1
    (( i++ )) || true
  done
  if is_pid_alive "${pid}"; then
    log_warn "STOP  ${label} 超时，发送 SIGKILL (PID ${pid})"
    kill -KILL "${pid}" 2>/dev/null || true
    sleep 1
  fi
}

save_pid_file() {
  local name="$1" pid="$2"
  ensure_run_dirs
  echo "${pid}" > "${RUN_DIR}/${name}.pid"
}

read_pid_file() {
  local name="$1" file="${RUN_DIR}/${name}.pid"
  if [[ -f "${file}" ]]; then
    tr -d '[:space:]' < "${file}"
  fi
}

remove_pid_file() {
  local name="$1"
  rm -f "${RUN_DIR}/${name}.pid"
}

stop_by_pid_file() {
  local name="$1"
  local pid
  pid="$(read_pid_file "${name}" || true)"
  if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
    stop_pid_graceful "${pid}" "${name}(pidfile)"
  fi
  remove_pid_file "${name}"
}

stop_port_process() {
  local port="$1" label="${2:-port ${port}}"
  local pid
  if pid="$(get_port_pid "${port}" 2>/dev/null || true)"; then
    stop_pid_graceful "${pid}" "${label}"
  else
    log_info "STOP  ${label} 未监听 :${port}"
  fi
}

wait_port_listen() {
  local port="$1" timeout="${2:-60}" label="${3:-}"
  local deadline=$(( SECONDS + timeout ))
  while (( SECONDS < deadline )); do
    if get_port_pid "${port}" >/dev/null 2>&1; then
      [[ -n "${label}" ]] && log_ok "${label} 已监听 :${port}"
      return 0
    fi
    sleep 0.5
  done
  [[ -n "${label}" ]] && log_fail "${label} 端口 :${port} 等待超时 (${timeout}s)"
  return 1
}

wait_http_ok() {
  local url="$1" timeout="${2:-90}" label="${3:-}"
  local deadline=$(( SECONDS + timeout ))
  while (( SECONDS < deadline )); do
    local code
    code="$(curl -sf -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "${url}" 2>/dev/null || echo "000")"
    if [[ "${code}" =~ ^[23][0-9][0-9]$ ]]; then
      [[ -n "${label}" ]] && log_ok "${label} ${url} (HTTP ${code})"
      return 0
    fi
    sleep 0.8
  done
  [[ -n "${label}" ]] && log_fail "${label} ${url} 健康检查超时 (${timeout}s)"
  return 1
}

# ── 依赖探测 ──
resolve_python() {
  local candidates=()
  if [[ -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
    candidates+=("${BACKEND_DIR}/.venv/bin/python")
  fi
  if [[ -x "${BACKEND_DIR}/.venv/bin/python3" ]]; then
    candidates+=("${BACKEND_DIR}/.venv/bin/python3")
  fi
  local bin
  for bin in python3.12 python3.11 python3 python; do
    if command -v "${bin}" >/dev/null 2>&1; then
      candidates+=("$(command -v "${bin}")")
    fi
  done
  local py ver
  for py in "${candidates[@]}"; do
    ver="$("${py}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
    if awk -v v="${ver}" 'BEGIN { split(v,a,"."); exit (a[1]>=3 && a[2]>=10)?0:1 }'; then
      echo "${py}"
      return 0
    fi
  done
  log_err "未找到 Python 3.10+。请安装或在 backend/ 下创建 .venv"
  return 1
}

resolve_npm() {
  if command -v npm >/dev/null 2>&1; then
    command -v npm
    return 0
  fi
  log_err "未找到 npm，请安装 Node.js 18+"
  return 1
}

test_docker_available() {
  command -v docker >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1
}

# ── 中间件 ──
start_docker_middleware() {
  if ! test_docker_available; then
    log_warn "Docker 不可用；请确保 MySQL:${HAICI_MYSQL_PORT} 与 Chroma:${HAICI_CHROMA_PORT} 已就绪，或设置 CHROMA_PERSIST_PATH"
    return 1
  fi
  log_info "START Docker 中间件 (MySQL + Chroma)..."
  (
    cd "${PROJECT_ROOT}"
    docker compose up -d
  )
  wait_port_listen "${HAICI_MYSQL_PORT}" 90 "MySQL" || return 1
  if [[ -z "${HAICI_CHROMA_PERSIST_PATH}" ]]; then
    wait_port_listen "${HAICI_CHROMA_PORT}" 90 "Chroma HTTP" || return 1
  fi
  log_event "智能客服-部署" "_lib.start_docker_middleware" "docker-compose" "硬编执行" "完成" "ok=true"
  return 0
}

stop_docker_middleware() {
  if ! test_docker_available; then
    log_info "SKIP  Docker 不可用"
    return 0
  fi
  log_info "STOP  Docker 中间件..."
  (
    cd "${PROJECT_ROOT}"
    docker compose stop
  )
}

preflight_middleware() {
  # MySQL 端口
  if ! wait_port_listen "${HAICI_MYSQL_PORT}" 5 "MySQL 预检" 2>/dev/null; then
    log_fail "MySQL 未在 ${MYSQL_HOST:-127.0.0.1}:${HAICI_MYSQL_PORT} 监听"
    return 1
  fi
  # Chroma：持久化目录或 HTTP
  if [[ -n "${HAICI_CHROMA_PERSIST_PATH}" ]]; then
    mkdir -p "${HAICI_CHROMA_PERSIST_PATH}"
    log_ok "Chroma 本地持久化: ${HAICI_CHROMA_PERSIST_PATH}"
  else
    if ! wait_port_listen "${HAICI_CHROMA_PORT}" 5 "Chroma 预检" 2>/dev/null; then
      log_fail "Chroma HTTP 未在 :${HAICI_CHROMA_PORT} 监听，且未设置 CHROMA_PERSIST_PATH"
      return 1
    fi
  fi
  return 0
}

# ── 前端构建（prod） ──
build_frontend_prod() {
  local force="${1:-false}"
  local dist="${FRONTEND_DIR}/dist/index.html"
  if [[ "${force}" != "true" && -f "${dist}" ]]; then
    log_info "前端 dist 已存在，跳过构建（使用 --rebuild-frontend 强制重建）"
    return 0
  fi
  local npm_bin
  npm_bin="$(resolve_npm)"
  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    log_info "INSTALL frontend npm install ..."
    (cd "${FRONTEND_DIR}" && "${npm_bin}" ci 2>/dev/null || "${npm_bin}" install)
  fi
  log_info "BUILD frontend (production) ..."
  (cd "${FRONTEND_DIR}" && "${npm_bin}" run build)
  if [[ ! -f "${dist}" ]]; then
    log_fail "前端构建失败：未生成 dist/index.html"
    return 1
  fi
  log_ok "前端构建完成"
}

# ── 应用进程 ──
start_backend() {
  ensure_run_dirs
  stop_by_pid_file "backend"
  stop_port_process "${HAICI_BACKEND_PORT}" "backend API"

  local py out_log err_log
  py="$(resolve_python)"
  out_log="${LOG_DIR}/backend.out.log"
  err_log="${LOG_DIR}/backend.err.log"

  local -a uvicorn_args=(
    -m uvicorn app.main:app
    --host "${HAICI_BIND_HOST}"
    --port "${HAICI_BACKEND_PORT}"
    --timeout-graceful-shutdown 30
    --log-level info
  )
  if [[ "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
    uvicorn_args+=(--workers "${UVICORN_WORKERS}")
  fi

  log_info "START backend http://${HAICI_BIND_HOST}:${HAICI_BACKEND_PORT} (mode=${HAICI_DEPLOY_MODE}) ..."
  log_event "智能客服-部署" "_lib.start_backend" "uvicorn" "硬编执行" "启动" \
    "host=${HAICI_BIND_HOST}" "port=${HAICI_BACKEND_PORT}" "workers=${UVICORN_WORKERS}"

  (
    cd "${BACKEND_DIR}"
    export CHROMA_PERSIST_PATH="${HAICI_CHROMA_PERSIST_PATH}"
    nohup "${py}" "${uvicorn_args[@]}" >> "${out_log}" 2>> "${err_log}" &
    echo $! > "${RUN_DIR}/backend.pid"
  )

  sleep 2
  local listen_pid
  if listen_pid="$(get_port_pid "${HAICI_BACKEND_PORT}" 2>/dev/null || true)"; then
    save_pid_file "backend" "${listen_pid}"
  fi

  local health_url="http://127.0.0.1:${HAICI_BACKEND_PORT}/health"
  wait_http_ok "${health_url}" "${HAICI_HEALTH_TIMEOUT_SEC}" "backend API" || {
    log_err "后端启动失败，最近日志:"
    tail -n 30 "${err_log}" 2>/dev/null || true
    return 1
  }
}

start_frontend_dev() {
  ensure_run_dirs
  stop_by_pid_file "frontend"
  stop_port_process "${HAICI_FRONTEND_PORT}" "frontend Vite"

  local npm_bin out_log err_log
  npm_bin="$(resolve_npm)"
  out_log="${LOG_DIR}/frontend.out.log"
  err_log="${LOG_DIR}/frontend.err.log"

  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    log_info "INSTALL frontend npm install ..."
    (cd "${FRONTEND_DIR}" && "${npm_bin}" ci 2>/dev/null || "${npm_bin}" install)
  fi

  log_info "START frontend dev http://127.0.0.1:${HAICI_FRONTEND_PORT} ..."
  (
    cd "${FRONTEND_DIR}"
    nohup "${npm_bin}" run dev -- --host 127.0.0.1 --port "${HAICI_FRONTEND_PORT}" --strictPort \
      >> "${out_log}" 2>> "${err_log}" &
    echo $! > "${RUN_DIR}/frontend.pid"
  )

  wait_http_ok "http://127.0.0.1:${HAICI_FRONTEND_PORT}/" 60 "frontend Vite" || {
    log_err "前端启动失败，最近日志:"
    tail -n 20 "${err_log}" 2>/dev/null || true
    return 1
  }
}

stop_app_processes() {
  stop_by_pid_file "frontend"
  stop_by_pid_file "backend"
  stop_port_process "${HAICI_FRONTEND_PORT}" "frontend Vite"
  stop_port_process "${HAICI_BACKEND_PORT}" "backend API"
}

show_service_status() {
  echo ""
  echo "========== HaiChi 服务状态 (mode=${HAICI_DEPLOY_MODE}) =========="
  local item name port pid
  for item in "MySQL:${HAICI_MYSQL_PORT}" "Chroma:${HAICI_CHROMA_PORT}" "Backend:${HAICI_BACKEND_PORT}" "Frontend:${HAICI_FRONTEND_PORT}"; do
    name="${item%%:*}"
    port="${item##*:}"
    if [[ "${name}" == "Frontend" && "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
      echo "  Frontend   : (prod 模式由 backend 静态托管 dist/)"
      continue
    fi
    if [[ "${name}" == "Chroma" && -n "${HAICI_CHROMA_PERSIST_PATH}" ]]; then
      echo "  Chroma     : 本地持久化 ${HAICI_CHROMA_PERSIST_PATH}"
      continue
    fi
    if pid="$(get_port_pid "${port}" 2>/dev/null || true)"; then
      printf "  %-10s :%-5s running (PID %s)\n" "${name}" "${port}" "${pid}"
    else
      printf "  %-10s :%-5s stopped\n" "${name}" "${port}"
    fi
  done
  if [[ "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
    echo "  UI/API:    http://${HAICI_BIND_HOST}:${HAICI_BACKEND_PORT}/  (admin / admin)"
  else
    echo "  UI:        http://127.0.0.1:${HAICI_FRONTEND_PORT}/  (admin / admin)"
    echo "  API:       http://127.0.0.1:${HAICI_BACKEND_PORT}/docs"
  fi
  echo "  Logs:      ${LOG_DIR}/"
  echo "==============================================================="
}

parse_common_flags() {
  SKIP_DOCKER=false
  SKIP_BACKEND=false
  SKIP_FRONTEND=false
  KEEP_DOCKER=false
  REBUILD_FRONTEND=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-docker)    SKIP_DOCKER=true ;;
      --skip-backend)   SKIP_BACKEND=true ;;
      --skip-frontend)  SKIP_FRONTEND=true ;;
      --keep-docker)    KEEP_DOCKER=true ;;
      --prod)           HAICI_DEPLOY_MODE=prod; HAICI_BIND_HOST="${HAICI_BIND_HOST:-0.0.0.0}" ;;
      --dev)            HAICI_DEPLOY_MODE=dev; HAICI_BIND_HOST="${HAICI_BIND_HOST:-127.0.0.1}" ;;
      --rebuild-frontend) REBUILD_FRONTEND=true ;;
      -h|--help)
        cat <<'EOF'
HaiChi 服务管理通用参数:
  --skip-docker       跳过 Docker 中间件启停
  --skip-backend      跳过后端
  --skip-frontend     跳过前端（dev 模式）
  --keep-docker       停止/重启时不操作 Docker
  --prod              生产模式：构建 dist + 多 worker 后端，静态由 backend 托管
  --dev               开发模式：Vite dev + 单 worker 后端（默认）
  --rebuild-frontend  强制重新 npm run build
  -h, --help          显示帮助

环境变量:
  HAICI_DEPLOY_MODE, HAICI_BIND_HOST, HAICI_BACKEND_PORT, HAICI_FRONTEND_PORT
  HAICI_MYSQL_PORT / MYSQL_PORT, CHROMA_PERSIST_PATH, UVICORN_WORKERS
EOF
        exit 0
        ;;
      *)
        log_err "未知参数: $1"
        exit 2
        ;;
    esac
    shift
  done
}

init_haici_lib() {
  ensure_run_dirs
  load_env_files
}
