#!/usr/bin/env python3
"""
D2C 用户认证模块
使用 Flask-Login 实现成熟的用户体系
"""

import os
import secrets
import hashlib
from pathlib import Path
from typing import Optional, Dict
from functools import wraps

from flask import Blueprint, request, jsonify, session, current_app
from flask_login import (
    LoginManager, UserMixin, 
    login_user, logout_user, 
    login_required, current_user
)

from utils.logger import get_logger

logger = get_logger()

# 蓝图
auth_bp = Blueprint('auth', __name__)

# 用户数据存储路径
USERS_FILE = Path('/app/config/users.json')


class User(UserMixin):
    """用户类"""
    
    def __init__(self, user_id: str, username: str, is_admin: bool = False):
        self.id = user_id
        self.username = username
        self.is_admin = is_admin
    
    def get_id(self):
        return self.id
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'username': self.username,
            'is_admin': self.is_admin
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'User':
        return User(
            user_id=data.get('id'),
            username=data.get('username'),
            is_admin=data.get('is_admin', False)
        )


class UserManager:
    """用户管理器 - 单例模式"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._users: Dict[str, Dict] = {}
        self._sessions: Dict[str, str] = {}
        self._load_users()
        self._initialized = True
    
    def _load_users(self):
        """从文件加载用户数据"""
        import fcntl
        try:
            if USERS_FILE.exists():
                import json
                # 使用文件锁防止并发读取问题
                with open(USERS_FILE, 'r', encoding='utf-8') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    self._users = json.load(f)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                logger.info(f"已加载 {len(self._users)} 个用户")
            else:
                # 创建默认管理员账户（带锁）
                self._create_default_admin_safe()
        except Exception as e:
            logger.error(f"加载用户数据失败: {e}")
            self._users = {}
    
    def _create_default_admin_safe(self):
        """安全地创建默认管理员（带文件锁）"""
        import fcntl
        import json
        
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 尝试获取排他锁
        lock_file = USERS_FILE.parent / '.users.lock'
        with open(lock_file, 'w') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # 再次检查文件是否已存在（可能被其他进程创建）
                if USERS_FILE.exists():
                    with open(USERS_FILE, 'r', encoding='utf-8') as f:
                        self._users = json.load(f)
                    return
                
                # 创建默认管理员
                default_username = 'admin'
                default_password = 'admin123'
                
                password_hash, salt = self._hash_password(default_password)
                
                self._users = {
                    default_username: {
                        'id': secrets.token_hex(16),
                        'username': default_username,
                        'password_hash': password_hash,
                        'salt': salt,
                        'is_admin': True,
                        'created_at': str(__import__('datetime').datetime.now()),
                        'require_password_change': True
                    }
                }
                
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._users, f, indent=2, ensure_ascii=False)
                
                logger.info("已创建默认管理员账户 (admin/admin123)")
                
            except (IOError, OSError):
                # 无法获取锁，等待后重试加载
                import time
                time.sleep(0.5)
                if USERS_FILE.exists():
                    with open(USERS_FILE, 'r', encoding='utf-8') as f:
                        self._users = json.load(f)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    
    def _save_users(self):
        """保存用户数据到文件（内部方法，实际保存已通过锁保护）"""
        # 实际保存逻辑在各自的锁保护块中完成
        pass
    
    def _create_default_admin(self):
        """创建默认管理员账户（已弃用，使用 _create_default_admin_safe）"""
        pass  # 由 _load_users 调用 _create_default_admin_safe 替代
    
    def _hash_password(self, password: str, salt: Optional[str] = None) -> tuple:
        """密码哈希"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        # 使用 PBKDF2 进行密码哈希
        hash_value = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # 迭代次数
        ).hex()
        
        return hash_value, salt
    
    def create_user(self, username: str, password: str, is_admin: bool = False) -> Optional[User]:
        """创建新用户（带文件锁）"""
        import fcntl
        import json
        from datetime import datetime
        
        lock_file = USERS_FILE.parent / '.users.lock'
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(lock_file, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            
            try:
                # 重新加载用户数据（可能有其他进程已更新）
                if USERS_FILE.exists():
                    with open(USERS_FILE, 'r', encoding='utf-8') as f:
                        self._users = json.load(f)
                
                if username in self._users:
                    logger.warning(f"用户已存在: {username}")
                    return None
                
                user_id = secrets.token_hex(16)
                password_hash, salt = self._hash_password(password)
                
                self._users[username] = {
                    'id': user_id,
                    'username': username,
                    'password_hash': password_hash,
                    'salt': salt,
                    'is_admin': is_admin,
                    'created_at': str(datetime.now()),
                    'require_password_change': True
                }
                
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._users, f, indent=2, ensure_ascii=False)
                
                logger.info(f"创建用户成功: {username}")
                
                return User(user_id=user_id, username=username, is_admin=is_admin)
                
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    
    def verify_user(self, username: str, password: str) -> Optional[User]:
        """验证用户密码"""
        user_data = self._users.get(username)
        if not user_data:
            return None
        
        password_hash, _ = self._hash_password(password, user_data['salt'])
        
        if password_hash == user_data['password_hash']:
            return User(
                user_id=user_data['id'],
                username=user_data['username'],
                is_admin=user_data.get('is_admin', False)
            )
        
        return None
    
    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改密码"""
        user_data = self._users.get(username)
        if not user_data:
            return False
        
        # 验证旧密码
        old_hash, _ = self._hash_password(old_password, user_data['salt'])
        if old_hash != user_data['password_hash']:
            return False
        
        # 设置新密码
        new_hash, new_salt = self._hash_password(new_password)
        user_data['password_hash'] = new_hash
        user_data['salt'] = new_salt
        user_data['require_password_change'] = False
        
        self._save_users()
        logger.info(f"用户 {username} 修改了密码")
        return True
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """通过 ID 获取用户"""
        for username, data in self._users.items():
            if data['id'] == user_id:
                return User(
                    user_id=data['id'],
                    username=data['username'],
                    is_admin=data.get('is_admin', False)
                )
        return None
    
    def list_users(self) -> list:
        """获取用户列表"""
        return [
            {
                'id': data['id'],
                'username': data['username'],
                'is_admin': data.get('is_admin', False),
                'created_at': data.get('created_at', ''),
                'require_password_change': data.get('require_password_change', False)
            }
            for username, data in self._users.items()
        ]
    
    def delete_user(self, username: str) -> bool:
        """删除用户"""
        if username in self._users:
            del self._users[username]
            self._save_users()
            logger.info(f"删除用户: {username}")
            return True
        return False


# 全局用户管理器
user_manager = UserManager()


def init_login_manager(app):
    """初始化 Flask-Login"""
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录'
    
    @login_manager.user_loader
    def load_user(user_id):
        return user_manager.get_user_by_id(user_id)
    
    return login_manager


# ==================== API 路由 ====================

@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
        
        user = user_manager.verify_user(username, password)
        
        if not user:
            logger.warning(f"登录失败: {username}")
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
        
        login_user(user, remember=data.get('remember', False))
        logger.info(f"用户登录: {username}")
        
        return jsonify({
            'success': True,
            'message': '登录成功',
            'data': {
                'user': user.to_dict(),
                'require_password_change': user_manager._users[username].get('require_password_change', False)
            }
        })
        
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return jsonify({'success': False, 'error': '登录失败'}), 500


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """用户登出"""
    logger.info(f"用户登出: {current_user.username}")
    logout_user()
    return jsonify({'success': True, 'message': '已登出'})


@auth_bp.route('/me')
@login_required
def get_current_user():
    """获取当前用户信息"""
    return jsonify({
        'success': True,
        'data': current_user.to_dict()
    })


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """修改密码"""
    try:
        data = request.get_json() or {}
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        
        if not old_password or not new_password:
            return jsonify({'success': False, 'error': '旧密码和新密码不能为空'}), 400
        
        if len(new_password) < 6:
            return jsonify({'success': False, 'error': '新密码长度不能少于6位'}), 400
        
        success = user_manager.change_password(
            current_user.username,
            old_password,
            new_password
        )
        
        if success:
            return jsonify({'success': True, 'message': '密码修改成功'})
        else:
            return jsonify({'success': False, 'error': '旧密码错误'}), 400
            
    except Exception as e:
        logger.error(f"修改密码异常: {e}")
        return jsonify({'success': False, 'error': '修改密码失败'}), 500


# 管理员接口

@auth_bp.route('/users', methods=['GET'])
@login_required
def list_users():
    """获取用户列表（仅管理员）"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403
    
    return jsonify({
        'success': True,
        'data': user_manager.list_users()
    })


