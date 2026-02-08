#!/usr/bin/env python3
"""
D2C Filters Module
用于过滤系统标签、环境变量等
"""

from typing import Dict, List, Optional, Set


# 系统标签前缀黑名单 - 这些前缀的标签将被过滤掉
SYSTEM_LABEL_PREFIXES: List[str] = [
    # Open Containers Initiative 标准标签
    'org.opencontainers.image.',
    'org.opencontainers.',
    
    # Label Schema 标准（已废弃但仍广泛使用）
    'org.label-schema.',
    
    # Docker 官方标签
    'com.docker.',
    'io.docker.',
    
    # 构建相关
    'build-date',
    'vcs-ref',
    'vcs-type',
    'vcs-url',
    
    # 其他常见系统标签
    'maintainer',  # 已弃用，改用 LABEL maintainer="..."
]

# 精确匹配的系统标签黑名单
SYSTEM_LABELS_EXACT: Set[str] = {
    # Docker Compose 生成的标签
    'com.docker.compose.container-number',
    'com.docker.compose.service',
    'com.docker.compose.project',
    'com.docker.compose.version',
    'com.docker.compose.config-hash',
    'com.docker.compose.project.config_files',
    'com.docker.compose.project.working_dir',
    'com.docker.compose.oneoff',
    'com.docker.compose.image',
    
    # 其他 Docker 内部标签
    'desktop.docker.io/binds/0/Source',
    'desktop.docker.io/binds/0/Target',
}

# 用户可能想保留的标签白名单（即使匹配系统前缀）
USER_LABEL_WHITELIST: Set[str] = set()

# 环境变量黑名单
ENV_VAR_BLACKLIST: Set[str] = {
    'PATH',
    'HOSTNAME',
    'HOME',
    'USER',
    'TERM',
    'LANG',
    'LANGUAGE',
    'LC_ALL',
    'PWD',
    'OLDPWD',
    'SHLVL',
    '_',  # 上一条命令
    
    # Docker 相关环境变量
    'DOCKER_HOST',
    'DOCKER_TLS_VERIFY',
    'DOCKER_CERT_PATH',
    
    # Python 相关
    'PYTHONPATH',
    'PYTHON_VERSION',
    'PYTHON_PIP_VERSION',
    'PYTHON_GET_PIP_URL',
    'PYTHON_GET_PIP_SHA256',
    
    # 其他常见系统环境变量
    'DEBIAN_FRONTEND',
    'GPG_KEY',
}

# 环境变量前缀黑名单
ENV_VAR_PREFIX_BLACKLIST: List[str] = [
    'APPDIR_',
    'APP_NAME_',
]

# 默认环境变量关键词黑名单（用于动态过滤）
DEFAULT_ENV_VAR_KEYWORDS: List[str] = [
    'VERSION',
    'YARN_VERSION',
    'NODE_VERSION',
    'APP_VERSION',
    'NPM_VERSION',
    'PYTHON_VERSION',
    'PIP_VERSION',
    'RUBY_VERSION',
    'GEM_VERSION',
    'GO_VERSION',
    'RUST_VERSION',
    'JAVA_VERSION',
    'GRADLE_VERSION',
    'MAVEN_VERSION',
    'PHP_VERSION',
    'COMPOSER_VERSION',
]


def should_keep_label(key: str, value: str = '') -> bool:
    """
    判断是否应该保留标签
    
    Args:
        key: 标签键名
        value: 标签值（用于未来可能的值过滤）
    
    Returns:
        bool: 是否保留该标签
    """
    # 如果标签在白名单中，直接保留
    if key in USER_LABEL_WHITELIST:
        return True
    
    # 如果标签在精确匹配黑名单中，过滤掉
    if key in SYSTEM_LABELS_EXACT:
        return False
    
    # 检查是否匹配系统前缀黑名单
    for prefix in SYSTEM_LABEL_PREFIXES:
        if key.startswith(prefix):
            return False
    
    # 其他标签保留
    return True


