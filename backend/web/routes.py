#!/usr/bin/env python3
"""
D2C Web Routes
Flask 路由定义
"""

import json
import os
import glob
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, render_template, send_from_directory
from flask_login import current_user

from config import ConfigManager, D2CConfig
from converter import (
    convert_container_to_service, 
    group_containers_by_network,
    generate_compose_config
)
# 调度器服务通过 scheduler_service.py 独立进程管理
from utils.docker_utils import get_containers, get_networks, check_docker_connection
from utils.security import validate_path, sanitize_filename, SecurityError
from utils.yaml_utils import dump_compose_config
from filters import get_label_filter_stats
from utils.logger import get_logger
from .auth import require_auth

logger = get_logger()

# 蓝图
main_bp = Blueprint('main', __name__)
api_bp = Blueprint('api', __name__)

# 为 API 蓝图添加认证检查
@api_bp.before_request
def check_auth():
    """API 请求认证检查"""
    from flask import request
    
    # 不需要认证的路径
    exempt_paths = [
        '/api/auth/',
        '/health',
    ]
    
    # 检查是否需要跳过认证
    for path in exempt_paths:
        if request.path.startswith(path):
            return None
    
    # 检查是否已登录
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': '请先登录', 'code': 'UNAUTHORIZED'}), 401
    
    return None


# =============================================================================
# 页面路由
# =============================================================================

@main_bp.route('/')
def index():
    """首页"""
    return render_template('index.html')


@main_bp.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    """Chrome DevTools 配置请求 - 返回空响应"""
    return jsonify({})


@main_bp.route('/health')
def health():
    """健康检查"""
    connected, message = check_docker_connection()
    
    if connected:
        try:
            containers = get_containers()
            return jsonify({
                'status': 'healthy',
                'docker_connected': True,
                'container_count': len(containers),
                'message': message
            })
        except Exception as e:
            return jsonify({
                'status': 'unhealthy',
                'docker_connected': True,
                'error': str(e)
            }), 503
    else:
        return jsonify({
            'status': 'unhealthy',
            'docker_connected': False,
            'message': message
        }), 503


# =============================================================================
# API 路由 - 容器管理
# =============================================================================

