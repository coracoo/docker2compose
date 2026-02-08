#!/usr/bin/env python3
"""
D2C Flask Application Factory
使用应用工厂模式创建 Flask 应用
"""

import os
import secrets
import logging
from pathlib import Path
from flask import Flask, request

from config import ConfigManager
from utils.logger import get_logger
from .routes import api_bp, main_bp
from .auth import auth_bp, init_login_manager

logger = get_logger()


def load_or_create_secret_key() -> str:
    """加载或创建固定的 SECRET_KEY"""
    key_file = Path('/app/config/.secret_key')
    if key_file.exists():
        return key_file.read_text().strip()
    
    # 创建新的 key
    key = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    return key


def create_app(config_path: str = '/app/config/config.json') -> Flask:
    """
    创建 Flask 应用实例
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        Flask 应用实例
    """
    app = Flask(__name__)
    
    # 配置 - 使用固定的 SECRET_KEY 确保多 worker 间 session 共享
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or load_or_create_secret_key()
    app.config['CONFIG_PATH'] = config_path
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24小时
    app.config['SESSION_COOKIE_SECURE'] = False  # 允许 HTTP
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # 减少 Werkzeug 日志输出
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.WARNING)
    
    # 初始化用户认证
    init_login_manager(app)
    
    # 确保配置存在
    config_manager = ConfigManager(config_path)
    config_manager.ensure_config_file()
    
    # 注册蓝图
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    
    # 错误处理器
    register_error_handlers(app)
    
    # 请求完成后记录（仅记录错误）
    @app.after_request
    def after_request(response):
        if response.status_code >= 400:
            logger.warning(f"HTTP {response.status_code} {request.path}")
        return response
    
    logger.info("Web 服务初始化完成")
    return app


def register_error_handlers(app: Flask):
    """注册错误处理器"""
    
    @app.errorhandler(404)
    def not_found(error):
        from flask import jsonify
        return jsonify({'success': False, 'error': 'Not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        from flask import jsonify
        logger.error(f"服务器错误: {error}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


# 应用实例（用于 Gunicorn）
app = create_app()