def filter_labels(labels: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    过滤容器标签，移除系统标签
    
    Args:
        labels: 原始标签字典
    
    Returns:
        过滤后的标签字典，如果没有有效标签则返回 None
    """
    if not labels:
        return None
    
    filtered = {
        k: v for k, v in labels.items() 
        if should_keep_label(k, v)
    }
    
    return filtered if filtered else None


def should_keep_env_var(key: str, filter_keywords: List[str] = None) -> bool:
    """
    判断是否应该保留环境变量
    
    Args:
        key: 环境变量名
        filter_keywords: 额外的过滤关键词列表
    
    Returns:
        bool: 是否保留该环境变量
    """
    # 如果在黑名单中，过滤掉
    if key in ENV_VAR_BLACKLIST:
        return False
    
    # 检查前缀黑名单
    for prefix in ENV_VAR_PREFIX_BLACKLIST:
        if key.startswith(prefix):
            return False
    
    # 检查动态过滤关键词
    if filter_keywords:
        for keyword in filter_keywords:
            keyword = keyword.strip()
            if keyword and keyword in key:
                return False
    
    return True


def filter_env_vars(env_vars: Optional[List[str]], 
                    filter_keywords: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
    """
    过滤环境变量，移除系统环境变量
    
    Args:
        env_vars: 环境变量列表，格式为 ['KEY=value', ...]
        filter_keywords: 额外的过滤关键词列表
    
    Returns:
        过滤后的环境变量字典，如果没有有效变量则返回 None
    """
    if not env_vars:
        return None
    
    filtered = {}
    for env_var in env_vars:
        if '=' not in env_var:
            continue
        
        key, value = env_var.split('=', 1)
        
        if should_keep_env_var(key, filter_keywords):
            filtered[key] = value
    
    return filtered if filtered else None


def parse_env_filter_keywords(filter_string: Optional[str]) -> List[str]:
    """
    解析环境变量过滤关键词字符串
    
    Args:
        filter_string: 逗号分隔的过滤关键词字符串
    
    Returns:
        过滤关键词列表
    """
    if not filter_string:
        return []
    
    # 按逗号分割并清理
    keywords = [kw.strip() for kw in filter_string.split(',') if kw.strip()]
    return keywords


def get_label_filter_stats(original: Optional[Dict[str, str]], 
                           filtered: Optional[Dict[str, str]]) -> Dict[str, int]:
    """
    获取标签过滤统计信息
    
    Args:
        original: 原始标签
        filtered: 过滤后的标签
    
    Returns:
        统计信息字典
    """
    original_count = len(original) if original else 0
    filtered_count = len(filtered) if filtered else 0
    
    return {
        'original_count': original_count,
        'filtered_count': filtered_count,
        'removed_count': original_count - filtered_count,
        'removed_ratio': f"{((original_count - filtered_count) / original_count * 100):.1f}%" if original_count > 0 else "0%"
    }


# Watchtower 标签（用户通常希望保留）
WATCHTOWER_LABELS: Set[str] = {
    'com.centurylinklabs.watchtower.enable',
    'com.centurylinklabs.watchtower.monitor-only',
}


def should_keep_watchtower_label(key: str) -> bool:
    """判断是否是需要保留的 Watchtower 标签"""
    return key in WATCHTOWER_LABELS or key.startswith('com.centurylinklabs.watchtower.')


if __name__ == '__main__':
    # 测试过滤器
    test_labels = {
        'com.docker.compose.project': 'myproject',
        'com.docker.compose.service': 'web',
        'org.opencontainers.image.title': 'My App',
        'org.label-schema.name': 'My App',
        'maintainer': 'test@example.com',
        'my.custom.label': 'value',
        'com.centurylinklabs.watchtower.enable': 'true',
        'app.version': '1.0.0',
    }
    
    filtered = filter_labels(test_labels)
    stats = get_label_filter_stats(test_labels, filtered)
    
    print("标签过滤测试:")
    print(f"  原始标签: {len(test_labels)} 个")
    print(f"  过滤后: {len(filtered)} 个")
    print(f"  移除: {stats['removed_count']} 个 ({stats['removed_ratio']})")
    print(f"  保留的标签: {filtered}")
    
    test_env = [
        'PATH=/usr/bin',
        'HOME=/root',
        'MY_APP_KEY=secret',
        'DATABASE_URL=postgres://localhost',
    ]
    
    filtered_env = filter_env_vars(test_env)
    print("\n环境变量过滤测试:")
    print(f"  原始环境变量: {len(test_env)} 个")
    print(f"  过滤后: {len(filtered_env)} 个")
    print(f"  保留的环境变量: {filtered_env}")
