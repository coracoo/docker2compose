#!/usr/bin/env python3
"""
D2C 日志工具模块 - 生产级日志配置
使用标准 logging 模块，支持日志轮转和级别控制
"""

import os
import sys
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Optional


class D2CLogger:
    """D2C 日志管理器 - 单例模式"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, 
                 name: str = "D2C",
                 log_dir: str = '/app/logs',
                 level: int = logging.INFO,
                 max_bytes: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5):
        if D2CLogger._initialized:
            return
            
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = level
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        
        self._setup_logger()
        D2CLogger._initialized = True
    
    def _setup_logger(self):
        """配置日志记录器"""
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(self.level)
        self.logger.propagate = False
        
        # 避免重复添加处理器
        if self.logger.handlers:
            return
        
        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 文件处理器 - 带轮转
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / 'd2c.log',
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(self.level)
        file_handler.setFormatter(formatter)
        
        # 错误日志单独文件
        error_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / 'd2c.error.log',
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.level)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(console_handler)
    
    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)
    
    def set_level(self, level: int):
        """设置日志级别"""
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)


# 全局日志实例
_logger_instance: Optional[D2CLogger] = None


def get_logger() -> D2CLogger:
    """获取全局日志实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = D2CLogger()
    return _logger_instance


# 便捷函数
def debug(msg: str, *args, **kwargs):
    get_logger().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    get_logger().info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    get_logger().warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    get_logger().error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    get_logger().critical(msg, *args, **kwargs)


# 抑制第三方库的日志
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