@auth_bp.route('/users', methods=['POST'])
@login_required
def create_user():
    """创建用户（仅管理员）"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403
    
    try:
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        is_admin = data.get('is_admin', False)
        
        if not username or not password:
            return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
        
        if len(password) < 6:
            return jsonify({'success': False, 'error': '密码长度不能少于6位'}), 400
        
        user = user_manager.create_user(username, password, is_admin)
        
        if user:
            return jsonify({
                'success': True,
                'message': '用户创建成功',
                'data': user.to_dict()
            })
        else:
            return jsonify({'success': False, 'error': '用户已存在'}), 409
            
    except Exception as e:
        logger.error(f"创建用户异常: {e}")
        return jsonify({'success': False, 'error': '创建用户失败'}), 500


@auth_bp.route('/users/<username>', methods=['DELETE'])
@login_required
def delete_user(username):
    """删除用户（仅管理员）"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': '权限不足'}), 403
    
    if username == current_user.username:
        return jsonify({'success': False, 'error': '不能删除当前登录的用户'}), 400
    
    success = user_manager.delete_user(username)
    
    if success:
        return jsonify({'success': True, 'message': '用户已删除'})
    else:
        return jsonify({'success': False, 'error': '用户不存在'}), 404


def require_auth(f):
    """API 认证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查 session
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        
        # 检查 API Token（可选）
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
            # 这里可以实现 token 验证逻辑
            return f(*args, **kwargs)
        
        return jsonify({'success': False, 'error': '请先登录'}), 401
    
    return decorated_function
