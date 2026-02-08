#!/usr/bin/env python3

import json
import subprocess
import yaml
import os
import re
from collections import defaultdict


def load_config():
    """加载配置，优先从config.json读取，如果没有则从环境变量读取"""
    config_file = '/app/config/config.json'
    
    # 默认配置
    default_config = {
        'CRON': 'once',
        'NETWORK': 'true',
        'SHOW_COMMAND': 'true',
        'SHOW_ENTRYPOINT': 'true',
        'TZ': 'Asia/Shanghai'
    }
    
    # 如果配置文件存在，读取配置文件
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            print(f"从配置文件加载配置: {config_file}")
            # 合并默认配置和文件配置
            config = {**default_config, **file_config}
            return config
        except Exception as e:
            print(f"读取配置文件失败: {e}，使用环境变量")
    
    # 如果配置文件不存在或读取失败，从环境变量读取
    config = {
        'CRON': os.getenv('CRON', default_config['CRON']),
        'NETWORK': os.getenv('NETWORK', default_config['NETWORK']),
        'SHOW_COMMAND': os.getenv('SHOW_COMMAND', default_config['SHOW_COMMAND']),
        'SHOW_ENTRYPOINT': os.getenv('SHOW_ENTRYPOINT', default_config['SHOW_ENTRYPOINT']),
        'TZ': os.getenv('TZ', default_config['TZ'])
    }
    print("从环境变量加载配置")
    return config


def ensure_config_file():
    """确保配置文件存在，如果不存在则创建默认配置文件"""
    config_file = '/app/config/config.json'
    
    # 确保config目录存在
    config_dir = os.path.dirname(config_file)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        print(f"已创建配置目录: {config_dir}")
    
    if not os.path.exists(config_file):
        default_config = {
            "// 配置说明": "以下是D2C的配置选项",
            "// CRON": "定时执行配置,使用标准cron表达式,如'0 2 * * *'(每天凌晨2点),'once'(执行一次后退出)",
            "CRON": "once",
            "// NETWORK": "控制bridge网络配置的显示方式: true(显示) 或 false(隐藏)",
            "NETWORK": "true",
            "// SHOW_COMMAND": "控制command配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_COMMAND": "true",
            "// SHOW_ENTRYPOINT": "控制entrypoint配置的显示方式: true(显示) 或 false(隐藏)",
            "SHOW_ENTRYPOINT": "true",
            "// TZ": "时区设置,如Asia/Shanghai、Europe/London等",
            "TZ": "Asia/Shanghai"
        }
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"已创建默认配置文件: {config_file}")
        except Exception as e:
            print(f"创建配置文件失败: {e}")


def run_command(command):
    """执行shell命令并返回输出
    
    当在容器内运行时，确保命令能够访问宿主机的Docker守护进程
    这需要容器启动时挂载了Docker socket (/var/run/docker.sock)
    """
    # 检查是否在容器内运行
    in_container = os.path.exists('/.dockerenv')
    
    # 如果在容器内运行且命令是docker相关，确保使用宿主机的Docker socket
    if in_container and command.startswith('docker'):
        # 确保Docker socket已挂载
        if not os.path.exists('/var/run/docker.sock'):
            print("错误: 未找到Docker socket挂载。请确保容器启动时使用了 -v /var/run/docker.sock:/var/run/docker.sock")
            return None
    
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        print(f"执行命令出错: {command}")
        print(f"错误信息: {stderr}")
        return None
    return stdout


def get_containers():
    """获取所有运行中的容器信息"""
    cmd = "docker ps -a --format '{{.ID}}'"
    output = run_command(cmd)
    if not output:
        return []
    
    container_ids = output.strip().split('\n')
    containers = []
    
    for container_id in container_ids:
        cmd = f"docker inspect {container_id}"
        output = run_command(cmd)
        if output:
            container_info = json.loads(output)
            # 检查容器的网络配置
            container = container_info[0]
            
            # 如果容器已停止，尝试从容器标签中获取网络信息
            if not container['State']['Running']:
                if 'Labels' in container['Config']:
                    network_labels = {k: v for k, v in container['Config']['Labels'].items() if 'network' in k.lower()}
                    if network_labels:
                        print(f"警告: 容器 {container['Name']} 已停止，但从标签中找到网络配置")
                else:
                    print(f"警告: 容器 {container['Name']} 已停止，可能无法获取完整的网络配置")
            
            containers.append(container)
    
    return containers


