#!/usr/bin/env bash
# HaiChi 一键停止（生产级：SIGTERM 优雅退出 + 端口兜底）
# 用法: ./scripts/stop.sh [--keep-docker] [--skip-docker]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

main() {
  parse_common_flags "$@"
  init_haici_lib
  acquire_service_lock
  trap 'release_service_lock' EXIT

  log_info ">>> HaiChi 停止服务"

  stop_app_processes

  if [[ "${SKIP_DOCKER}" != "true" && "${KEEP_DOCKER}" != "true" ]]; then
    stop_docker_middleware
  else
    log_info "KEEP  Docker 中间件仍在运行 (--keep-docker / --skip-docker)"
  fi

  show_service_status
  log_event "智能客服-部署" "stop.sh" "all" "硬编执行" "完成" "ok=true"
}

main "$@"
