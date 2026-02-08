#!/usr/bin/env python3
"""
D2C Converter Module
Docker 容器到 Compose 配置的转换核心
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

from config import D2CConfig
from filters import filter_labels, filter_env_vars, should_keep_watchtower_label, parse_env_filter_keywords
from utils.yaml_utils import dump_compose_config


def convert_container_to_service(container: Dict[str, Any], 
                                 config: D2CConfig,
                                 networks_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    将容器配置转换为 docker-compose 服务配置
    
    Args:
        container: Docker 容器信息字典
        config: D2C 配置
        networks_info: 网络信息字典
    
    Returns:
        Compose 服务配置字典
    """
    service: Dict[str, Any] = {}
    
    # 获取容器名称
    container_name = container.get('Name', '').lstrip('/')
    service['container_name'] = container_name
    
    # 获取镜像
    image = container.get('Config', {}).get('Image', '')
    service['image'] = image
    
    # 重启策略
    restart_policy = container.get('HostConfig', {}).get('RestartPolicy', {})
    if restart_policy and restart_policy.get('Name'):
        policy_name = restart_policy['Name']
        if policy_name != 'no':
            if policy_name == 'on-failure' and restart_policy.get('MaximumRetryCount'):
                service['restart'] = f"{policy_name}:{restart_policy['MaximumRetryCount']}"
            else:
                service['restart'] = policy_name
    
    # 端口映射
    ports = convert_ports(container)
    if ports:
        service['ports'] = ports
    
    # 环境变量（过滤系统变量和自定义关键词）
    env_vars = container.get('Config', {}).get('Env', [])
    filter_keywords = parse_env_filter_keywords(config.env_filter_keywords)
    filtered_env = filter_env_vars(env_vars, filter_keywords)
    if filtered_env:
        service['environment'] = filtered_env
    
    # 卷挂载
    volumes = convert_volumes(container)
    if volumes:
        service['volumes'] = volumes
    
    # 网络配置
    network_config = convert_networks(container, config, networks_info)
    if network_config:
        service.update(network_config)
    
    # 链接
    links = convert_links(container)
    if links:
        service['links'] = links
    
    # 特权模式
    if container.get('HostConfig', {}).get('Privileged'):
        service['privileged'] = True
    
    # 设备挂载
    devices = convert_devices(container)
    if devices:
        service['devices'] = devices
    
    # 标签（过滤系统标签）
    labels = container.get('Config', {}).get('Labels', {})
    filtered_labels = filter_labels(labels)
    if filtered_labels:
        service['labels'] = filtered_labels
    
    # CapAdd（根据配置判断是否显示）
    if config.show_cap_add:
        caps = convert_capabilities(container)
        if caps:
            service['cap_add'] = caps
    
    # Security Opt
    security_opt = convert_security_options(container)
    if security_opt:
        service['security_opt'] = security_opt
    
    # 主机名解析
    extra_hosts = container.get('HostConfig', {}).get('ExtraHosts', [])
    if extra_hosts:
        service['extra_hosts'] = extra_hosts
    
    # 时区（如果配置需要）
    tz = config.timezone
    if tz and tz != 'UTC':
        # 只在环境变量中没有 TZ 时才添加
        if not filtered_env or 'TZ' not in filtered_env:
            if 'environment' not in service:
                service['environment'] = {}
            service['environment']['TZ'] = tz
    
    # Entrypoint（根据配置判断是否显示）
    if config.show_entrypoint:
        entrypoint = container.get('Config', {}).get('Entrypoint')
        if entrypoint:
            service['entrypoint'] = entrypoint[0] if len(entrypoint) == 1 else entrypoint
    
    # Command（根据配置判断是否显示）
    if config.show_command:
        cmd = container.get('Config', {}).get('Cmd')
        entrypoint = container.get('Config', {}).get('Entrypoint')
        if cmd and cmd != entrypoint:
            service['command'] = cmd[0] if len(cmd) == 1 else cmd
    
    # 健康检查（根据配置判断是否显示）
    if config.show_healthcheck:
        healthcheck = convert_healthcheck(container)
        if healthcheck:
            service['healthcheck'] = healthcheck
    
    return service


def convert_ports(container: Dict[str, Any]) -> List[str]:
    """转换端口映射，自动去重"""
    ports = []
    seen = set()  # 用于去重
    port_mappings = container.get('NetworkSettings', {}).get('Ports', {})
    
    if not port_mappings:
        return ports
    
    for container_port, host_bindings in port_mappings.items():
        if not host_bindings:
            continue
        
        # 解析容器端口和协议
        port_proto = container_port  # 例如 "80/tcp"
        
        for binding in host_bindings:
            host_ip = binding.get('HostIp', '')
            host_port = binding.get('HostPort', '')
            
            if not host_port:
                continue
            
            # 构建端口映射字符串
            if host_ip and host_ip not in ['0.0.0.0', '::']:
                # 指定了特定 IP
                port_str = f"{host_ip}:{host_port}:{port_proto}"
            else:
                # 标准格式
                port_str = f"{host_port}:{port_proto}"
            
            # 去重检查
            if port_str not in seen:
                seen.add(port_str)
                ports.append(port_str)
    
    return ports


