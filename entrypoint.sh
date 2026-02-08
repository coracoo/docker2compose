#!/bin/bash

# D2C 容器入口脚本
# 处理配置初始化和应用启动

set -e

# 颜色输出
print_info() {
    echo -e "\033[1;34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[1;32m[SUCCESS]\033[0m $1"
}

print_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
}

print_warning() {
    echo -e "\033[1;33m[WARNING]\033[0m $1"
}

# 获取当前用户
CURRENT_USER=$(id -un)
CURRENT_UID=$(id -u)
print_info "当前用户: $CURRENT_USER (UID: $CURRENT_UID)"

# 检查 Docker socket
if [ ! -S "/var/run/docker.sock" ]; then
    print_error "Docker socket 未挂载！"
    print_error "请确保启动时使用了 -v /var/run/docker.sock:/var/run/docker.sock"
    exit 1
fi

# 检查 Docker 连接
print_info "检查 Docker 连接..."
if docker version > /dev/null 2>&1; then
    DOCKER_VERSION=$(docker version --format "{{.Server.Version}}" 2>/dev/null || echo "unknown")
    print_success "Docker 连接正常 (版本: $DOCKER_VERSION)"
else
    print_error "无法连接到 Docker daemon"
    print_warning "如果您使用非 root 用户运行，请确保已配置 Docker 权限"
    exit 1
fi

# 确保配置目录存在
mkdir -p /app/config /app/compose /app/logs

# 加载或创建配置
export CONFIG_FILE="/app/config/config.json"

if [ -f "$CONFIG_FILE" ]; then
    print_info "加载现有配置: $CONFIG_FILE"
else
    print_info "创建默认配置..."
    python3 << 'PYTHON_EOF'
import json
import os

config = {
    "// 配置说明": "以下是D2C的配置选项",
    "// CRON": "定时执行配置: '0 2 * * *'(每天凌晨2点), 'manual'(手动), 'once'(执行一次)",
    "CRON": os.environ.get("CRON", "0 2 * * *"),
    "// NETWORK": "控制bridge网络配置的显示方式: true(显示) 或 false(隐藏)",
    "NETWORK": os.environ.get("NETWORK", "true"),
    "// SHOW_HEALTHCHECK": "控制healthcheck配置的显示方式: true(显示) 或 false(隐藏)",
    "SHOW_HEALTHCHECK": os.environ.get("SHOW_HEALTHCHECK", "true"),
    "// SHOW_CAP_ADD": "控制cap_add配置的显示方式: true(显示) 或 false(隐藏)",
    "SHOW_CAP_ADD": os.environ.get("SHOW_CAP_ADD", "true"),
    "// SHOW_COMMAND": "控制command配置的显示方式: true(显示) 或 false(隐藏)",
    "SHOW_COMMAND": os.environ.get("SHOW_COMMAND", "true"),
    "// SHOW_ENTRYPOINT": "控制entrypoint配置的显示方式: true(显示) 或 false(隐藏)",
    "SHOW_ENTRYPOINT": os.environ.get("SHOW_ENTRYPOINT", "true"),
    "// ENV_FILTER_KEYWORDS": "环境变量过滤关键词，逗号分隔",
    "ENV_FILTER_KEYWORDS": os.environ.get("ENV_FILTER_KEYWORDS", ""),
    "// TZ": "时区设置,如Asia/Shanghai、Europe/London等",
    "TZ": os.environ.get("TZ", "Asia/Shanghai")
}

with open("/app/config/config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("默认配置已创建")
PYTHON_EOF
fi

# 读取配置
CRON=$(python3 -c "
import json
import os
config_file = os.environ.get('CONFIG_FILE', '/app/config/config.json')
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
    print(config.get('CRON', 'once'))
except:
    print('once')
")

TZ=$(python3 -c "
import json
import os
config_file = os.environ.get('CONFIG_FILE', '/app/config/config.json')
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
    print(config.get('TZ', 'Asia/Shanghai'))
except:
    print('Asia/Shanghai')
")

print_info "时区设置: $TZ"
print_info "CRON 设置: $CRON"

# 设置时区（如果可能）
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    export TZ="$TZ"
    print_info "时区已设置: $(date)"
else
    print_warning "时区文件不存在，使用系统默认时区"
fi

# 如果 CRON 不是 once 或 manual，启动后台调度器
if [ "$CRON" != "once" ] && [ "$CRON" != "manual" ]; then
    print_info "启动后台调度器 (CRON: $CRON)..."
    
    # 先检查是否已有调度器在运行
    SCHEDULER_STATUS=$(python3 /app/scheduler_service.py status 2>/dev/null)
    print_info "当前调度器状态: $SCHEDULER_STATUS"
    
    if echo "$SCHEDULER_STATUS" | grep -q '"running": true'; then
        print_warning "调度器已在运行，跳过启动"
    else
        # 清理可能存在的旧 PID 文件
        rm -f /tmp/d2c_scheduler.pid /tmp/d2c_scheduler.lock
        
        print_info "正在启动调度器进程..."
        # 使用 nohup 确保调度器在后台持续运行
        nohup python3 /app/scheduler_service.py start > /app/logs/scheduler.log 2>&1 &
        SCHEDULER_PID=$!
        print_info "调度器进程 PID: $SCHEDULER_PID"
        
        # 等待调度器初始化
        sleep 3
        
        # 检查调度器是否正常运行
        SCHEDULER_STARTED=false
        for i in 1 2 3; do
            if python3 /app/scheduler_service.py status 2>/dev/null | grep -q '"running": true'; then
                print_success "调度器已启动"
                SCHEDULER_STARTED=true
                break
            fi
            print_warning "等待调度器启动... ($i/3)"
            sleep 1
        done
        
        if [ "$SCHEDULER_STARTED" = false ]; then
            print_error "调度器启动失败，查看日志:"
            cat /app/logs/scheduler.log 2>/dev/null || echo "日志文件不存在"
        fi
    fi
    
    # 显示调度器日志最后几行
    if [ -f /app/logs/scheduler.log ]; then
        print_info "调度器日志:"
        tail -n 10 /app/logs/scheduler.log
    fi
fi

print_success "D2C 初始化完成"
print_info "启动 Web 服务..."
print_info "========================================"

# 启动 Gunicorn（作为前台进程）
# 注意：--access-logfile /dev/null 禁用访问日志，避免健康检查日志刷屏
exec gunicorn \
    -w 1 \
    --threads 4 \
    -b 0.0.0.0:5000 \
    --timeout 120 \
    --access-logfile /dev/null \
    --error-logfile - \
    --capture-output \
    --enable-stdio-inheritance \
    web.app:app
