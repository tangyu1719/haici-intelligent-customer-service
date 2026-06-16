#!/usr/bin/env bash
# HaiChi 一键启动（生产级）
# 用法: ./scripts/start.sh [--prod|--dev] [--skip-docker] [--skip-backend] [--skip-frontend] [--rebuild-frontend]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

main() {
  parse_common_flags "$@"
  init_haici_lib
  acquire_service_lock
  trap 'release_service_lock' EXIT

  log_info ">>> HaiChi 启动服务 (mode=${HAICI_DEPLOY_MODE})"

  if [[ "${SKIP_DOCKER}" != "true" ]]; then
    start_docker_middleware || true
  else
    log_info "SKIP  Docker 中间件 (--skip-docker)"
  fi

  if ! preflight_middleware; then
    log_err "中间件预检失败。本地无 Docker 时可: export CHROMA_PERSIST_PATH=${RUN_DIR}/chroma_persist MYSQL_PORT=3306"
    exit 1
  fi

  if [[ "${HAICI_DEPLOY_MODE}" == "prod" ]]; then
    build_frontend_prod "${REBUILD_FRONTEND}"
    SKIP_FRONTEND=true
  fi

  if [[ "${SKIP_BACKEND}" != "true" ]]; then
    start_backend
  else
    log_info "SKIP  后端 (--skip-backend)"
  fi

  if [[ "${SKIP_FRONTEND}" != "true" && "${HAICI_DEPLOY_MODE}" == "dev" ]]; then
    start_frontend_dev
  elif [[ "${SKIP_FRONTEND}" == "true" && "${HAICI_DEPLOY_MODE}" == "dev" ]]; then
    log_info "SKIP  前端 (--skip-frontend)"
  fi

  show_service_status
  log_event "智能客服-部署" "start.sh" "all" "硬编执行" "完成" "ok=true" "mode=${HAICI_DEPLOY_MODE}"
}

main "$@"
