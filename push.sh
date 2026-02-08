#!/bin/bash
#
# D2C Unified Push Script
# Supports Git, Docker Hub, and GHCR pushes
#
# Usage:
#   ./push.sh              # Interactive menu
#   ./push.sh quick       # Quick push (add+commit+push)
#   ./push.sh docker      # Build & push Docker images
#   ./push.sh tag "v1.0.0"  # Create tag
#
# SSH 配置:
#   默认使用 SSH 方式推送到 GitHub（无需输入密码）
#   如需使用 HTTPS，请设置: export USE_HTTPS=1
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Configuration
REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_step() { echo -e "${CYAN}[STEP]${NC} $1"; }
print_docker() { echo -e "${MAGENTA}[DOCKER]${NC} $1"; }

# Get image name from docker-compose.yml
get_image_name() {
    local compose_file="$1"
    if [ -f "$compose_file" ]; then
        grep -E '^\s*image:' "$compose_file" | head -1 | awk '{print $2}' | tr -d ' '
    fi
}

# Build Docker image
build_image() {
    local tag="$1"
    print_docker "Building image: $tag"
    
    if [ -f "$DOCKERFILE" ]; then
        docker build -t "$tag" .
        print_success "Built: $tag"
    else
        print_error "Dockerfile not found: $DOCKERFILE"
        return 1
    fi
}

# Push to Docker Hub
push_dockerhub() {
    local image="$1"
    local tag="${2:-latest}"
    local full_tag="$image:$tag"
    
    print_docker "Pushing to Docker Hub: $full_tag"
    docker tag "$image:latest" "$full_tag"
    docker push "$full_tag"
    print_success "Pushed: $full_tag"
}

# Push to GHCR
push_ghcr() {
    local image="$1"
    local tag="${2:-latest}"
    local full_tag="ghcr.io/$image:$tag"
    
    print_docker "Pushing to GHCR: $full_tag"
    docker tag "$image:latest" "$full_tag"
    docker push "$full_tag"
    print_success "Pushed: $full_tag"
}

# Push to all registries
push_all_registries() {
    local image_name="$1"
    local tag="${2:-latest}"
    
    echo ""
    print_step "Pushing to all registries..."
    echo ""
    
    # Docker Hub (hub.docker.com)
    push_dockerhub "$image_name" "$tag"
    echo ""
    
    # GHCR (GitHub Container Registry)
    push_ghcr "$image_name" "$tag"
    echo ""
    
    print_success "All images pushed successfully!"
}

# Get git remote URL (convert HTTPS to SSH if needed)
get_git_remote() {
    local remote_url="${USE_HTTPS:-0}"
    
    if [ "$remote_url" = "1" ]; then
        git remote get-url origin 2>/dev/null || echo ""
    else
        # Convert HTTPS to SSH
        local https_url=$(git remote get-url origin 2>/dev/null || echo "")
        if [ -n "$https_url" ]; then
            echo "$https_url" | sed 's|https://github.com/|git@github.com:|;s|/$||'
        fi
    fi
}

# Set SSH remote URL automatically
set_ssh_remote() {
    local current_url=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -n "$current_url" ] && echo "$current_url" | grep -q "https://"; then
        local ssh_url=$(echo "$current_url" | sed 's|https://github.com/|git@github.com:|;s|/$||')
        print_info "转换 remote URL 为 SSH: $ssh_url"
        git remote set-url origin "$ssh_url"
    fi
}

# Git functions
git_status() {
    print_step "Git Status"
    git status
}

git_add() {
    print_step "Staging Changes"
    git add -A
    print_success "Changes staged"
    git status --short
}

git_commit() {
    print_step "Commit Changes"
    
    if git diff --cached --quiet; then
        print_warning "No staged changes"
        return
    fi
    
    echo "Select commit type:"
    echo "  1) feat: New feature"
    echo "  2) fix: Bug fix"
    echo "  3) docs: Documentation"
    echo "  4) style: Code style"
    echo "  5) refactor: Refactoring"
    echo "  6) chore: Maintenance"
    echo "  0) Custom message"
    echo ""
    read -p "选择类型 [0-6]: " type
    
    read -p "输入提交信息: " message
    
    local prefix=""
    case $type in
        1) prefix="feat: " ;;
        2) prefix="fix: " ;;
        3) prefix="docs: " ;;
        4) prefix="style: " ;;
        5) prefix="refactor: " ;;
        6) prefix="chore: " ;;
        *) prefix="" ;;
    esac
    
    git commit -m "${prefix}${message}"
    print_success "Committed: ${prefix}${message}"
}

git_push() {
    print_step "Pushing to GitHub"
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    local remote_url=$(get_git_remote)
    if [ -n "$remote_url" ]; then
        print_info "Using SSH: $remote_url"
    fi
    git push origin "$BRANCH"
    print_success "Pushed to $BRANCH"
}

