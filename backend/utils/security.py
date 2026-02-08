#!/usr/bin/env python3
"""
D2C Security Utilities
安全相关工具函数
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple


class SecurityError(Exception):
    """安全错误异常"""
    pass


def validate_path(file_path: str, 
                  allowed_base_paths: list[str],
                  allow_absolute: bool = True) -> Path:
    """
    验证文件路径，防止路径遍历攻击
    
    Args:
        file_path: 用户提供的文件路径
        allowed_base_paths: 允许的基路径列表
        allow_absolute: 是否允许绝对路径
    
    Returns:
        验证后的 Path 对象
    
    Raises:
        SecurityError: 路径验证失败
    """
    # 规范化路径
    path = Path(file_path).resolve()
    
    # 检查是否是绝对路径
    if not allow_absolute and path.is_absolute():
        raise SecurityError(f"不允许使用绝对路径: {file_path}")
    
    # 检查路径是否在允许的基路径下
    allowed = False
    for base_path in allowed_base_paths:
        base = Path(base_path).resolve()
        try:
            # 检查 path 是否是 base 的子路径
            path.relative_to(base)
            allowed = True
            break
        except ValueError:
            continue
    
    if not allowed:
        raise SecurityError(f"无权访问该路径: {file_path}")
    
    return path


def sanitize_filename(filename: str, 
                     max_length: int = 255,
                     allowed_pattern: Optional[str] = None) -> str:
    """
    清理文件名，移除危险字符
    
    Args:
        filename: 原始文件名
        max_length: 最大长度
        allowed_pattern: 允许的字符正则表达式
    
    Returns:
        清理后的文件名
    """
    # 默认只允许字母、数字、下划线、连字符和点
    if allowed_pattern is None:
        allowed_pattern = r'[^a-zA-Z0-9_.\-]'
    
    # 移除路径分隔符和危险字符
    sanitized = re.sub(r'[/\\<>:"|?*\x00-\x1f]', '', filename)
    
    # 应用自定义模式
    sanitized = re.sub(allowed_pattern, '_', sanitized)
    
    # 移除前导和尾随的点和空格
    sanitized = sanitized.strip('. ')
    
    # 限制长度
    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:max_length - len(ext)] + ext
    
    # 如果文件名为空，使用默认名称
    if not sanitized:
        sanitized = 'unnamed'
    
    return sanitized


def validate_container_id(container_id: str) -> bool:
    """
    验证容器 ID 格式
    
    Args:
        container_id: 容器 ID
    
    Returns:
        是否有效
    """
    if not container_id:
        return False
    
    # Docker 容器 ID 是 64 位十六进制字符串，通常使用短 ID（12 位）
    pattern = r'^[a-f0-9]{12,64}$'
    return bool(re.match(pattern, container_id.lower()))


def validate_cron_expression(cron_expr: str) -> Tuple[bool, str]:
    """
    验证 CRON 表达式
    
    Args:
        cron_expr: CRON 表达式
    
    Returns:
        (是否有效, 错误信息)
    """
    if cron_expr == 'once':
        return True, ""
    
    parts = cron_expr.split()
    if len(parts) not in [5, 6]:
        return False, f"CRON表达式必须是5位或6位格式，当前: {len(parts)}位"
    
    # 基本字符验证
    valid_chars = set('0123456789*/,-? ')
    for i, part in enumerate(parts):
        if not all(c in valid_chars for c in part):
            return False, f"第{i+1}个字段包含无效字符: {part}"
    
    return True, ""


def escape_shell_arg(arg: str) -> str:
    """
    转义 shell 参数，防止命令注入
    
    Args:
        arg: 原始参数
    
    Returns:
        转义后的参数
    """
    # 如果参数包含特殊字符，使用单引号包裹
    if re.search(r'[^a-zA-Z0-9_.\-/]', arg):
        # 将单引号替换为 '\'' 以安全地包裹
        return "'" + arg.replace("'", "'\\''") + "'"
    return arg


class RateLimiter:
    """简单的内存速率限制器"""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = {}
    
    def is_allowed(self, key: str) -> bool:
        """
        检查是否允许请求
        
        Args:
            key: 标识符（如 IP 地址）
        
        Returns:
            是否允许
        """
        import time
        
        now = time.time()
        
        # 清理过期的请求记录
        if key in self.requests:
            self.requests[key] = [
                t for t in self.requests[key] 
                if now - t < self.window_seconds
            ]
        else:
            self.requests[key] = []
        
        # 检查是否超过限制
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        # 记录本次请求
        self.requests[key].append(now)
        return True


if __name__ == '__main__':
    # 测试安全工具
    print("路径验证测试:")
    try:
        path = validate_path('/app/compose/test.yaml', ['/app/compose', '/app/config'])
        print(f"  有效路径: {path}")
    except SecurityError as e:
        print(f"  错误: {e}")
    
    try:
        path = validate_path('/etc/passwd', ['/app/compose', '/app/config'])
        print(f"  有效路径: {path}")
    except SecurityError as e:
        print(f"  预期错误: {e}")
    
    print("\n文件名清理测试:")
    test_names = [
        '../../../etc/passwd',
        'test<>|file.yaml',
        'valid_name.yaml',
        '',
        '.hidden',
    ]
    for name in test_names:
        print(f"  '{name}' -> '{sanitize_filename(name)}'")
    
    print("\n容器 ID 验证测试:")
    test_ids = [
        'abc123def456',
        'abc123',
        'invalid-id',
        'abc123def456ghi789',
    ]
    for id in test_ids:
        print(f"  '{id}' -> {validate_container_id(id)}")