@api_bp.route('/containers')
def get_containers_api():
    """获取容器列表"""
    try:
        containers = get_containers()
        networks = get_networks()
        groups = group_containers_by_network(containers, networks)
        
        result = []
        for i, group in enumerate(groups):
            group_containers = []
            for container_id in group:
                container = next(
                    (c for c in containers if c.get('Id') == container_id), 
                    None
                )
                if container:
                    group_containers.append({
                        'id': container.get('Id', '')[:12],
                        'name': container.get('Name', '').lstrip('/'),
                        'image': container.get('Config', {}).get('Image', ''),
                        'status': 'running' if container.get('State', {}).get('Running') else 'stopped',
                        'network_mode': container.get('HostConfig', {}).get('NetworkMode', 'default'),
                    })
            
            if group_containers:
                result.append({
                    'id': f'group_{i}',
                    'name': group_containers[0]['name'] if len(group_containers) == 1 else f"{group_containers[0]['name']}-group",
                    'type': 'single' if len(group_containers) == 1 else 'group',
                    'containers': group_containers,
                    'count': len(group_containers),
                })
        
        # 按分组名称字母排序
        result.sort(key=lambda x: x['name'].lower())
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/containers/<container_id>/compose')
def get_container_compose(container_id: str):
    """获取单个容器的 Compose 配置"""
    try:
        containers = get_containers()
        networks = get_networks()
        
        # 查找容器
        container = None
        for c in containers:
            cid = c.get('Id', '')
            if cid.startswith(container_id) or cid[:12] == container_id:
                container = c
                break
        
        if not container:
            return jsonify({'success': False, 'error': '容器未找到'}), 404
        
        # 加载配置
        config_manager = ConfigManager()
        config = config_manager.load()
        
        # 转换为服务配置
        service = convert_container_to_service(container, config, networks)
        
        # 生成 Compose 配置
        compose_config = {
            'services': {
                container.get('Name', '').lstrip('/').replace('-', '_'): service
            }
        }
        
        # 转换为 YAML
        yaml_content = dump_compose_config(compose_config)
        
        return jsonify({
            'success': True,
            'data': {
                'yaml': yaml_content,
                'config': compose_config,
                'container_name': container.get('Name', '').lstrip('/')
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/compose', methods=['POST'])
@api_bp.route('/compose/generate', methods=['POST'])
def generate_compose():
    """生成 Compose 配置"""
    try:
        data = request.get_json() or {}
        container_ids = data.get('container_ids', [])
        
        if not container_ids:
            return jsonify({'success': False, 'error': '请选择至少一个容器'}), 400
        
        # 获取容器信息
        all_containers = get_containers()
        networks = get_networks()
        
        # 过滤选中的容器
        selected = []
        for cid in container_ids:
            for c in all_containers:
                if c.get('Id', '').startswith(cid) or c.get('Id', '')[:12] == cid:
                    selected.append(c)
                    break
        
        if not selected:
            return jsonify({'success': False, 'error': '未找到指定的容器'}), 404
        
        # 加载配置
        config_manager = ConfigManager()
        config = config_manager.load()
        
        # 生成 Compose 配置
        compose_config = generate_compose_config(selected, networks, config)
        
        # 转换为 YAML
        yaml_content = dump_compose_config(compose_config)
        
        return jsonify({
            'success': True,
            'data': {
                'yaml': yaml_content,
                'config': compose_config
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/generate-all-compose', methods=['POST'])
def generate_all_compose():
    """生成所有容器的 Compose 配置"""
    try:
        # 获取所有容器
        all_containers = get_containers()
        networks = get_networks()
        
        if not all_containers:
            return jsonify({'success': False, 'error': '未找到任何容器'}), 404
        
        # 加载配置
        config_manager = ConfigManager()
        config = config_manager.load()
        
        # 生成所有容器的 Compose 配置
        compose_config = generate_compose_config(all_containers, networks, config)
        
        # 转换为 YAML
        yaml_content = dump_compose_config(compose_config)
        
        # 保存到文件
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M")
        output_dir = f"/app/compose/{timestamp}"
        os.makedirs(output_dir, exist_ok=True)
        
        output_file = os.path.join(output_dir, 'all-containers-compose.yaml')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        return jsonify({
            'success': True,
            'message': f'全量 Compose 文件已生成',
            'data': {
                'yaml': yaml_content,
                'filepath': output_file
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# API 路由 - 文件管理
# =============================================================================

@api_bp.route('/files')
def list_files():
    """列出 compose 目录中的文件"""
    try:
        compose_dir = '/app/compose'
        
        result = {
            'root': [],
            'folders': {}
        }
        
        if os.path.exists(compose_dir):
            # 根目录文件
            for item in os.listdir(compose_dir):
                item_path = os.path.join(compose_dir, item)
                
                if os.path.isfile(item_path) and item.endswith(('.yaml', '.yml')):
                    stat = os.stat(item_path)
                    result['root'].append({
                        'name': item,
                        'path': item_path,
                        'modified': stat.st_mtime,
                        'size': stat.st_size,
                    })
                
                elif os.path.isdir(item_path):
                    # 子目录
                    files = []
                    for subitem in os.listdir(item_path):
                        if subitem.endswith(('.yaml', '.yml')):
                            subpath = os.path.join(item_path, subitem)
                            if os.path.isfile(subpath):
                                stat = os.stat(subpath)
                                files.append({
                                    'name': subitem,
                                    'path': subpath,
                                    'modified': stat.st_mtime,
                                    'size': stat.st_size,
                                })
                    
                    if files:
                        files.sort(key=lambda x: x['name'].lower())
                        stat = os.stat(item_path)
                        result['folders'][item] = {
                            'name': item,
                            'path': item_path,
                            'modified': stat.st_mtime,
                            'files': files,
                        }
            
            # 根目录文件按名字排序
            result['root'].sort(key=lambda x: x['name'].lower())
            
            # 文件夹列表按修改时间倒序排序（最新的排在前面）
            # 使用列表而不是字典，确保顺序在 JSON 序列化中不被改变
            folder_items = list(result['folders'].items())
            folder_items.sort(key=lambda x: x[1]['modified'], reverse=True)
            result['folders'] = [item[1] for item in folder_items]
        
        return jsonify({'success': True, 'data': result})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/files/content', methods=['POST'])
@api_bp.route('/file-content', methods=['POST'])  # 兼容旧版API
def get_file_content():
    """获取文件内容"""
    try:
        data = request.get_json() or {}
        file_path = data.get('path', '')
        
        if not file_path:
            return jsonify({'success': False, 'error': '文件路径不能为空'}), 400
        
        # 验证路径安全
        try:
            validate_path(file_path, ['/app/compose'])
        except SecurityError as e:
            return jsonify({'success': False, 'error': str(e)}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': '文件不存在'}), 404
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            'success': True,
            'data': {
                'content': content,
                'filename': os.path.basename(file_path),
                'path': file_path
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/files/save', methods=['POST'])
def save_file():
    """保存文件"""
    try:
        data = request.get_json() or {}
        file_path = data.get('path', '')
        content = data.get('content', '')
        
        if not file_path:
            return jsonify({'success': False, 'error': '文件路径不能为空'}), 400
        
        # 验证路径安全
        try:
            path = validate_path(file_path, ['/app/compose'])
        except SecurityError as e:
            return jsonify({'success': False, 'error': str(e)}), 403
        
        # 确保目录存在
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # 保存文件
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({
            'success': True,
            'message': f'文件已保存: {file_path}'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/files/delete', methods=['POST'])
@api_bp.route('/delete-file', methods=['POST'])  # 兼容旧版API
def delete_file():
    """删除文件或目录"""
    try:
        data = request.get_json() or {}
        file_path = data.get('path', '') or data.get('file_path', '')  # 兼容旧参数名
        
        if not file_path:
            return jsonify({'success': False, 'error': '文件路径不能为空'}), 400
        
        # 验证路径安全
        try:
            validate_path(file_path, ['/app/compose'])
        except SecurityError as e:
            return jsonify({'success': False, 'error': str(e)}), 403
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': '文件不存在'}), 404
        
        # 删除文件或目录
        if os.path.isfile(file_path):
            os.remove(file_path)
        else:
            import shutil
            shutil.rmtree(file_path)
        
        return jsonify({
            'success': True,
            'message': '删除成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/save-compose', methods=['POST'])  # 兼容旧版API
def save_compose():
    """保存 Compose 文件（兼容旧版API）"""
    try:
        data = request.get_json() or {}
        filename = data.get('filename', '')
        content = data.get('content', '')
        
        if not filename:
            return jsonify({'success': False, 'error': '文件名不能为空'}), 400
        
        if not content:
            return jsonify({'success': False, 'error': '内容不能为空'}), 400
        
        # 清理文件名
        filename = sanitize_filename(filename)
        if not filename.endswith(('.yaml', '.yml')):
            filename += '.yaml'
        
        # 构建完整路径
        file_path = os.path.join('/app/compose', filename)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # 保存文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({
            'success': True,
            'message': f'文件已保存: {filename}',
            'path': file_path
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# API 路由 - 配置管理
# =============================================================================

@api_bp.route('/settings', methods=['GET'])
def get_settings():
    """获取配置"""
    try:
        config_manager = ConfigManager()
        config = config_manager.load()
        
        return jsonify({
            'success': True,
            'data': {
                'CRON': config.cron,
                'NETWORK': config.network,
                'SHOW_HEALTHCHECK': config.show_healthcheck,
                'SHOW_CAP_ADD': config.show_cap_add,
                'SHOW_COMMAND': config.show_command,
                'SHOW_ENTRYPOINT': config.show_entrypoint,
                'ENV_FILTER_KEYWORDS': config.env_filter_keywords,
                'TZ': config.timezone,
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/settings', methods=['POST'])
def save_settings():
    """保存配置并应用"""
    try:
        data = request.get_json() or {}
        settings = data.get('settings', {})
        
        # 创建配置对象（自动验证）
        config = D2CConfig.model_validate({
            'CRON': settings.get('CRON', 'once'),
            'NETWORK': settings.get('NETWORK', 'true'),
            'SHOW_HEALTHCHECK': settings.get('SHOW_HEALTHCHECK', 'true'),
            'SHOW_CAP_ADD': settings.get('SHOW_CAP_ADD', 'true'),
            'SHOW_COMMAND': settings.get('SHOW_COMMAND', 'true'),
            'SHOW_ENTRYPOINT': settings.get('SHOW_ENTRYPOINT', 'true'),
            'ENV_FILTER_KEYWORDS': settings.get('ENV_FILTER_KEYWORDS', ''),
            'TZ': settings.get('TZ', 'Asia/Shanghai'),
        })
        
        # 保存配置
        config_manager = ConfigManager()
        config_manager.save(config)
        
        # 如果调度器正在运行，触发配置重载（热更新）
        reload_result = None
        try:
            import subprocess
            result = subprocess.run(
                ['python3', '/app/scheduler_service.py', 'reload'],
                capture_output=True,
                text=True,
                timeout=5
            )
            reload_result = result.returncode == 0
            if reload_result:
                logger.info("调度器配置已热重载")
            else:
                logger.warning(f"调度器重载失败: {result.stderr}")
        except Exception as e:
            logger.warning(f"触发调度器重载失败: {e}")
            reload_result = False
        
        return jsonify({
            'success': True,
            'message': '配置已保存并应用' if reload_result else '配置已保存',
            'reload_status': reload_result,
            'data': {
                'CRON': config.cron,
                'NETWORK': config.network,
                'SHOW_HEALTHCHECK': config.show_healthcheck,
                'SHOW_CAP_ADD': config.show_cap_add,
                'SHOW_COMMAND': config.show_command,
                'SHOW_ENTRYPOINT': config.show_entrypoint,
                'ENV_FILTER_KEYWORDS': config.env_filter_keywords,
                'TZ': config.timezone,
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# =============================================================================
# API 路由 - 调度器管理
# =============================================================================

@api_bp.route('/scheduler/start', methods=['POST'])
def start_scheduler():
    """启动调度器"""
    try:
        config_manager = ConfigManager()
        config = config_manager.load()
        
        if config.cron == 'once':
            return jsonify({
                'success': False,
                'error': 'CRON 设置为 once，无法启动定时任务'
            }), 400
        
        # 使用调度器服务（后台启动，不阻塞）
        import subprocess
        subprocess.Popen(
            ['python3', '/app/scheduler_service.py', 'start'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        return jsonify({
            'success': True,
            'message': '调度器启动命令已发送'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/stop', methods=['POST'])
def stop_scheduler_api():
    """停止调度器"""
    try:
        import subprocess
        subprocess.run(
            ['python3', '/app/scheduler_service.py', 'stop'],
            capture_output=True
        )
        
        return jsonify({
            'success': True,
            'message': '调度器已停止'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/reload', methods=['POST'])
def reload_scheduler():
    """重载调度器配置（热更新）"""
    try:
        import subprocess
        result = subprocess.run(
            ['python3', '/app/scheduler_service.py', 'reload'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': '配置已重载'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr or '重载失败'
            }), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/status')
def get_scheduler_status():
    """获取调度器状态"""
    try:
        import subprocess
        import json
        
        result = subprocess.run(
            ['python3', '/app/scheduler_service.py', 'status'],
            capture_output=True,
            text=True
        )
        
        status = json.loads(result.stdout) if result.returncode == 0 else {}
        
        # 获取执行日志
        executions = []
        try:
            log_file = Path('/app/logs/executions.json')
            if log_file.exists():
                with open(log_file, 'r') as f:
                    executions = json.load(f)[:10]  # 最近10条
        except:
            pass
        
        status['executions'] = executions
        
        return jsonify({
            'success': True,
            'data': status
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/run-once', methods=['POST'])
def run_once():
    """立即执行一次"""
    try:
        config_manager = ConfigManager()
        config = config_manager.load()
        
        # 使用调度器服务运行一次（后台执行）
        import subprocess
        subprocess.Popen(
            ['python3', '/app/scheduler_service.py', 'run-once'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        return jsonify({
            'success': True,
            'message': '任务已在后台启动'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/logs')
def get_scheduler_logs():
    """获取调度器执行日志"""
    try:
        executions = []
        log_file = Path('/app/logs/executions.json')
        if log_file.exists():
            with open(log_file, 'r') as f:
                executions = json.load(f)[:50]
        
        # 转换为前端期望的格式
        logs = []
        for exec_record in executions:
            level = 'success' if exec_record['success'] else 'error'
            logs.append({
                'timestamp': exec_record['timestamp'],
                'level': level,
                'message': exec_record['message'],
                'source': 'execution'
            })
        
        # 如果没有日志，返回提示
        if not logs:
            logs = [{
                'timestamp': datetime.now().isoformat(),
                'level': 'info',
                'message': '暂无执行记录，请执行任务后查看',
                'source': 'system'
            }]
        
        return jsonify({
            'success': True,
            'data': {'logs': logs}
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/scheduler/clear-logs', methods=['POST'])
def clear_scheduler_logs():
    """清空执行日志"""
    try:
        log_file = Path('/app/logs/executions.json')
        if log_file.exists():
            log_file.unlink()
        
        return jsonify({
            'success': True,
            'message': '执行日志已清空'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# 默认 CRON 选项
DEFAULT_CRON_OPTIONS = [
    {'label': '每天凌晨 2 点', 'value': '0 2 * * *', 'desc': '每日自动备份'},
    {'label': '每 6 小时', 'value': '0 */6 * * *', 'desc': '一天 4 次备份'},
    {'label': '每 3 小时', 'value': '0 */3 * * *', 'desc': '一天 8 次备份'},
    {'label': '每小时', 'value': '0 * * * *', 'desc': '每小时备份'},
    {'label': '每 30 分钟', 'value': '*/30 * * * *', 'desc': '高频备份'},
    {'label': '每 10 分钟', 'value': '*/10 * * * *', 'desc': '实时备份'},
    {'label': '仅执行一次', 'value': 'once', 'desc': '启动时执行一次'},
    {'label': '手动执行', 'value': 'manual', 'desc': '仅手动触发'},
]


@api_bp.route('/scheduler/cron-options')
def get_cron_options():
    """获取默认的 CRON 选项"""
    return jsonify({
        'success': True,
        'data': DEFAULT_CRON_OPTIONS
    })


# =============================================================================
# 静态文件服务
# =============================================================================

@main_bp.route('/static/<path:filename>')
def serve_static(filename):
    """服务静态文件"""
    return send_from_directory('static', filename)
