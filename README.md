# docker2compose

[![Docker Build](https://github.com/Jackie264/docker2compose/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Jackie264/docker2compose/actions/workflows/docker-publish.yml)
[![Tests](https://github.com/Jackie264/docker2compose/actions/workflows/test.yml/badge.svg)](https://github.com/Jackie264/docker2compose/actions/workflows/test.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/jackie264/docker2compose)](https://hub.docker.com/r/jackie264/docker2compose)
[![Docker Image Size](https://img.shields.io/docker/image-size/jackie264/docker2compose/latest)](https://hub.docker.com/r/jackie264/docker2compose)

## 前言

本工具用于读取 NAS 中存量 Docker 容器信息，自动生成对应的 `docker-compose.yaml` 文件。

它会根据容器之间的网络关系（自定义网络或link连接）将相关容器分组，并为每组容器生成一个独立的docker-compose.yaml文件。

# 我的仓库

**1️⃣** ： 中文docker项目集成项目： [https://github.com/coracoo/awesome_docker_cn](https://github.com/coracoo/awesome_docker_cn)

**2️⃣** ： docker转compose：[https://github.com/coracoo/docker2compose](https://github.com/coracoo/docker2compose)

**3️⃣** ： 容器部署iSCSI：[https://github.com/coracoo/d-tgtadm/](https://github.com/coracoo/d-tgtadm/)

**4️⃣** ： 容器端口检查工具： [https://github.com/coracoo/DockPorts/](https://github.com/coracoo/DockPorts)

# 我的频道

### 首发平台——什么值得买：

### [⭐点我关注](https://zhiyou.smzdm.com/member/9674309982/) 

### 微信公众号：

![关注](https://github.com/user-attachments/assets/9a1c4de0-2f08-413f-ab7f-d7d463af1698)

-------------------------------------

## 🆕 v2.0 版本更新

### 新增功能
- **🔐 用户系统**：新增完整的用户系统，默认账号 `admin/admin123`，保护信息安全
- **📊 调度器**：取消了 Cron&Python调度器 并行的方式，统一使用 Python 调度器；设置后需要手动先开启定时任务；
- **📝 日志**：调度器执行日志记录到 `/app/logs/scheduler.log`
- **🎨 前端**：采用了手工画风格的界面；增加搜索功能；优化默认排序
- **🙌 配置参数**：增加了`关键词`过滤；优化了网络、健康检测、入口点、命令、权限的展示选择，现在可以更自由的配置生成的文档

### 代码优化
- 清理冗余文件，减少项目体积
- 优化 GitHub Actions 工作流

-------------------------------------

## 功能特点

- 纯AI打造，有问题提issuse，特殊容器贴原docker cli
- 读取系统中所有Docker容器信息
- 分析容器之间的网络关系（自定义network和link连接）
- 根据网络关系将相关容器分组
- 为每组容器生成对应的docker-compose.yaml文件（根据首个容器名称）
- **智能时区管理**：自动读取配置文件中的时区设置并应用到容器系统，确保定时任务在正确时区执行
- 支持提取容器的各种配置，包括：
  - 容器名称
  - 镜像
  - 端口映射
  - 环境变量
  - 数据卷(volume/bind)
  - 网络(host/bridge/macvlan单独配置，其它网络根据名称在一起)
  - 重启策略
  - 特权模式
  - 硬件设备挂载
  - cap_add 能力
  - command和entrypoint
  - 健康检测
  - 其他配置等等

## 🌐全新的 Web UI 访问

部署完成后，可通过浏览器访问Web界面：
- 本地访问：`http://localhost:5000`
- 局域网访问：`http://你的IP地址:5000`

### Web UI功能特点

- 📊 **容器管理**：实时查看所有Docker容器状态，按网络关系自动分组
- 📄 **Compose预览**：直接在界面中查看生成的docker-compose.yaml文件内容
- ⏰ **调度器监控**：实时监控定时任务状态，查看执行日志
- 🚀 **立即执行**：一键执行compose文件生成任务
- 🗂️ **文件管理**：浏览和管理生成的compose文件目录
- 📝 **日志查看**：查看详细的执行日志，支持清空日志功能
- 🎨 **响应式设计**：采用三栏式布局（容器列表:文件列表:编辑器 = 1:1:2），适配不同屏幕尺寸
- 🔘 **优化界面**："关于我"按钮采用白底设计，提供更好的视觉对比度


**🔻项目首页**
<img width="1859" height="903" alt="总览" src="https://github.com/user-attachments/assets/d43eec83-16da-4a6a-9fff-11ee064a109d" />

**🔻可视化配置编辑**
<img width="1838" height="897" alt="系统设置" src="https://github.com/user-attachments/assets/81a52a1b-7621-4dc5-92fb-c3097256659e" />

**🔻定时任务管理**
<img width="1847" height="872" alt="定时任务" src="https://github.com/user-attachments/assets/37c0a299-39bd-4456-9cf1-537afd31f61c" />

### 配置文件说明 (/app/config.json)

- `CRON`: 定时执行配置，支持5位\6位Cron规则，示例：`0 2 * * *`（每天凌晨2点执行）
  - 默认值：`0 */12 * * *`（每天0点起，每天12小时执行一次）
  - `once`: 执行一次后退出

- `NETWORK`: 控制bridge网络配置的显示方式
  - `true`: 默认值，在生成的compose.yaml中显式添加 `network_mode: bridge` 配置
  - `false`: 隐藏bridge网络配置，不在compose.yaml中显示 `network_mode: bridge`（因为bridge是Docker默认网络模式）

- `TZ`: 时区设置，影响容器内系统时间和定时任务执行
  - 默认值：`Asia/Shanghai`
  - 支持标准时区格式：`Asia/Shanghai`、`Europe/London`、`America/New_York` 等
  - 容器启动时会自动应用此时区设置到系统中
  - 如果指定的时区文件不存在，系统会显示警告并使用UTC时区

### 输出目录说明
- `/app/compose`: 脚本输出目录，默认值为`/app/compose`
- `/app/compose/YYYY_MM_DD_HH_MM`: 定时任务输出目录，格式为`YYYY_MM_DD_HH_MM`，例如`2023_05_04_15_00`
- `/app/logs`：定时任务日志

### 输出说明

- 对于单个独立的容器，生成的文件名格式为：`{容器名}.yaml`
- 对于有网络关系的容器组，生成的文件名格式为：`{第一个容器名前缀}-group.yaml`
- 所有生成的文件都会保存在`compose/时间戳`目录下

### 注意事项

- 该工具需要Docker命令行权限才能正常工作
- 生成的docker-compose.yaml文件可能需要手动调整以满足特定需求
- 通过Docker运行时，会将宿主机的Docker套接字挂载到容器中，以便获取容器信息
- 工具支持定时执行，默认`once`（只执行一次），可通过CRON环境变量自定义执行时间
- **时区配置重要提醒**：
  - 容器启动时会自动读取 `config.json` 中的TZ配置并应用到系统
  - 如果定时任务时间不准确，请检查TZ配置是否正确
  - 可通过 `docker exec d2c-container date` 命令验证容器内时区是否正确
- 关于Macvlan网络，DHCP的理论上会展示`macvlan:{}`，
- 对于使用默认bridge网络但没有显式link的容器，它们可能会被分到不同的组中
- 工具会将自定义网络标记为`external: true`，因为它假设这些网络已经存在

-------------------------------------

# 使用方法

## 1、通过compose部署（推荐）

启用前确保系统安装了docker

**🔻docker cli启动**
```bash
docker run -itd --name docker2compose \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /{path}/d2c/compose:/app/compose \
  -v /{path}/d2c/logs:/app/logs \
  -v /{path}/d2c/config:/app/config \
  -p 5000:5000 \
  -e TZ=Asia/Shanghai \
  coracoo/docker2compose:latest
```

**🔻docker compose启动**
```yaml
services:
  d2c:
    image: coracoo/docker2compose:latest
    container_name: docker2compose
    ports:
      - "5000:5000"  # Web UI端口
    environment:
      - TZ=Asia/Shanghai  # 可选，时区设置
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /{path}/d2c/compose:/app/compose
      - /{path}/d2c/logs:/app/logs
      - /{path}/d2c/config:/app/config
```

## 2、直接运行（需要Python环境）

如果您的系统已安装Python环境，也可以直接运行：

1. 确保系统中已安装Python 3和Docker
2. 确保脚本有执行权限

```bash
chmod +x d2c.py
```

3. 安装python所需的依赖包

```bash
pip install -r requirements.txt
```

4. 运行脚本

```bash
./run.sh
```

5. 脚本会在当前目录下创建一个`compose`文件夹，并在其中生成docker-compose.yaml文件

## 3、运行测试

项目现在包含了完整的测试套件，用于验证核心功能：

```bash
# 安装测试依赖
pip install -r requirements.txt

# 运行所有测试
python run_tests.py

# 或者使用pytest直接运行
python -m pytest tests/ -v
```

测试套件包含40个综合测试，覆盖：
- 配置管理和验证
- 容器分析和分组逻辑
- CRON表达式处理
- 调度器功能
- Web UI工具函数

详细信息请参阅 `tests/README.md`

## 4、Docker镜像

### 4.1 镜像版本

项目支持自动构建多平台Docker镜像并推送到Docker Hub：

```bash
- **Docker Hub**: `coracoo/docker2compose`
- **GitHub Container Registry**: `ghcr.io/coracoo/docker2compose`
```

### 4.1 支持的平台
- `linux/amd64`
- `linux/arm64` 
- `linux/arm/v7`

### 4.2 自动构建
- 每次推送到master分支时自动构建
- 创建版本标签时自动构建并发布
- 构建前会自动运行完整测试套件
- 详细设置说明请参阅 `docs/DOCKER_HUB_SETUP.md`

-------------------------------------

# 更新说明

## 2025-07-30(v1.1.5)
- 增加了完整的test套件（@Jackie264）
- 增加了docker.hub镜像源（@jackie264）
- 优化了`entrypoint.sh`，优化了部分`icon`图标更新（@jackie264）
- 使用 Dependabot 自动更新所需的依赖项（@jackie264）
- 修复部分CRON会导致调度器异常以及无法重启的问题（@jackie264）

## 2025-07-12(v1.1.4)
- 修复`Dockerfile.github`中未添加`procps`以来导致CRON无法识别启动的问题
- 优化@Jackie264提到，关于PID 1进程管理问题：新增 `entrypoint.sh` 脚本专注于PID 1进程管理，不会自动启动调度器
- 实现Web UI进程的监控和重启机制，调度器由Web UI界面管理
- 添加优雅的容器停止处理，确保所有子进程正确清理
- 避免once模式下的调度器冲突，提升容器健壮性和一致性
- 解决子进程意外退出导致容器停止的问题
- 修复容器内时区显示为UTC而非配置时区的问题

## 2025-07-09(v1.1.3)
- 🎨 **UI布局优化**：
  - 重新设计顶部导航栏为三栏式布局：左侧"关于我"按钮、中间Logo和项目名称居中、右侧功能按钮
  - 调整主内容区域布局比例为 1:1:2（容器列表:文件列表:编辑器），解决编辑器过宽问题
  - 优化响应式设计，在移动端（768px以下）自动切换为垂直堆叠布局
  - 修复设置保存、Cron异常的问题。

## 2025-07-04(v1.1.2)
  - 改进了Host网络和Macvlan网络的compose文件命名规则
    - Host网络容器组现在生成`host-group.yaml`文件名
    - Macvlan网络容器组现在生成`{网络名}-group.yaml`文件名
  - 增加配置文件`config.json`的持久化读取，现在在`/app/config/config.json`目录下
  - 优化compose编辑器，现在保存compose文件后会自动刷新文件列表
  - 修复dockerfile中路径映射不生效、flask缺失的问题
  - 优化切换compose文件的视觉效果
  - 修复任务计划、生成全量Compose功能，时区配置不起作用的问题
  - 优化任务计划中，`once`参数启动任务、任务停止（未启动）时的提示内容
  - 修复任务计划中，缺失`gnupg`导致无法正确识别CRON和调度器状态的问题

## 2025-07-03(v1.1.0)
- 🎉 **新增Web UI界面**：
  - 采用全新得现代化的图形界面设计，原CLI模式保留不变。
  - 左侧为容器分组展示，支持按网络关系自动分组，包含运行状态、容器数量等。
  - 中间为文件列表，展示`/app/compose`目录下所有得`yaml`文件。
  - 右侧是Compose编辑区域，支持勾选docker整合compose。
  - 新增设置页面，用来编辑配置文件。
  - 新增任务计划页面，用来执行定时任务。
  - 新增日志查看页面，用来查看任务执行日志。

- 🔧 **修改代码逻辑**：
  - 去除环境变量，所有参数通过`/app/config.json`来配置（参考前面得配置文件说明）。
  - 新增系统CRON和Python调度器来执行CRON任务，彻底解决5、6位CRON的问题。
  - 初次登录会自动生成所有得容器yaml文件，保存在`/app/compose`目录下。

- 🐛 **修复已知问题**：
  - 解决多个稳定性和兼容性问题
  - 改进错误处理和异常捕获机制
  - 优化代码注释和函数级文档

## 2025-07-03(v1.0.5)
- 修复了volumes挂载权限处理逻辑，移除不必要的:rw后缀，只在只读模式时添加:ro后缀
- 优化了healthcheck的CMD-SHELL格式处理，确保生成符合Docker Compose规范的配置
- 改进了volumes处理逻辑，使生成的compose文件更简洁，符合Docker Compose最佳实践
- 添加了healthcheck处理过程的调试日志输出，便于跟踪问题
- 完善了代码注释和错误处理逻辑
- 修复了cron表达式的时区问题，确保定时任务在正确的时区执行
- 修复了extra_hosts配置处理，现在能够正确从容器的HostConfig.ExtraHosts获取配置

## 2025-06-04(v1.0.4)
- 改进了macvlan网络配置处理，现在能够正确导出IPv4地址、IPv6地址和MAC地址
- 优化了volumes处理逻辑，支持中文路径，确保在生成的compose文件中保留原始路径
- 修复了链接处理逻辑，现在能够正确处理容器链接格式
- 改进了YAML生成逻辑，使用自定义Dumper类确保正确的缩进格式
- 添加了更多错误处理和日志输出，便于调试和跟踪处理过程

## 2025-05-05(v1.0.3)
- 添加了command、entrypoint的生成，若环境变量配置NAS配置为ZOS，则不生成
- 添加了环境变量：NAS、CRON、TZ、NETWORK
- 支持定时执行，支持标准CRON表达式；支持一次性任务执行（CRON=once）
- 重新修改yaml文件生成路径，在`./compose/`路径下，按`YYYY-MM-DD-HH-MM`时间戳组织输出文件
- 完善日志输出内容；完善README.md
- 创建Github Action，自动构建并推送到github和阿里云
- 适配 amd64/arm64/arm7 架构