def get_networks():
    """获取所有网络信息"""
    cmd = "docker network ls --format '{{.ID}}'"
    output = run_command(cmd)
    if not output:
        return {}
    
    network_ids = output.strip().split('\n')
    networks = {}
    
    for network_id in network_ids:
        cmd = f"docker network inspect {network_id}"
        output = run_command(cmd)
        if output:
            network_info = json.loads(output)
            network_name = network_info[0]['Name']
            # 包含所有网络信息，包括bridge和host，以便后续处理
            networks[network_name] = network_info[0]
            print(f"获取网络信息: {network_name}, 驱动: {network_info[0].get('Driver', 'unknown')}")
    
    return networks


def group_containers_by_network(containers, networks):

    """根据网络关系对容器进行分组"""
    # 初始化网络分组
    network_groups = defaultdict(list)
    container_to_networks = defaultdict(list)
    container_links = defaultdict(list)
    special_network_containers = []
    
    # 记录每个容器所属的网络
    for container in containers:
        container_id = container['Id']
        container_name = container['Name'].lstrip('/')
        
        # 检查网络模式
        network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
        
        # 检查是否使用特殊网络（bridge、host）
        # macvlan网络不再作为特殊网络处理，允许正常分组
        is_special_network = network_mode in ['bridge', 'host']
        
        if is_special_network:
            special_network_containers.append(container_id)
            continue
            
        # 处理网络连接
        for network_name, network_config in container.get('NetworkSettings', {}).get('Networks', {}).items():
            # 排除默认的bridge和host网络
            if network_name not in ['bridge', 'host', 'none']:
                container_to_networks[container_id].append(network_name)
                network_groups[network_name].append(container_id)
        
        # 处理容器链接
        for link in container.get('HostConfig', {}).get('Links', []) or []:
            linked_container = link.split(':')[0].lstrip('/')
            container_links[container_id].append(linked_container)
    
    # 合并有链接关系的容器组
    merged_groups = []
    processed_networks = set()
    
    # 首先基于自定义网络分组
    for network_name, container_ids in network_groups.items():
        if network_name in processed_networks:
            continue
            
        group = set(container_ids)
        processed_networks.add(network_name)
        
        # 查找与当前网络有重叠容器的其他网络
        for other_network, other_containers in network_groups.items():
            if other_network != network_name and not other_network in processed_networks:
                if any(c in group for c in other_containers):
                    group.update(other_containers)
                    processed_networks.add(other_network)
        
        merged_groups.append(list(group))
    
    # 处理通过links连接但没有共享自定义网络的容器
    for container_id, linked_containers in container_links.items():
        if not any(container_id in group for group in merged_groups):
            # 查找所有链接的容器
            linked_group = {container_id}
            for linked in linked_containers:
                for c in containers:
                    if c['Name'].lstrip('/') == linked:
                        linked_group.add(c['Id'])
            
            # 检查是否可以合并到现有组
            merged = False
            for i, group in enumerate(merged_groups):
                if any(c in group for c in linked_group):
                    merged_groups[i] = list(set(group).union(linked_group))
                    merged = True
                    break
            
            if not merged:
                merged_groups.append(list(linked_group))
    
    # 处理剩余的独立容器
    standalone_containers = []
    for container in containers:
        container_id = container['Id']
        if not any(container_id in group for group in merged_groups) and container_id not in special_network_containers:
            standalone_containers.append(container_id)
    
    if standalone_containers:
        merged_groups.append(standalone_containers)
    
    # 为每个bridge、host或macvlan网络的容器创建单独的组
    for container_id in special_network_containers:
        merged_groups.append([container_id])
    
    return merged_groups


