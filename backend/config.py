#!/usr/bin/env python3
"""
D2C Configuration Management
使用 Pydantic 进行类型安全的配置管理
"""

import json
import os
import time
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils.logger import get_logger

logger = get_logger()


class D2CConfig(BaseSettings):
    """D2C 配置模型"""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # 定时任务配置 - 支持标准 cron 表达式或特殊值: once, manual
    cron: str = Field(
        default='0 2 * * *',  # 默认每天凌晨 2 点
        alias='CRON',
        description="定时执行配置: '0 2 * * *'(每天凌晨2点), 'manual'(手动), 'once'(执行一次)"
    )
    
    # 网络配置显示控制
    network: bool = Field(
        default=True,
        alias='NETWORK',
        description="控制bridge网络配置的显示方式: true(显示) 或 false(隐藏)"
    )
    
    # Healthcheck 配置显示控制
    show_healthcheck: bool = Field(
        default=True,
        alias='SHOW_HEALTHCHECK',
        description="控制healthcheck配置的显示方式: true(显示) 或 false(隐藏)"
    )
    
    # CapAdd 配置显示控制
    show_cap_add: bool = Field(
        default=True,
        alias='SHOW_CAP_ADD',
        description="控制cap_add配置的显示方式: true(显示) 或 false(隐藏)"
    )
    
    # 环境变量过滤关键词
    env_filter_keywords: str = Field(
        default='',
        alias='ENV_FILTER_KEYWORDS',
        description="环境变量过滤关键词，逗号分隔。匹配这些关键词的环境变量将被过滤掉"
    )
    
    # Command 配置显示控制
    show_command: bool = Field(
        default=True,
        alias='SHOW_COMMAND',
        description="控制command配置的显示方式: true(显示) 或 false(隐藏)"
    )
    
    # Entrypoint 配置显示控制
    show_entrypoint: bool = Field(
        default=True,
        alias='SHOW_ENTRYPOINT',
        description="控制entrypoint配置的显示方式: true(显示) 或 false(隐藏)"
    )
    
    # 时区配置
    timezone: str = Field(
        default='Asia/Shanghai',
        alias='TZ',
        description="时区设置,如Asia/Shanghai、Europe/London等"
    )
    
    # 输出目录
    output_dir: str = Field(
        default='/app/compose',
        alias='OUTPUT_DIR',
        description="compose文件输出目录"
    )
    
    # 配置文件路径
    config_file: Path = Field(
        default=Path('/app/config/config.json'),
        exclude=True
    )
    
    @field_validator('cron')
    @classmethod
    def validate_cron(cls, v: str) -> str:
        """验证 CRON 表达式格式"""
        # 支持特殊值
        if v in ('once', 'manual'):
            return v
        
        parts = v.split()
        if len(parts) not in [5, 6]:
            raise ValueError(f'CRON表达式必须是5位或6位格式，当前: {len(parts)}位')
        
        # 基本字符验证
        valid_chars = set('0123456789*/,-? ')
        for part in parts:
            if not all(c in valid_chars for c in part):
                raise ValueError(f'CRON表达式包含无效字符: {part}')
        
        return v
    
    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """验证时区格式"""
        # 检查时区文件是否存在
        tz_path = Path(f'/usr/share/zoneinfo/{v}')
        if not tz_path.exists():
            # 在容器中可能不存在，只打印警告
            print(f"[WARNING] 时区文件不存在: {tz_path}，将使用系统默认时区")
        return v


