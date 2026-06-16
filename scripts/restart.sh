#!/usr/bin/env bash
# HaiCi 一键重启（生产级）
# 用法: ./scripts/restart.sh [--prod|--dev] [--keep-docker] [--skip-docker] [--rebuild-frontend]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

main() {
  parse_common_flags "$@"
  init_haici_lib
  acquire_service_lock
  trap 'release_service_lock' EXIT

  log_info ">>> HaiCi 重启服务 (mode=${HAICI_DEPLOY_MODE})"

  stop_app_processes
  sleep 2

  if [[ "${SKIP_DOCKER}" != "true" && "${KEEP_DOCKER}" != "true" ]]; then
    stop_docker_middleware
    sleep 2
    start_docker_middleware || true
  elif [[ "${SKIP_DOCKER}" != "true" && "${KEEP_DOCKER}" == "true" ]]; then
    log_info "KEEP  Docker 未重启 (--keep-docker)"
  else
    log_info "SKIP  Docker (--skip-docker)"
  fi

  if ! preflight_middleware; then
    log_err "中间件预检失败，重启中止"
    exit 1
  fi

  if [[ "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
    build_frontend_prod "${REBUILD_FRONTEND}"
    SKIP_FRONTEND=true
  fi

  if [[ "${SKIP_BACKEND}" != "true" ]]; then
    start_backend
  fi

  if [[ "${SKIP_FRONTEND}" != "true" && "${HAICI_DEPLOY_MODE}" == "dev" ]]; then
    start_frontend_dev
  fi

  show_service_status
  log_event "智能客服-部署" "restart.sh" "all" "硬编执行" "完成" "ok=true" "mode=${HAICI_DEPLOY_MODE}"
}

main "$@"