def convert_container_to_service(container):
    """将容器配置转换为docker-compose服务配置"""
    service = {}
        
    # 获取配置
    config = load_config()
    network_env = config['NETWORK'].lower() == 'true'
    show_command = config.get('SHOW_COMMAND', 'true').lower() == 'true'
    show_entrypoint = config.get('SHOW_ENTRYPOINT', 'true').lower() == 'true'
    print(f"配置信息: NETWORK={network_env}, SHOW_COMMAND={show_command}, SHOW_ENTRYPOINT={show_entrypoint}")

    # 输出容器信息
    # print(f"容器信息:{container}")

    # 获取容器名称
    container_name = container['Name'].lstrip('/')
    service['container_name'] = container_name
    
    # 获取容器镜像
    service['image'] = container['Config']['Image']
    
    # 获取容器重启策略
    restart_policy = container['HostConfig'].get('RestartPolicy', {})
    if restart_policy and restart_policy.get('Name'):
        if restart_policy['Name'] != 'no':
            service['restart'] = restart_policy['Name']
            if restart_policy['Name'] == 'on-failure' and restart_policy.get('MaximumRetryCount'):
                service['restart'] = f"{restart_policy['Name']}:{restart_policy['MaximumRetryCount']}"
    
    # 获取容器端口映射
    port_mappings = {}
    for port in container['NetworkSettings'].get('Ports', {}) or {}:
        if container['NetworkSettings']['Ports'][port]:
            for binding in container['NetworkSettings']['Ports'][port]:
                # 提取端口信息
                host_ip = binding['HostIp']
                host_port = int(binding['HostPort'])  # 转换为整数
                container_port = port.split('/')[0]  # 移除协议部分
                protocol = port.split('/')[1] if '/' in port else 'tcp'
                
                # 标准化IP地址
                if host_ip in ['0.0.0.0', '::', '']:
                    key = f"{container_port}/{protocol}"
                else:
                    key = f"{host_ip}:{container_port}/{protocol}"
                
                # 使用集合去重
                if key not in port_mappings:
                    port_mappings[key] = set()
                port_mappings[key].add(host_port)
    
    # 处理端口映射，合并连续端口
    ports = []
    for container_port, host_ports in port_mappings.items():
        # 转换为列表并排序
        host_ports = sorted(list(host_ports))
        
        # 查找连续的端口范围
        if len(host_ports) > 0:
            ranges = []
            start = host_ports[0]
            prev = start
            
            for curr in host_ports[1:]:
                if curr != prev + 1:
                    # 如果不连续，添加之前的范围
                    if start == prev:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{prev}")
                    start = curr
                prev = curr
            
            # 添加最后一个范围
            if start == prev:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{prev}")
            
            # 生成端口映射字符串
            if ':' in container_port:  # 包含特定IP
                host_ip, port_proto = container_port.split(':', 1)
                for port_range in ranges:
                    ports.append(f"{host_ip}:{port_range}:{port_proto}")
            else:
                for port_range in ranges:
                    ports.append(f"{port_range}:{container_port}")
    
    if ports:
        service['ports'] = ports
    
    # 环境变量 (忽略PATH)
    if container['Config'].get('Env'):
        env = {}
        for env_var in container['Config']['Env']:
            if '=' in env_var:
                key, value = env_var.split('=', 1)
                if key != 'PATH':  # 忽略PATH环境变量
                    env[key] = value
        if env:
            service['environment'] = env
    
    # 获取容器数据卷，包含volume和bind类型
    volumes = []
    if container['Mounts']:
        for mount in container['Mounts']:
            mode = mount.get('RW', True)
            if mount['Type'] == 'volume':
                source = mount['Name']
                target = mount['Destination']
                # 对于volume类型，只在非默认模式时添加后缀
                if not mode:  # 只读模式
                    volumes.append(f"{source}:{target}:ro")
                else:  # 读写模式（默认），不添加后缀
                    volumes.append(f"{source}:{target}")
            elif mount['Type'] == 'bind':
                source = mount['Source']
                target = mount['Destination']
                # 对于bind类型，只在非默认模式时添加后缀
                if not mode:  # 只读模式
                    volumes.append(f"{source}:{target}:ro")
                else:  # 读写模式（默认），不添加后缀
                    volumes.append(f"{source}:{target}")
    if volumes:
        service['volumes'] = volumes
    
    # 统一网络配置处理
    network_mode = container['HostConfig'].get('NetworkMode', '')
    
    if network_mode == 'host':
        service['network_mode'] = 'host'
    elif network_mode == 'container':
        linked_container = network_mode.split(':')[1]
        service['network_mode'] = f"container:{linked_container}"
    elif network_mode == 'bridge':
        if network_env:
            service['network_mode'] = 'bridge'
    elif network_mode != 'default':
        # 处理自定义网络模式
        if not service.get('networks'):
            service['networks'] = []
        service['networks'].append(network_mode)
    else:
        # 处理网络配置
        networks_config = container['NetworkSettings'].get('Networks', {})
        for network_name, network_config in networks_config.items():
            if network_name not in ['bridge', 'host', 'none']:
                if not service.get('networks'):
                    service['networks'] = {}
                
                # 初始化网络配置
                network_settings = {}
                
                print(f"处理网络 {network_name} 的配置: {json.dumps(network_config, indent=2)}")
                
                # 检查网络驱动类型
                network_driver = networks.get(network_name, {}).get('Driver', '')
                print(f"网络 {network_name} 的驱动类型: {network_driver}")
                
                # 处理 IPv4 配置
                ipam_config = network_config.get('IPAMConfig')
                if ipam_config and isinstance(ipam_config, dict) and ipam_config.get('IPv4Address'):
                    network_settings['ipv4_address'] = ipam_config['IPv4Address']
                    print(f"从 IPAMConfig 获取到 IPv4 地址: {ipam_config['IPv4Address']}")
                elif network_config.get('IPAddress') and network_config['IPAddress'] != "":
                    network_settings['ipv4_address'] = network_config['IPAddress']
                    print(f"从 IPAddress 获取到 IPv4 地址: {network_config['IPAddress']}")
                
                # 处理 IPv6 配置
                if ipam_config and isinstance(ipam_config, dict) and ipam_config.get('IPv6Address'):
                    network_settings['ipv6_address'] = ipam_config['IPv6Address']
                    print(f"从 IPAMConfig 获取到 IPv6 地址: {ipam_config['IPv6Address']}")
                elif network_config.get('GlobalIPv6Address') and network_config['GlobalIPv6Address'] != "":
                    network_settings['ipv6_address'] = network_config['GlobalIPv6Address']
                    print(f"从 GlobalIPv6Address 获取到 IPv6 地址: {network_config['GlobalIPv6Address']}")
                
                # 处理 MAC 地址 - 改进获取逻辑
                mac_address = None
                if network_config.get('MacAddress') and network_config['MacAddress'] != "":
                    mac_address = network_config['MacAddress']
                    print(f"从 MacAddress 获取到 MAC 地址: {mac_address}")
                elif network_config.get('EndpointID'):
                    # 尝试从网络详细信息中获取MAC地址
                    endpoint_id = network_config['EndpointID']
                    print(f"尝试从 EndpointID {endpoint_id} 获取 MAC 地址")
                    # 这里可以添加更多的MAC地址获取逻辑
                
                if mac_address:
                    network_settings['mac_address'] = mac_address
                    print(f"设置 MAC 地址: {mac_address}")
                
                # 如果有网络设置，添加到服务配置中
                if network_settings:
                    # 有特殊配置时使用字典格式
                    if not service.get('networks'):
                        service['networks'] = {}
                    elif isinstance(service['networks'], list):
                        # 如果之前是列表格式，转换为字典格式
                        old_networks = service['networks']
                        service['networks'] = {}
                        for net in old_networks:
                            service['networks'][net] = None
                    service['networks'][network_name] = network_settings
                    print(f"为服务添加网络配置: {network_name} = {network_settings}")
                else:
                    # 对于没有特殊配置的网络，使用列表格式
                    if not service.get('networks'):
                        service['networks'] = []
                    if isinstance(service['networks'], dict):
                        # 如果已经是字典格式，保持字典格式
                        service['networks'][network_name] = None
                    else:
                        # 如果是列表格式，添加到列表中
                        service['networks'].append(network_name)
                    print(f"为服务添加外部网络: {network_name}")
    
    # 添加 extra_hosts - 修复为获取容器的 ExtraHosts 配置
    extra_hosts = container['HostConfig'].get('ExtraHosts', [])
    if extra_hosts:
        service['extra_hosts'] = extra_hosts
    
    # 获取容器之间的link信息，如果有link指向，则组合到group中
    links = container['HostConfig'].get('Links', [])
    if links:
        # 修复链接处理逻辑
        service_links = []
        for link in links:
            # 链接格式通常是 /container_name:/alias
            parts = link.split(':')
            if len(parts) >= 2:
                container_name = parts[0].lstrip('/')
                alias = parts[1].lstrip('/')
                service_links.append(f"{container_name}:{alias}")
            else:
                service_links.append(link.lstrip('/'))
        service['links'] = service_links
    
    # 获取特权模式
    if container['HostConfig'].get('Privileged'):
        service['privileged'] = container['HostConfig']['Privileged']
    
    # 获取硬件设备挂载
    if container['HostConfig'].get('Devices'):
        devices = []
        for device in container['HostConfig']['Devices']:
            devices.append(f"{device['PathOnHost']}:{device['PathInContainer']}:{device['CgroupPermissions']}")
        service['devices'] = devices
    
    # 获取watchtower.enable标签
    if container['Config'].get('Labels'):
        labels = {}
        for label_key, label_value in container['Config']['Labels'].items():
            # 保留所有watchtower相关标签
            if 'watchtower' in label_key.lower():
                labels[label_key] = label_value
            # 保留关于com/org/io开头的标签
            # elif label_key.startswith('com.') or label_key.startswith('org.') or label_key.startswith('io.'):
            #    labels[label_key] = label_value
        if labels:
            service['labels'] = labels
    
    # 获取容器的cap_add权限
    if container['HostConfig'].get('CapAdd'):
        caps = []
        if 'SYS_ADMIN' in container['HostConfig']['CapAdd']:
            service['security_opt'] = ['apparmor:unconfined']
            caps.append('SYS_ADMIN')
        if 'NET_ADMIN' in container['HostConfig']['CapAdd']:
            service['security_opt'] = ['apparmor:unconfined']
            caps.append('NET_ADMIN')
        if caps:
            service['cap_add'] = caps
    
    ''' 
    # 获取容器性能限制配置 ，极空间compose暂不支持性能限制配置，其它NAS可以用0.3版本。
    host_config = container.get('HostConfig', {})
    
    # CPU限制
    cpu_shares = host_config.get('CpuShares')
    cpu_period = host_config.get('CpuPeriod')
    cpu_quota = host_config.get('CpuQuota')
    cpuset_cpus = host_config.get('CpusetCpus')
    
    # 内存限制
    memory = host_config.get('Memory')
    memory_swap = host_config.get('MemorySwap')
    memory_reservation = host_config.get('MemoryReservation')
    
    # 如果设置了资源限制，添加到服务配置中
    if any([cpu_shares, cpu_period, cpu_quota, cpuset_cpus, memory, memory_swap, memory_reservation]):
        deploy = {}
        resources = {'limits': {}, 'reservations': {}}
        
        # CPU配置
        if cpu_quota and cpu_period:
            # 将CPU配额转换为cores数量
            cores = float(cpu_quota) / float(cpu_period)
            resources['limits']['cpus'] = str(cores)
        elif cpu_shares:
            # cpu_shares是相对权重，1024为默认值
            resources['limits']['cpus'] = str(float(cpu_shares) / 1024.0)
        
        if cpuset_cpus:
            resources['limits']['cpus'] = cpuset_cpus
        
        # 内存配置
        if memory and memory > 0:
            resources['limits']['memory'] = memory
        if memory_reservation and memory_reservation > 0:
            resources['reservations']['memory'] = memory_reservation
        
        # 只有当实际设置了资源限制时才添加配置
        if resources['limits'] or resources['reservations']:
            deploy['resources'] = resources
            service['deploy'] = deploy
    '''
    
    # 获取容器的entrypoint配置（根据配置判断是否显示）
    if show_entrypoint:
        entrypoint_config = container['Config'].get('Entrypoint')
        if entrypoint_config:
            if len(entrypoint_config) == 1:
                service['entrypoint'] = entrypoint_config[0]
            else:
                service['entrypoint'] = entrypoint_config
    
    # 获取容器的command配置（根据配置判断是否显示）
    if show_command:
        cmd_config = container['Config'].get('Cmd')
        entrypoint_config = container['Config'].get('Entrypoint')
        if cmd_config:
            # 检查command是否与entrypoint相同，如果相同则不设置command
            if entrypoint_config and cmd_config == entrypoint_config:
                # 如果command和entrypoint相同，只保留entrypoint
                pass
            else:
                # 如果只有一个元素，使用字符串格式；多个元素使用数组格式
                if len(cmd_config) == 1:
                    service['command'] = cmd_config[0]
                else:
                    service['command'] = cmd_config
    
    # 获取容器的健康检查配置
    if container['Config'].get('Healthcheck'):
        healthcheck = {}
        
        # 处理test字段
        test = container['Config']['Healthcheck'].get('Test', [])
        if test:
            # 对于CMD-SHELL类型，需要特殊处理
            if len(test) >= 2 and test[0] == 'CMD-SHELL':
                # 将CMD-SHELL和后续命令合并为两个数组元素：CMD-SHELL和完整命令
                # 修复：确保正确合并为两个元素的数组
                full_command = ' '.join(test[1:])
                healthcheck['test'] = ['CMD-SHELL', full_command]
                print(f"处理healthcheck CMD-SHELL: {healthcheck['test']}")
            elif len(test) == 1 and not test[0].startswith('CMD'):
                # 简单命令使用字符串格式
                healthcheck['test'] = test[0]
            elif len(test) >= 2 and test[0] == 'CMD':
                # 对于CMD类型，保持原数组格式
                healthcheck['test'] = test
            else:
                # 其他情况保持原数组格式
                healthcheck['test'] = test
        
        # 处理时间间隔字段，将纳秒转换为秒
        def convert_nanoseconds_to_duration(ns):
            if ns is None:
                return None
            # Docker的时间间隔通常以纳秒为单位
            seconds = ns // 1000000000
            if seconds < 60:
                return f"{seconds}s"
            elif seconds < 3600:
                minutes = seconds // 60
                return f"{minutes}m"
            else:
                hours = seconds // 3600
                return f"{hours}h"
        
        interval = container['Config']['Healthcheck'].get('Interval')
        if interval:
            healthcheck['interval'] = convert_nanoseconds_to_duration(interval)
            
        timeout = container['Config']['Healthcheck'].get('Timeout')
        if timeout:
            healthcheck['timeout'] = convert_nanoseconds_to_duration(timeout)
            
        retries = container['Config']['Healthcheck'].get('Retries')
        if retries:
            healthcheck['retries'] = retries
        
        if healthcheck:
            service['healthcheck'] = healthcheck
    
    return service