def convert_volumes(container: Dict[str, Any]) -> List[str]:
    """转换卷挂载"""
    volumes = []
    mounts = container.get('Mounts', [])
    
    for mount in mounts:
        mount_type = mount.get('Type', '')
        target = mount.get('Destination', '')
        rw = mount.get('RW', True)
        
        if mount_type == 'volume':
            source = mount.get('Name', '')
        elif mount_type == 'bind':
            source = mount.get('Source', '')
        else:
            continue
        
        if not source or not target:
            continue
        
        # 构建卷映射字符串
        if rw:
            volumes.append(f"{source}:{target}")
        else:
            volumes.append(f"{source}:{target}:ro")
    
    return volumes


def convert_networks(container: Dict[str, Any], 
                     config: D2CConfig,
                     networks_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """转换网络配置"""
    result = {}
    
    network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
    networks_config = container.get('NetworkSettings', {}).get('Networks', {})
    
    # 特殊网络模式
    if network_mode == 'host':
        result['network_mode'] = 'host'
        return result
    
    if network_mode == 'none':
        result['network_mode'] = 'none'
        return result
    
    if network_mode.startswith('container:'):
        linked_container = network_mode.split(':')[1]
        result['network_mode'] = f"container:{linked_container}"
        return result
    
    if network_mode == 'bridge':
        if config.network:
            result['network_mode'] = 'bridge'
        return result
    
    # 自定义网络
    custom_networks = {}
    
    for network_name, network_config in networks_config.items():
        # 跳过默认网络
        if network_name in ['bridge', 'host', 'none']:
            continue
        
        # 检查网络驱动
        driver = ''
        if networks_info and network_name in networks_info:
            driver = networks_info[network_name].get('Driver', '')
        
        # 构建网络配置
        net_settings = {}
        
        # IPv4 地址
        ipam = network_config.get('IPAMConfig', {})
        if ipam and ipam.get('IPv4Address'):
            net_settings['ipv4_address'] = ipam['IPv4Address']
        elif network_config.get('IPAddress'):
            net_settings['ipv4_address'] = network_config['IPAddress']
        
        # IPv6 地址
        if ipam and ipam.get('IPv6Address'):
            net_settings['ipv6_address'] = ipam['IPv6Address']
        elif network_config.get('GlobalIPv6Address'):
            net_settings['ipv6_address'] = network_config['GlobalIPv6Address']
        
        # MAC 地址
        if network_config.get('MacAddress'):
            net_settings['mac_address'] = network_config['MacAddress']
        
        # 存储网络配置
        if net_settings:
            custom_networks[network_name] = net_settings
        else:
            custom_networks[network_name] = None
    
    if custom_networks:
        # 简化格式：如果所有网络都没有特殊配置，使用列表格式
        if all(v is None for v in custom_networks.values()):
            result['networks'] = list(custom_networks.keys())
        else:
            # 转换 None 为空字典，保持格式一致
            result['networks'] = {
                k: (v if v is not None else {}) 
                for k, v in custom_networks.items()
            }
    
    return result


def convert_links(container: Dict[str, Any]) -> List[str]:
    """转换容器链接"""
    links = []
    raw_links = container.get('HostConfig', {}).get('Links', [])
    
    for link in raw_links or []:
        # 链接格式: /container_name:/alias
        parts = link.split(':')
        if len(parts) >= 2:
            container_name = parts[0].lstrip('/')
            alias = parts[1].lstrip('/')
            links.append(f"{container_name}:{alias}")
        else:
            links.append(link.lstrip('/'))
    
    return links


def convert_devices(container: Dict[str, Any]) -> List[str]:
    """转换设备挂载"""
    devices = []
    raw_devices = container.get('HostConfig', {}).get('Devices', [])
    
    for device in raw_devices or []:
        host_path = device.get('PathOnHost', '')
        container_path = device.get('PathInContainer', '')
        cgroup_perms = device.get('CgroupPermissions', 'rwm')
        
        if host_path and container_path:
            devices.append(f"{host_path}:{container_path}:{cgroup_perms}")
    
    return devices


def convert_capabilities(container: Dict[str, Any]) -> List[str]:
    """转换能力配置"""
    caps = []
    cap_add = container.get('HostConfig', {}).get('CapAdd', [])
    
    # 只保留用户添加的能力，不自动添加
    for cap in cap_add or []:
        caps.append(cap)
    
    return caps


def convert_security_options(container: Dict[str, Any]) -> List[str]:
    """转换安全选项"""
    security_opt = []
    
    # 检查是否需要 apparmor unconfined
    cap_add = container.get('HostConfig', {}).get('CapAdd', [])
    
    if cap_add and ('SYS_ADMIN' in cap_add or 'NET_ADMIN' in cap_add):
        # 检查是否已经有 apparmor 设置
        existing_opts = container.get('HostConfig', {}).get('SecurityOpt', [])
        has_apparmor = any('apparmor' in opt for opt in existing_opts or [])
        
        if not has_apparmor:
            security_opt.append('apparmor:unconfined')
    
    # 添加其他安全选项
    existing_opts = container.get('HostConfig', {}).get('SecurityOpt', [])
    for opt in existing_opts or []:
        if opt not in security_opt:
            security_opt.append(opt)
    
    return security_opt


def convert_healthcheck(container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """转换健康检查配置"""
    health_config = container.get('Config', {}).get('Healthcheck')
    
    if not health_config:
        return None
    
    healthcheck = {}
    
    # 测试命令
    test = health_config.get('Test', [])
    if test:
        if len(test) >= 2 and test[0] == 'CMD-SHELL':
            # CMD-SHELL 格式
            full_command = ' '.join(test[1:])
            healthcheck['test'] = ['CMD-SHELL', full_command]
        elif len(test) >= 2 and test[0] == 'CMD':
            # CMD 格式
            healthcheck['test'] = test
        elif len(test) == 1:
            # 简单命令
            healthcheck['test'] = test[0]
        else:
            healthcheck['test'] = test
    
    # 时间间隔转换（纳秒到秒）
    def ns_to_duration(ns: Optional[int]) -> Optional[str]:
        if ns is None:
            return None
        seconds = ns // 1_000_000_000
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        else:
            return f"{seconds // 3600}h"
    
    interval = health_config.get('Interval')
    if interval:
        healthcheck['interval'] = ns_to_duration(interval)
    
    timeout = health_config.get('Timeout')
    if timeout:
        healthcheck['timeout'] = ns_to_duration(timeout)
    
    start_period = health_config.get('StartPeriod')
    if start_period:
        healthcheck['start_period'] = ns_to_duration(start_period)
    
    retries = health_config.get('Retries')
    if retries:
        healthcheck['retries'] = retries
    
    disable = health_config.get('Disable')
    if disable:
        healthcheck['disable'] = True
    
    return healthcheck if healthcheck else None


def analyze_container_dependencies(containers: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    分析容器间的依赖关系
    
    Returns:
        容器名称到依赖列表的映射
    """
    dependencies = {}
    container_names = {c.get('Name', '').lstrip('/') for c in containers}
    
    for container in containers:
        name = container.get('Name', '').lstrip('/')
        deps = set()
        
        # 从 Links 分析
        links = container.get('HostConfig', {}).get('Links', [])
        for link in links or []:
            linked_name = link.split(':')[0].lstrip('/')
            if linked_name in container_names and linked_name != name:
                deps.add(linked_name)
        
        # 从网络模式分析
        network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
        if network_mode.startswith('container:'):
            dep_name = network_mode.split(':')[1]
            if dep_name in container_names:
                deps.add(dep_name)
        
        if deps:
            dependencies[name] = sorted(list(deps))
    
    return dependencies


def group_containers_by_network(containers: List[Dict[str, Any]], 
                                 networks: Dict[str, Any]) -> List[List[str]]:
    """
    根据网络关系对容器进行分组
    
    Args:
        containers: 容器列表
        networks: 网络信息
    
    Returns:
        容器 ID 分组列表
    """
    # 初始化数据结构
    network_groups = defaultdict(list)
    container_links = defaultdict(list)
    special_network_containers = []
    
    # 收集每个容器的网络信息
    for container in containers:
        container_id = container.get('Id', '')
        container_name = container.get('Name', '').lstrip('/')
        network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
        
        # 特殊网络模式（host, bridge）单独处理
        if network_mode in ['bridge', 'host']:
            special_network_containers.append(container_id)
            continue
        
        # 收集自定义网络
        container_networks = container.get('NetworkSettings', {}).get('Networks', {})
        for network_name in container_networks.keys():
            if network_name not in ['bridge', 'host', 'none']:
                network_groups[network_name].append(container_id)
        
        # 收集链接
        links = container.get('HostConfig', {}).get('Links', [])
        for link in links or []:
            linked_name = link.split(':')[0].lstrip('/')
            container_links[container_id].append(linked_name)
    
    # 合并有共同网络的容器组
    merged_groups = []
    processed_networks = set()
    
    for network_name, container_ids in network_groups.items():
        if network_name in processed_networks:
            continue
        
        group = set(container_ids)
        processed_networks.add(network_name)
        
        # 查找有重叠容器的其他网络
        for other_network, other_ids in network_groups.items():
            if other_network not in processed_networks:
                if any(cid in group for cid in other_ids):
                    group.update(other_ids)
                    processed_networks.add(other_network)
        
        merged_groups.append(list(group))
    
    # 处理通过链接连接的容器
    for container_id, linked_names in container_links.items():
        # 检查容器是否已经在某个组中
        existing_group_idx = None
        for i, group in enumerate(merged_groups):
            if container_id in group:
                existing_group_idx = i
                break
        
        # 查找链接的容器 ID
        linked_ids = set()
        for name in linked_names:
            for c in containers:
                if c.get('Name', '').lstrip('/') == name:
                    linked_ids.add(c.get('Id', ''))
        
        if existing_group_idx is not None:
            # 添加到现有组
            merged_groups[existing_group_idx] = list(
                set(merged_groups[existing_group_idx]) | linked_ids
            )
        else:
            # 创建新组
            new_group = {container_id} | linked_ids
            merged_groups.append(list(new_group))
    
    # 处理剩余未分组的容器
    grouped_ids = set()
    for group in merged_groups:
        grouped_ids.update(group)
    
    standalone = [
        c.get('Id', '') for c in containers 
        if c.get('Id', '') not in grouped_ids 
        and c.get('Id', '') not in special_network_containers
    ]
    
    if standalone:
        merged_groups.append(standalone)
    
    # 添加特殊网络容器（每个单独一组）
    for container_id in special_network_containers:
        merged_groups.append([container_id])
    
    return merged_groups


def generate_compose_config(containers: List[Dict[str, Any]],
                           networks: Optional[Dict[str, Any]] = None,
                           config: Optional[D2CConfig] = None) -> Dict[str, Any]:
    """
    生成完整的 Compose 配置
    
    Args:
        containers: 容器列表
        networks: 网络信息
        config: D2C 配置
    
    Returns:
        Compose 配置字典
    """
    if config is None:
        config = D2CConfig()
    
    # 不再添加已废弃的 version 字段
    compose = {
        'services': {},
    }
    
    # 转换每个容器为服务
    for container in containers:
        container_name = container.get('Name', '').lstrip('/')
        service_name = re.sub(r'[^a-zA-Z0-9_]', '_', container_name)
        
        service = convert_container_to_service(container, config, networks)
        compose['services'][service_name] = service
    
    # 分析依赖关系并添加 depends_on
    dependencies = analyze_container_dependencies(containers)
    if dependencies:
        for service_name, service in compose['services'].items():
            container_name = service.get('container_name', '')
            if container_name in dependencies:
                deps = dependencies[container_name]
                # 转换为服务名
                dep_services = [
                    re.sub(r'[^a-zA-Z0-9_]', '_', d) 
                    for d in deps
                ]
                service['depends_on'] = dep_services
    
    # 收集使用的网络
    used_networks = set()
    for container in containers:
        container_networks = container.get('NetworkSettings', {}).get('Networks', {})
        for network_name in container_networks.keys():
            if network_name not in ['bridge', 'host', 'none']:
                used_networks.add(network_name)
    
    # 添加网络配置
    if used_networks:
        compose['networks'] = {}
        for network_name in used_networks:
            # 对于 compose 创建的默认网络，不设置 external
            if '_default' in network_name:
                compose['networks'][network_name] = {'external': True}
            else:
                compose['networks'][network_name] = {}
    
    return compose


if __name__ == '__main__':
    # 测试转换器
    from utils.docker_utils import get_containers, get_networks
    
    print("测试容器到 Compose 转换:")
    
    containers = get_containers()
    networks = get_networks()
    config = D2CConfig()
    
    if containers:
        print(f"\n找到 {len(containers)} 个容器")
        
        # 转换第一个容器
        test_container = containers[0]
        service = convert_container_to_service(test_container, config, networks)
        
        print(f"\n容器 '{test_container.get('Name', '').lstrip('/')}' 的服务配置:")
        import json
        print(json.dumps(service, indent=2, ensure_ascii=False))
    
    # 测试分组
    print("\n\n测试容器分组:")
    groups = group_containers_by_network(containers, networks)
    print(f"共 {len(groups)} 个组")
    for i, group in enumerate(groups):
        print(f"  组 {i+1}: {len(group)} 个容器")
