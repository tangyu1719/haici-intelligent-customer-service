#!/bin/bash
echo "=========================================="
echo "  电商智能客服系统部署"
echo "=========================================="

echo "[1/5] 停止旧容器..."
docker-compose down 2>/dev/null

echo "[2/5] 构建镜像..."
docker-compose build --no-cache

echo "[3/5] 启动服务..."
docker-compose up -d

echo "[4/5] 等待服务就绪..."
sleep 30

echo "[5/5] 检查服务状态..."
docker-compose ps

echo ""
echo "=========================================="
echo "  部署完成"
echo "=========================================="
echo ""
echo "API地址: http://localhost:8000"
echo "健康检查: http://localhost:8000/health"
echo "工具列表: http://localhost:8000/tools"
echo ""
echo "导入知识库:"
echo "  docker exec -it rag-app python import_kb.py"
echo ""
echo "运行评测:"
echo "  docker exec -it rag-app python run_eval.py"
echo ""
echo "=========================================="
