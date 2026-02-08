#!/usr/bin/env python3
"""
D2C Docker Utilities
Docker 相关工具函数
"""

import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


class DockerError(Exception):
    """Docker 操作错误"""
    pass


def run_docker_command(command: str, 
                       timeout: int = 30,
                       check_socket: bool = True) -> Optional[str]:
    """
    执行 Docker 命令
    
    Args:
        command: 命令字符串
        timeout: 超时时间（秒）
        check_socket: 是否检查 Docker socket
    
    Returns:
        命令输出，失败返回 None
    
    Raises:
        DockerError: Docker 连接错误
    """
    # 检查 Docker socket
    if check_socket and not Path('/var/run/docker.sock').exists():
        raise DockerError(
            "未找到 Docker socket 挂载。"
            "请确保容器启动时使用了 -v /var/run/docker.sock:/var/run/docker.sock"
        )
    
    # 确保命令以 docker 开头
    if not command.strip().startswith('docker'):
        raise DockerError(f"不安全的命令: {command}")
    
    try:
        # 使用 shlex 分割命令，避免 shell=True 的安全风险
        import shlex
        cmd_parts = shlex.split(command)
        result = subprocess.run(
            cmd_parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            print(f"[ERROR] Docker命令执行失败: {command}")
            print(f"[ERROR] 错误信息: {result.stderr}")
            return None
        
        return result.stdout
        
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Docker命令执行超时: {command}")
        return None
    except Exception as e:
        print(f"[ERROR] Docker命令执行异常: {e}")
        return None


def check_docker_connection() -> Tuple[bool, str]:
    """
    检查 Docker 连接状态
    
    Returns:
        (是否成功, 状态信息)
    """
    # 检查 socket
    if not Path('/var/run/docker.sock').exists():
        return False, "Docker socket 未挂载"
    
    # 测试连接
    output = run_docker_command('docker version --format "{{.Server.Version}}"', 
                                check_socket=False)
    
    if output:
        version = output.strip()
        return True, f"Docker 版本: {version}"
    
    return False, "无法连接到 Docker daemon"


def get_docker_info() -> Dict[str, Any]:
    """
    获取 Docker 系统信息
    
    Returns:
        Docker 信息字典
    """
    output = run_docker_command('docker info --format "{{json .}}"')
    
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            print(f"[ERROR] 解析 Docker 信息失败: {e}")
    
    return {}


def get_containers(all_containers: bool = True) -> List[Dict[str, Any]]:
    """
    获取容器列表
    
    Args:
        all_containers: 是否获取所有容器（包括停止的）
    
    Returns:
        容器信息列表
    """
    # 获取容器 ID 列表
    format_str = "{{.ID}}"
    filter_flag = "-a" if all_containers else ""
    
    cmd = f"docker ps {filter_flag} --format '{format_str}'"
    output = run_docker_command(cmd)
    
    if not output:
        return []
    
    container_ids = [cid.strip() for cid in output.strip().split('\n') if cid.strip()]
    
    if not container_ids:
        return []
    
    # 批量获取所有容器详情（性能优化）
    ids_str = ' '.join(container_ids)
    inspect_output = run_docker_command(f'docker inspect {ids_str}')
    
    if not inspect_output:
        return []
    
    try:
        containers = json.loads(inspect_output)
        return containers if containers else []
    except json.JSONDecodeError as e:
        print(f"[WARNING] 解析容器信息失败: {e}")
        return []


def get_networks() -> Dict[str, Dict[str, Any]]:
    """
    获取网络列表
    
    Returns:
        网络名称到网络信息的映射
    """
    networks = {}
    
    # 获取网络 ID 列表
    cmd = "docker network ls --format '{{.ID}}'"
    output = run_docker_command(cmd)
    
    if not output:
        return networks
    
    network_ids = [nid.strip() for nid in output.strip().split('\n') if nid.strip()]
    
    # 获取每个网络的详细信息
    for network_id in network_ids:
        inspect_output = run_docker_command(f'docker network inspect {network_id}')
        
        if inspect_output:
            try:
                network_info = json.loads(inspect_output)
                if network_info and len(network_info) > 0:
                    network_name = network_info[0].get('Name', '')
                    networks[network_name] = network_info[0]
            except json.JSONDecodeError as e:
                print(f"[WARNING] 解析网络 {network_id} 信息失败: {e}")
    
    return networks


def get_volumes() -> List[Dict[str, Any]]:
    """
    获取卷列表
    
    Returns:
        卷信息列表
    """
    volumes = []
    
    # 获取卷列表
    cmd = "docker volume ls --format '{{.Name}}'"
    output = run_docker_command(cmd)
    
    if not output:
        return volumes
    
    volume_names = [v.strip() for v in output.strip().split('\n') if v.strip()]
    
    # 获取每个卷的详细信息
    for volume_name in volume_names:
        inspect_output = run_docker_command(f'docker volume inspect {volume_name}')
        
        if inspect_output:
            try:
                volume_info = json.loads(inspect_output)
                if volume_info and len(volume_info) > 0:
                    volumes.append(volume_info[0])
            except json.JSONDecodeError as e:
                print(f"[WARNING] 解析卷 {volume_name} 信息失败: {e}")
    
    return volumes


def container_name_to_id(name: str) -> Optional[str]:
    """
    将容器名称转换为 ID
    
    Args:
        name: 容器名称或短 ID
    
    Returns:
        完整容器 ID，失败返回 None
    """
    output = run_docker_command(
        f'docker ps -a --filter "name={name}" --format "{{{{.ID}}}}"'
    )
    
    if output:
        return output.strip().split('\n')[0] if output.strip() else None
    
    return None


def get_container_logs(container_id: str, 
                       tail: int = 100,
                       timestamps: bool = False) -> str:
    """
    获取容器日志
    
    Args:
        container_id: 容器 ID
        tail: 获取最后多少行
        timestamps: 是否包含时间戳
    
    Returns:
        日志内容
    """
    ts_flag = "-t" if timestamps else ""
    cmd = f'docker logs {ts_flag} --tail {tail} {container_id}'
    
    output = run_docker_command(cmd)
    return output or ""


if __name__ == '__main__':
    # 测试 Docker 工具
    print("检查 Docker 连接:")
    connected, info = check_docker_connection()
    print(f"  状态: {'已连接' if connected else '未连接'}")
    print(f"  信息: {info}")
    
    if connected:
        print("\n获取容器列表:")
        containers = get_containers()
        print(f"  找到 {len(containers)} 个容器")
        
        for c in containers[:3]:  # 只显示前3个
            name = c.get('Name', 'unknown').lstrip('/')
            image = c.get('Config', {}).get('Image', 'unknown')
            print(f"    - {name} ({image})")
        
        print("\n获取网络列表:")
        networks = get_networks()
        print(f"  找到 {len(networks)} 个网络")
        
        for name in list(networks.keys())[:3]:
            print(f"    - {name}")