class ConfigManager:
    """配置管理器 - 带缓存机制"""
    
    def __init__(self, config_path: str = '/app/config/config.json'):
        self.config_path = Path(config_path)
        self._config: Optional[D2CConfig] = None
        self._last_modified: float = 0
        self._last_size: int = 0
        self._load_count: int = 0
        self._last_log_time: float = 0  # 上次打印日志时间
    
    def _is_config_changed(self) -> bool:
        """检查配置文件是否发生变化"""
        if not self.config_path.exists():
            return True
        
        stat = self.config_path.stat()
        return stat.st_mtime != self._last_modified or stat.st_size != self._last_size
    
    def _update_cache_info(self):
        """更新缓存信息"""
        if self.config_path.exists():
            stat = self.config_path.stat()
            self._last_modified = stat.st_mtime
            self._last_size = stat.st_size
    
    def load(self, force: bool = False) -> D2CConfig:
        """加载配置，优先从文件读取，带缓存机制"""
        self._load_count += 1
        
        # 如果配置已缓存且文件未变化，直接返回缓存
        if not force and self._config is not None and not self._is_config_changed():
            return self._config
        
        # 如果配置文件存在，从文件加载
        if self.config_path.exists():
            try:
                # 检查文件是否为空
                if self.config_path.stat().st_size == 0:
                    logger.warning(f"配置文件为空: {self.config_path}")
                    self._config = D2CConfig()
                    self.save(self._config)
                    return self._config
                
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                
                # 检查是否为字典
                if not isinstance(file_data, dict):
                    raise ValueError(f"配置文件格式错误: 期望字典，实际为 {type(file_data).__name__}")
                
                # 过滤掉注释字段（以 // 开头的键）
                clean_data = {k: v for k, v in file_data.items() if not k.startswith('//')}
                
                # 创建配置对象
                self._config = D2CConfig.model_validate(clean_data)
                self._update_cache_info()
                
                # 限制日志打印频率（至少间隔10秒）
                current_time = time.time()
                if current_time - self._last_log_time > 10:
                    logger.info(f"配置加载成功: CRON={self._config.cron}, NETWORK={self._config.network}")
                    self._last_log_time = current_time
                
                return self._config
                
            except json.JSONDecodeError as e:
                logger.error(f"配置文件 JSON 解析失败: {e}")
                # 备份损坏的配置文件
                backup_path = self.config_path.with_suffix('.json.backup')
                try:
                    self.config_path.rename(backup_path)
                    logger.info(f"原文件已备份到: {backup_path}")
                except Exception as backup_err:
                    logger.warning(f"备份失败: {backup_err}")
                
                self._config = D2CConfig()
                self.save(self._config)
                return self._config
                
            except Exception as e:
                logger.warning(f"读取配置文件失败: {e}，使用默认配置")
        
        # 从环境变量加载
        self._config = D2CConfig()
        if self._load_count <= 1:
            logger.info("使用默认配置")
        return self._config
    
    def save(self, config: D2CConfig) -> None:
        """保存配置到文件（带注释）"""
        # 确保配置目录存在
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 构建带注释的配置数据
        config_data = {
            "// 配置说明": "以下是D2C的配置选项",
            "// CRON": "定时执行配置: '0 2 * * *'(每天凌晨2点), 'manual'(手动), 'once'(执行一次), 或自定义CRON",
            "CRON": config.cron,
            "// NETWORK": "控制bridge网络配置的显示方式: true(显示) 或 false(隐藏)",
            "NETWORK": str(config.network).lower(),
            "// SHOW_HEALTHCHECK": "控制healthcheck配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_HEALTHCHECK": str(config.show_healthcheck).lower(),
            "// SHOW_CAP_ADD": "控制cap_add配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_CAP_ADD": str(config.show_cap_add).lower(),
            "// SHOW_COMMAND": "控制command配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_COMMAND": str(config.show_command).lower(),
            "// SHOW_ENTRYPOINT": "控制entrypoint配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_ENTRYPOINT": str(config.show_entrypoint).lower(),
            "// ENV_FILTER_KEYWORDS": "环境变量过滤关键词，逗号分隔。匹配这些关键词的环境变量将被过滤掉",
            "ENV_FILTER_KEYWORDS": config.env_filter_keywords,
            "// TZ": "时区设置,如Asia/Shanghai、Europe/London等",
            "TZ": config.timezone
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        
        self._config = config
        self._update_cache_info()
        logger.info(f"配置已保存: {self.config_path}")
    
    def ensure_config_file(self) -> D2CConfig:
        """确保配置文件存在，如果不存在则创建默认配置"""
        if not self.config_path.exists():
            logger.info(f"配置文件不存在，创建默认配置")
            default_config = D2CConfig()
            self.save(default_config)
            return default_config
        
        return self.load()
    
    def reload(self) -> D2CConfig:
        """重新加载配置"""
        self._config = None
        return self.load()
    
    @property
    def config(self) -> D2CConfig:
        """获取当前配置（缓存）"""
        if self._config is None:
            return self.load()
        return self._config


# 全局配置管理器实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_path: str = '/app/config/config.json') -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
    return _config_manager


def load_config() -> D2CConfig:
    """快捷函数：加载配置"""
    return get_config_manager().load()


def save_config(config: D2CConfig) -> None:
    """快捷函数：保存配置"""
    get_config_manager().save(config)


def ensure_config() -> D2CConfig:
    """快捷函数：确保配置存在"""
    return get_config_manager().ensure_config_file()


if __name__ == '__main__':
    # 测试配置管理
    config = ensure_config()
    print(f"\n当前配置:")
    print(f"  CRON: {config.cron}")
    print(f"  NETWORK: {config.network}")
    print(f"  SHOW_HEALTHCHECK: {config.show_healthcheck}")
    print(f"  SHOW_CAP_ADD: {config.show_cap_add}")
    print(f"  TZ: {config.timezone}")
    print(f"  OUTPUT_DIR: {config.output_dir}")