def generate_compose_file(containers_group, all_containers, networks=None, output_dir=None):
    """为一组容器生成docker-compose.yaml文件
    
    Args:
        containers_group: 容器ID列表
        all_containers: 所有容器信息
        networks: 网络信息字典，用于判断网络类型
        output_dir: 输出目录，如果为None则从环境变量获取
    """
    # 如果没有传入networks参数，获取网络信息
    if networks is None:
        networks = get_networks()
    # 使用环境变量中的输出目录，如果未指定则使用默认值
    if output_dir is None:
        output_dir = os.getenv('OUTPUT_DIR', 'compose')
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    compose = {
        'version': '3.8',
        'services': {},
    }
    
    # 添加网络配置
    used_networks = set()
    for container_id in containers_group:
        for container in all_containers:
            if container['Id'] == container_id:
                for network_name in container['NetworkSettings'].get('Networks', {}):
                    if network_name not in ['bridge', 'host', 'none']:
                        used_networks.add(network_name)
    
    if used_networks:
        # 检查网络是否为Docker默认创建的网络（通常包含项目名称）
        # 只有明确的外部网络才设置为external: true
        compose['networks'] = {}
        for network in used_networks:
            # 如果网络名包含下划线且看起来像compose创建的网络，不设置为external
            # 否则设置为external: true
            if '_default' in network or network.startswith('bridge') or network.startswith('host'):
                compose['networks'][network] = {'external': True}
            else:
                # 对于自定义网络，不设置external，让compose自动创建
                compose['networks'][network] = {}
    
    # 添加服务配置
    for container_id in containers_group:
        for container in all_containers:
            if container['Id'] == container_id:
                container_name = container['Name'].lstrip('/')
                service_name = re.sub(r'[^a-zA-Z0-9_]', '_', container_name)
                compose['services'][service_name] = convert_container_to_service(container)
    
    # 生成文件名
    if len(containers_group) == 1:
        for container in all_containers:
            if container['Id'] == containers_group[0]:
                filename = f"{container['Name'].lstrip('/')}.yaml"
                break
    else:
        # 检查容器组的网络类型，生成相应的组名
        group_network_type = None
        macvlan_network_name = None
        
        # 分析容器组中的网络类型
        for container_id in containers_group:
            for container in all_containers:
                if container['Id'] == container_id:
                    network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
                    
                    # 检查是否为host网络
                    if network_mode == 'host':
                        group_network_type = 'host'
                        break
                    
                    # 检查是否为macvlan网络
                    for network_name, network_config in container.get('NetworkSettings', {}).get('Networks', {}).items():
                        if network_name in networks and networks[network_name].get('Driver') == 'macvlan':
                            group_network_type = 'macvlan'
                            macvlan_network_name = network_name
                            break
                    
                    if group_network_type:
                        break
            if group_network_type:
                break
        
        # 根据网络类型生成文件名
        if group_network_type == 'host':
            filename = "host-group.yaml"
        elif group_network_type == 'macvlan' and macvlan_network_name:
            filename = f"{macvlan_network_name}-group.yaml"
        else:
            # 使用第一个容器的名称作为文件名前缀（原有逻辑）
            for container in all_containers:
                if container['Id'] == containers_group[0]:
                    prefix = container['Name'].lstrip('/').split('_')[0]
                    filename = f"{prefix}-group.yaml"
                    break
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 自定义YAML表示类，确保正确的缩进
    class MyDumper(yaml.Dumper):
        def increase_indent(self, flow=False, indentless=False):
            return super(MyDumper, self).increase_indent(flow, False)
        
        def write_line_break(self, data=None):
            super(MyDumper, self).write_line_break(data)
            if len(self.indents) == 1:
                super(MyDumper, self).write_line_break()
    
    # 生成YAML文件，使用自定义的Dumper类
    yaml_content = yaml.dump(compose, Dumper=MyDumper, default_flow_style=False, sort_keys=False, allow_unicode=True, indent=2, width=float('inf'))
    
    # 写入文件
    file_path = os.path.join(output_dir, filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
    
    print(f"已生成 {file_path}")
    return file_path


def generate_compose_for_selected_containers(container_ids):
    """为指定的容器ID列表生成compose配置
    
    Args:
        container_ids: 容器ID列表（可以是短ID）
    
    Returns:
        dict: compose配置字典，如果失败返回None
    """
    print(f"开始为指定容器生成compose配置: {container_ids}")
    
    # 获取所有容器信息
    all_containers = get_containers()
    if not all_containers:
        print("未找到Docker容器")
        return None
    
    # 过滤出指定的容器（支持短ID匹配）
    selected_containers = []
    for container in all_containers:
        container_short_id = container['Id'][:12]
        if container_short_id in container_ids or container['Id'] in container_ids:
            selected_containers.append(container)
    
    if not selected_containers:
        print(f"未找到指定的容器: {container_ids}")
        return None
    
    print(f"找到 {len(selected_containers)} 个匹配的容器")
    
    # 获取网络信息
    networks = get_networks()
    
    # 生成compose配置
    compose = {
        'version': '3.8',
        'services': {},
        'networks': {}
    }
    
    used_networks = set()
    
    # 为每个选中的容器生成服务配置
    for container in selected_containers:
        container_name = container['Name'].lstrip('/')
        service_name = re.sub(r'[^a-zA-Z0-9_]', '_', container_name)
        
        # 生成服务配置
        service_config = convert_container_to_service(container)
        compose['services'][service_name] = service_config
        
        # 收集使用的网络
        for network_name in container['NetworkSettings'].get('Networks', {}):
            if network_name not in ['bridge', 'host', 'none']:
                used_networks.add(network_name)
    
    # 添加网络配置
    for network_name in used_networks:
        if '_default' in network_name or network_name.startswith('bridge') or network_name.startswith('host'):
            compose['networks'][network_name] = {'external': True}
        else:
            compose['networks'][network_name] = {}
    
    # 如果没有网络配置，删除networks部分
    if not compose['networks']:
        del compose['networks']
    
    print(f"成功生成compose配置，包含 {len(compose['services'])} 个服务")
    return compose


def main():
    # 确保配置文件存在
    ensure_config_file()
    
    print("开始读取Docker容器信息...")
    containers = get_containers()
    if not containers:
        print("未找到Docker容器")
        return
    
    print(f"找到 {len(containers)} 个Docker容器")
    
    print("读取网络信息...")
    networks = get_networks()
    print(f"找到 {len(networks)} 个自定义网络")
    
    print("根据网络关系对容器进行分组...")
    container_groups = group_containers_by_network(containers, networks)
    print(f"分组完成，共 {len(container_groups)} 个分组")
    
    # 获取输出目录，优先使用环境变量中的设置
    output_dir = os.getenv('OUTPUT_DIR', 'compose')
    print(f"输出目录: {output_dir}")
    
    print("生成docker-compose文件...")
    generated_files = []
    for i, group in enumerate(container_groups):
        print(f"处理第 {i+1} 组，包含 {len(group)} 个容器")
        file_path = generate_compose_file(group, containers, networks, output_dir)
        generated_files.append(file_path)
    
    print("\n生成完成！生成的文件列表:")
    for file_path in generated_files:
        print(f"- {file_path}")


if __name__ == "__main__":
    main()