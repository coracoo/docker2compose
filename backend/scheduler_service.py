#!/usr/bin/env python3
"""
D2C 调度器服务 - 独立进程版本
提供更健壮的定时任务管理
"""

import os
import sys
import json
import time
import signal
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from apscheduler.util import undefined

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import D2CConfig, ConfigManager
from converter import generate_compose_config, convert_container_to_service, group_containers_by_network
from utils.docker_utils import get_containers, get_networks
from utils.yaml_utils import dump_compose_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('D2CScheduler')

# PID 文件
PID_FILE = Path('/tmp/d2c_scheduler.pid')
STATUS_FILE = Path('/tmp/d2c_scheduler.status')


class SchedulerService:
    """调度器服务 - 独立进程运行"""
    
    def __init__(self, config: D2CConfig):
        self.config = config
        self.scheduler: Optional[BackgroundScheduler] = None
        self.running = False
        self._shutdown_event = threading.Event()
        
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def shutdown_handler(signum, frame):
            logger.info(f"收到信号 {signum}，准备退出...")
            self._shutdown_event.set()
        
        def reload_handler(signum, frame):
            logger.info(f"收到信号 {signum}，准备重载配置...")
            self._reload_config()
        
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGHUP, reload_handler)
    
    def _update_status(self):
        """更新状态文件"""
        status = {
            'running': self.running,
            'cron': self.config.cron,
            'pid': os.getpid(),
            'started_at': datetime.now().isoformat(),
            'last_update': datetime.now().isoformat()
        }
        
        # 获取下次执行时间
        if self.scheduler:
            try:
                job = self.scheduler.get_job('d2c_backup')
                if job and job.next_run_time:
                    status['next_run'] = job.next_run_time.isoformat()
            except Exception:
                pass
        
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(status, f)
        except Exception as e:
            logger.error(f"更新状态文件失败: {e}")
    
    def run_task(self):
        """执行备份任务 - 按网络分组生成多个 compose 文件"""
        try:
            logger.info("=" * 50)
            logger.info("开始执行定时备份任务")
            logger.info(f"当前时间: {datetime.now().isoformat()}")
            logger.info(f"当前配置: CRON={self.config.cron}, TZ={self.config.timezone}")
            
            timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M")
            output_dir = f"{self.config.output_dir}/{timestamp}"
            os.makedirs(output_dir, exist_ok=True)
            
            containers = get_containers()
            if not containers:
                logger.warning("未找到 Docker 容器")
                return
            
            logger.info(f"找到 {len(containers)} 个容器")
            
            networks = get_networks()
            logger.info(f"找到 {len(networks)} 个网络")
            
            # 按网络分组容器
            from converter import group_containers_by_network
            logger.info("开始按网络分组容器...")
            container_groups = group_containers_by_network(containers, networks)
            logger.info(f"容器分组完成，共 {len(container_groups)} 个分组")
            
            # 打印每个组的信息
            for i, group in enumerate(container_groups):
                logger.info(f"  组 {i+1}: {len(group)} 个容器")
                for cid in group[:3]:  # 只显示前3个
                    for c in containers:
                        if c['Id'] == cid:
                            logger.info(f"    - {c['Name'].lstrip('/')}")
                            break
            
            # 为每个组生成单独的 compose 文件
            generated_files = []
            for i, group in enumerate(container_groups):
                file_path = self._generate_compose_for_group(
                    group, containers, networks, output_dir, i + 1
                )
                if file_path:
                    generated_files.append(file_path)
                    logger.info(f"第 {i+1} 组备份完成: {os.path.basename(file_path)}")
            
            logger.info(f"备份完成，共生成 {len(generated_files)} 个文件:")
            for f in generated_files:
                logger.info(f"  - {f}")
            
            # 记录执行日志
            self._log_execution(True, f"备份 {len(containers)} 个容器到 {output_dir}，生成 {len(generated_files)} 个 compose 文件", output_dir)
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"任务执行失败: {e}")
            self._log_execution(False, str(e))
    
    def _generate_compose_for_group(self, group: list, all_containers: list, 
                                     networks: dict, output_dir: str, group_index: int) -> str:
        """为单个容器组生成 compose 文件"""
        import re
        
        compose = {
            'version': '3.8',
            'services': {},
        }
        
        # 收集使用的网络
        used_networks = set()
        for container_id in group:
            for container in all_containers:
                if container['Id'] == container_id:
                    for network_name in container.get('NetworkSettings', {}).get('Networks', {}):
                        if network_name not in ['bridge', 'host', 'none']:
                            used_networks.add(network_name)
        
        if used_networks:
            compose['networks'] = {}
            for network in used_networks:
                if '_default' in network or network.startswith('bridge') or network.startswith('host'):
                    compose['networks'][network] = {'external': True}
                else:
                    compose['networks'][network] = {}
        
        # 添加服务配置
        for container_id in group:
            for container in all_containers:
                if container['Id'] == container_id:
                    container_name = container['Name'].lstrip('/')
                    service_name = re.sub(r'[^a-zA-Z0-9_]', '_', container_name)
                    compose['services'][service_name] = convert_container_to_service(
                        container, self.config, networks
                    )
        
        # 生成文件名
        if len(group) == 1:
            for container in all_containers:
                if container['Id'] == group[0]:
                    filename = f"{container['Name'].lstrip('/')}.yaml"
                    break
        else:
            # 根据网络类型生成文件名
            group_network_type = None
            macvlan_network_name = None
            
            for container_id in group:
                for container in all_containers:
                    if container['Id'] == container_id:
                        network_mode = container.get('HostConfig', {}).get('NetworkMode', '')
                        if network_mode == 'host':
                            group_network_type = 'host'
                            break
                        for network_name, network_config in container.get('NetworkSettings', {}).get('Networks', {}).items():
                            if network_name in networks and networks[network_name].get('Driver') == 'macvlan':
                                group_network_type = 'macvlan'
                                macvlan_network_name = network_name
                                break
                        if group_network_type:
                            break
                if group_network_type:
                    break
            
            if group_network_type == 'host':
                filename = "host-group.yaml"
            elif group_network_type == 'macvlan' and macvlan_network_name:
                filename = f"{macvlan_network_name}-group.yaml"
            else:
                for container in all_containers:
                    if container['Id'] == group[0]:
                        prefix = container['Name'].lstrip('/').split('_')[0]
                        filename = f"{prefix}-group.yaml"
                        break
        
        # 生成 YAML
        yaml_content = dump_compose_config(compose)
        
        file_path = os.path.join(output_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        return file_path
    
    def _log_execution(self, success: bool, message: str, output_dir: Optional[str] = None):
        """记录执行历史"""
        try:
            log_file = Path('/app/logs/executions.json')
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            executions = []
            if log_file.exists():
                with open(log_file, 'r') as f:
                    executions = json.load(f)
            
            executions.insert(0, {
                'timestamp': datetime.now().isoformat(),
                'success': success,
                'message': message,
                'output_dir': output_dir
            })
            
            # 只保留最近 100 条
            executions = executions[:100]
            
            with open(log_file, 'w') as f:
                json.dump(executions, f, indent=2)
                
        except Exception as e:
            logger.error(f"记录执行日志失败: {e}")
    
    def parse_cron(self, cron_expr: str) -> Optional[CronTrigger]:
        """解析 CRON 表达式"""
        if cron_expr in ('once', 'manual'):
            return None
        
        parts = cron_expr.split()
        
        # 获取时区
        try:
            from pytz import timezone
            tz = timezone(self.config.timezone)
        except Exception:
            from pytz import utc
            tz = utc
        
        if len(parts) == 5:
            minute, hour, day, month, day_of_week = parts
            return CronTrigger(
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=day_of_week,
                timezone=tz
            )
        elif len(parts) == 6:
            second, minute, hour, day, month, day_of_week = parts
            return CronTrigger(
                second=second, minute=minute, hour=hour,
                day=day, month=month, day_of_week=day_of_week,
                timezone=tz
            )
        
        return None
    
    def start(self):
        """启动调度器服务"""
        logger.info("=" * 50)
        logger.info("D2C 调度器服务启动")
        logger.info(f"CRON: {self.config.cron}")
        logger.info(f"时区: {self.config.timezone}")
        logger.info(f"输出目录: {self.config.output_dir}")
        logger.info(f"当前时间: {datetime.now().isoformat()}")
        
        self._setup_signal_handlers()
        
        # 检查是否手动模式
        if self.config.cron == 'manual':
            logger.info("手动模式，不启动定时任务")
            self._write_pid()
            self._wait_for_shutdown()
            return
        
        # 检查是否一次性执行
        if self.config.cron == 'once':
            logger.info("一次性执行模式")
            self.run_task()
            return
        
        # 创建调度器
        logger.info(f"正在解析 CRON 表达式: {self.config.cron}")
        trigger = self.parse_cron(self.config.cron)
        if not trigger:
            logger.error(f"无效的 CRON 表达式: {self.config.cron}")
            return
        logger.info("CRON 表达式解析成功")
        
        logger.info("正在创建调度器...")
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(
            self.run_task,
            trigger=trigger,
            id='d2c_backup',
            name='D2C Backup Task'
        )
        logger.info("任务已添加到调度器")
        
        logger.info("正在启动调度器...")
        self.scheduler.start()
        self.running = True
        self._write_pid()
        logger.info(f"PID 文件已写入: {PID_FILE}")
        
        # 获取下次执行时间
        job = self.scheduler.get_job('d2c_backup')
        if job and job.next_run_time:
            logger.info(f"下次执行时间: {job.next_run_time}")
        else:
            logger.warning("无法获取下次执行时间")
        
        logger.info("调度器已启动，等待任务执行...")
        logger.info("=" * 50)
        
        # 主循环 - 定期更新状态文件
        try:
            while not self._shutdown_event.is_set():
                self._update_status()
                time.sleep(5)
        except Exception as e:
            logger.error(f"主循环异常: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止调度器服务"""
        logger.info("停止调度器服务...")
        self.running = False
        
        if self.scheduler:
            try:
                self.scheduler.shutdown(wait=True)
            except Exception as e:
                logger.error(f"停止调度器异常: {e}")
        
        self._remove_pid()
        logger.info("调度器服务已停止")
    
    def _write_pid(self):
        """写入 PID 文件"""
        try:
            with open(PID_FILE, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.error(f"写入 PID 文件失败: {e}")
    
    def _remove_pid(self):
        """移除 PID 文件"""
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception as e:
            logger.error(f"移除 PID 文件失败: {e}")
    
    def _wait_for_shutdown(self):
        """等待关闭信号"""
        while not self._shutdown_event.is_set():
            self._update_status()
            time.sleep(5)
    
    def _reload_config(self):
        """重载配置（热更新）"""
        try:
            logger.info("=" * 50)
            logger.info("开始重载配置...")
            
            # 重新加载配置
            config_manager = ConfigManager()
            new_config = config_manager.load(force=True)
            old_cron = self.config.cron
            self.config = new_config
            
            logger.info(f"配置已重载: TZ={self.config.timezone}, NETWORK={self.config.network}")
            logger.info(f"网络配置: {self.config.network}, Healthcheck: {self.config.show_healthcheck}, CapAdd: {self.config.show_cap_add}")
            logger.info(f"环境过滤: {self.config.env_filter_keywords}")
            
            # 如果 CRON 表达式变化了，需要重新调度任务
            if old_cron != self.config.cron:
                logger.info(f"CRON 表达式变化: {old_cron} -> {self.config.cron}")
                
                # 检查是否为 manual 或 once 模式
                if self.config.cron in ('manual', 'once'):
                    logger.info(f"切换到 {self.config.cron} 模式，停止调度器")
                    self.stop()
                    return
                
                # 重新解析 CRON 表达式
                new_trigger = self.parse_cron(self.config.cron)
                if not new_trigger:
                    logger.error(f"无效的 CRON 表达式: {self.config.cron}")
                    return
                
                # 重新调度任务
                if self.scheduler:
                    try:
                        # 移除旧任务
                        self.scheduler.remove_job('d2c_backup')
                        logger.info("已移除旧任务")
                        
                        # 添加新任务
                        self.scheduler.add_job(
                            self.run_task,
                            trigger=new_trigger,
                            id='d2c_backup',
                            name='D2C Backup Task'
                        )
                        logger.info(f"已添加新任务，CRON: {self.config.cron}")
                        
                        # 获取下次执行时间
                        job = self.scheduler.get_job('d2c_backup')
                        if job and job.next_run_time:
                            logger.info(f"下次执行时间: {job.next_run_time}")
                    except Exception as e:
                        logger.error(f"重新调度任务失败: {e}")
                        return
                
                logger.info("调度器已更新")
            else:
                logger.info("CRON 表达式未变化，无需更新调度器")
            
            self._update_status()
            logger.info("配置重载完成")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"重载配置失败: {e}")


def is_running() -> bool:
    """检查调度器是否正在运行"""
    if not PID_FILE.exists():
        return False
    
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # 检查进程是否存在
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return False


def start_service(config_path: str = '/app/config/config.json'):
    """启动调度器服务"""
    import fcntl
    
    # 使用文件锁确保只有一个实例启动
    lock_file = Path('/tmp/d2c_scheduler.lock')
    try:
        with open(lock_file, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            if is_running():
                logger.warning("调度器服务已在运行")
                return
            
            logger.info(f"正在加载配置: {config_path}")
            config_manager = ConfigManager(config_path)
            config = config_manager.load()
            
            logger.info(f"配置加载完成: CRON={config.cron}, TZ={config.timezone}")
            
            service = SchedulerService(config)
            service.start()
            
    except (IOError, OSError) as e:
        logger.error(f"获取调度器锁失败: {e}")
        raise


def stop_service():
    """停止调度器服务"""
    if not PID_FILE.exists():
        logger.info("调度器服务未运行")
        return
    
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        os.kill(pid, signal.SIGTERM)
        logger.info(f"已发送停止信号到进程 {pid}")
        
        # 等待进程退出
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                logger.info("调度器服务已停止")
                return
        
        # 强制终止
        os.kill(pid, signal.SIGKILL)
        logger.warning("强制终止调度器服务")
        
    except Exception as e:
        logger.error(f"停止服务失败: {e}")


def reload_service():
    """重载调度器配置（发送 SIGHUP 信号）"""
    if not PID_FILE.exists():
        logger.info("调度器服务未运行，无需重载")
        return False
    
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # 检查进程是否存在
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            logger.warning("调度器进程不存在")
            return False
        
        # 发送 SIGHUP 信号触发重载
        os.kill(pid, signal.SIGHUP)
        logger.info(f"已发送重载信号到进程 {pid}")
        return True
        
    except Exception as e:
        logger.error(f"重载服务失败: {e}")
        return False


def get_service_status() -> Dict[str, Any]:
    """获取调度器服务状态"""
    status = {
        'running': False,
        'pid': None,
        'cron': None,
        'started_at': None
    }
    
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, 'r') as f:
                status = json.load(f)
        except:
            pass
    
    # 验证进程是否存在
    if status.get('pid'):
        try:
            os.kill(status['pid'], 0)
            status['running'] = True
        except ProcessLookupError:
            status['running'] = False
    
    return status


def run_once_service(config_path: str = '/app/config/config.json'):
    """立即执行一次任务（不启动调度器）"""
    config_manager = ConfigManager(config_path)
    config = config_manager.load()
    
    service = SchedulerService(config)
    
    # 直接运行任务
    logger.info("执行立即运行任务...")
    service.run_task()
    logger.info("任务执行完成")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='D2C 调度器服务')
    parser.add_argument('--config', '-c', default='/app/config/config.json')
    parser.add_argument('action', choices=['start', 'stop', 'reload', 'status', 'run-once'], 
                        default='start', nargs='?')
    
    args = parser.parse_args()
    
    if args.action == 'start':
        start_service(args.config)
    elif args.action == 'stop':
        stop_service()
    elif args.action == 'reload':
        reload_service()
    elif args.action == 'status':
        status = get_service_status()
        print(json.dumps(status, indent=2))
    elif args.action == 'run-once':
        run_once_service(args.config)