git_tag() {
    local version="$1"
    
    # 自动设置 SSH remote
    set_ssh_remote
    
    if [ -z "$version" ]; then
        read -p "输入版本号 (如 v1.0.0): " version
    fi
    
    if [ -z "$version" ]; then
        print_error "版本号不能为空"
        return 1
    fi
    
    print_step "Creating tag: $version"
    
    # 检查本地标签是否存在，存在则删除
    if git tag | grep -q "^${version}$"; then
        print_warning "本地标签 $version 已存在，正在删除..."
        git tag -d "$version" 2>/dev/null || true
    fi
    
    # 检查远程标签是否存在，存在则删除
    if git ls-remote --tags origin 2>/dev/null | grep -q "refs/tags/${version}$"; then
        print_warning "远程标签 $version 已存在，正在删除..."
        git push origin :refs/tags/"$version" 2>/dev/null || true
    fi
    
    # 创建新标签
    git tag -a "$version" -m "Release $version"
    
    local remote_url=$(get_git_remote)
    if [ -n "$remote_url" ]; then
        print_info "Using SSH: $remote_url"
    fi
    
    # 推送标签
    git push origin "$version"
    
    # 同时推送当前分支代码
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    print_step "Pushing branch: $BRANCH"
    git push origin "$BRANCH"
    
    print_success "Tag pushed: $version"
    print_success "Branch pushed: $BRANCH"
    
    echo ""
    echo "Build triggers:"
    echo "  - Docker Hub: https://hub.docker.com/r/$(grep -E 'image:' docker-compose.yml | head -1 | awk '{print $2}' | tr -d ' ' | cut -d'/' -f2)/tags"
    echo "  - GitHub: https://github.com/$(git remote get-url origin | sed 's/.*github.com[\/:]//;s/.git$//')/actions"
}

git_history() {
    print_step "Recent Commits"
    git log --oneline -10
}

quick_push() {
    local msg="$1"
    
    if [ -z "$msg" ]; then
        msg="Update $(date +%Y-%m-%d-%H:%M)"
    fi
    
    echo ""
    print_step "Quick Push"
    echo "Commit: $msg"
    echo ""
    
    git add -A
    git commit -m "$msg"
    print_success "Committed"
    
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    git push origin "$BRANCH"
    print_success "Pushed to $BRANCH"
    
    echo ""
    print_success "Done!"
}

docker_menu() {
    local image_name=$(get_image_name "$COMPOSE_FILE")
    
    if [ -z "$image_name" ]; then
        print_error "无法从 $COMPOSE_FILE 获取镜像名称"
        return 1
    fi
    
    echo ""
    echo "Docker Image Push"
    echo "================="
    echo "Image: $image_name"
    echo ""
    echo "  1) Build image"
    echo "  2) Push to Docker Hub"
    echo "  3) Push to GHCR"
    echo "  4) Push to all registries"
    echo "  5) Build & push all"
    echo ""
    echo "  q) Back to main menu"
    echo ""
    read -p "选择操作 [1-5, q]: " choice
    
    case $choice in
        1)
            read -p "输入标签 [latest]: " tag
            tag="${tag:-latest}"
            build_image "$image_name:$tag"
            ;;
        2)
            read -p "输入标签 [latest]: " tag
            tag="${tag:-latest}"
            push_dockerhub "$image_name" "$tag"
            ;;
        3)
            read -p "输入标签 [latest]: " tag
            tag="${tag:-latest}"
            push_ghcr "$image_name" "$tag"
            ;;
        4)
            read -p "输入标签 [latest]: " tag
            tag="${tag:-latest}"
            push_all_registries "$image_name" "$tag"
            ;;
        5)
            read -p "输入标签 [latest]: " tag
            tag="${tag:-latest}"
            build_image "$image_name:$tag"
            echo ""
            push_all_registries "$image_name" "$tag"
            ;;
        q|Q)
            return
            ;;
        *)
            print_error "无效选择"
            ;;
    esac
}

show_menu() {
    clear
    echo "================================"
    echo "      D2C Unified Push Tool"
    echo "================================"
    echo ""
    echo "Git 操作:"
    echo "  1) 查看状态 (git status)"
    echo "  2) 暂存所有 (git add)"
    echo "  3) 提交 (git commit)"
    echo "  4) 推送到 GitHub (git push)"
    echo "  5) 创建标签 (git tag)"
    echo "  6) 查看提交历史"
    echo "  7) 一键推送 (add+commit+push)"
    echo ""
    echo "Docker 操作:"
    echo "  8) Docker 镜像推送菜单"
    echo ""
    echo "  q) 退出"
    echo ""
    echo "================================"
}

main() {
    local mode="$1"
    
    case "$mode" in
        quick)
            quick_push "$2"
            ;;
        docker)
            docker_menu
            ;;
        tag)
            git_tag "$2"
            ;;
        "")
            # Interactive mode
            check_git_repo
            
            while true; do
                show_menu
                read -p "选择操作 [1-8, q]: " choice
                
                case "$choice" in
                    1) git_status; echo ""; read -p "Press Enter..." ;;
                    2) git_add; echo ""; read -p "Press Enter..." ;;
                    3) git_commit; echo ""; read -p "Press Enter..." ;;
                    4) git_push; echo ""; read -p "Press Enter..." ;;
                    5) git_tag; echo ""; read -p "Press Enter..." ;;
                    6) git_history; echo ""; read -p "Press Enter..." ;;
                    7) quick_push; echo ""; read -p "Press Enter..." ;;
                    8) docker_menu; echo ""; read -p "Press Enter..." ;;
                    q|Q) exit 0 ;;
                    *) print_error "无效选择"; sleep 1 ;;
                esac
            done
            ;;
        *)
            echo "Usage: $0 [quick|docker|tag] [args]"
            echo ""
            echo "Commands:"
            echo "  (none)    - Interactive menu"
            echo "  quick     - Quick push with optional message"
            echo "  docker    - Docker push menu"
            echo "  tag v1.0.0 - Create and push tag"
            exit 1
            ;;
    esac
}

check_git_repo() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not a git repository!"
        exit 1
    fi
    REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [ -z "$REMOTE_URL" ]; then
        print_error "No GitHub remote configured!"
        exit 1
    fi
    print_info "Remote: $REMOTE_URL"
}

main "$@"
