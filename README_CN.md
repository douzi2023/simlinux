<div align="right">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</div>

# SimLinux 🐧

> **基于大模型驱动的教学用模拟 Linux SSH 终端**  
> 专为 Linux 初学者打造：通过标准 SSH 客户端连接，拥有原生终端操作体验，在安全无害的模拟沙盒中自由练习 Linux 命令。

---

## ✨ 核心特性

- **🛡️ 纯虚拟环境，绝对安全**：  
  不会在宿主机上执行任何真实危险指令。所有基础文件操作均在内存虚拟文件系统（VFS）中进行，高级指令由大语言模型（默认 DeepSeek）进行高拟真输出模拟。
- **🖥️ 完整的原生终端体验（PTY Line Discipline）**：  
  - 支持字符即时回显（Echo）
  - 支持退格键（Backspace）、Delete 键、光标左右移动（Left / Right Arrow）
  - 支持上下方向键浏览命令历史（History Navigation）
  - 支持快捷键：`Ctrl+C` 取消当前输入、`Ctrl+D` 退出终端、`Ctrl+L` 清屏、`Ctrl+U` 清除整行
  - 支持 **Tab 键自动补全**（补全内置命令与当前目录下的文件/文件夹）
  - ANSI 彩色高亮提示符与彩色文件列表（目录高亮蓝色，可执行文件绿色）
- **🌐 多 Linux 发行版热切换**：  
  - 预置配置：Ubuntu 22.04 LTS、Arch Linux、Debian 12、Alpine Linux 3.19
  - 支持在会话内输入 `distro list` 查看所有可用发行版
  - 支持输入 `distro <id>`（例如 `distro arch`）在会话中即时切换系统环境，动态更新 `/etc/os-release`、`/etc/issue`、`/proc/version` 与包管理器行为。
- **🧠 大模型智能命令补全（LLM Engine）**：  
  - 当执行非内置文件命令时（如 `apt install nginx`、`pacman -Syu`、`git status`、`python3 -c "..."`、`top`、`curl`、`systemctl status`），自动携带当前发行版信息、工作目录与文件列表调用 LLM，流式返回真实的终端输出。
  - 启发式 VFS 同步：模拟执行 `git clone` 或 `wget` 时，自动在内存文件系统中建立对应目录与文件，确保后续 `ls` 查看的一致性。
- **📖 初学者交互式指南**：  
  - 登录即显示欢迎公告栏（MOTD）与入门快捷指南。
  - 终端内置 `help` 与 `tutorial` 教程命令，分阶段讲解导航、文件操作与高级命令。

---

## 📁 项目结构

```text
simlinux/
├── distros/                     # 发行版元数据配置
│   ├── ubuntu-22.04.json
│   ├── arch.json
│   ├── debian-12.json
│   └── alpine-3.19.json
├── simlinux/                    # 核心代码包
│   ├── __init__.py
│   ├── config.py                # 配置与发行版加载器
│   ├── vfs.py                   # 内存虚拟文件系统（树形节点、路径解析）
│   ├── terminal.py              # PTY 终端行规程（按键解析、Tab补全、ANSI颜色）
│   ├── commands.py              # 内置命令分发器与 LLM 协同
│   ├── llm_engine.py            # DeepSeek / OpenAI 异步流式引擎
│   ├── session.py               # 用户会话状态隔离（CWD、历史记录、Prompt）
│   └── server.py                # AsyncSSH 服务端与认证
├── .env.example                 # 环境变量模板
├── .env                         # 本地配置文件（API Key、端口、账号）
├── requirements.txt             # 依赖列表
├── ssh_host_key                 # SSH 服务端 RSA 私钥（缺失会自动生成）
├── ssh-keygen.py                # 辅助密钥生成工具
├── main.py                      # 服务启动主入口
├── test_vfs.py                  # 虚拟文件系统单元测试
├── test_line_editor.py          # 终端按键与行编辑单元测试
└── test_integration.py          # 端到端 SSH 完整集成测试
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

检查或编辑根目录下的 `.env` 文件：

```ini
# LLM API 配置（支持 DeepSeek 或任意兼容 OpenAI 规范的模型）
OPENAI_API_KEY=sk-your-deepseek-api-key
BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

# SSH 服务配置
SSH_HOST=0.0.0.0
SSH_PORT=2222
SSH_HOST_KEY=ssh_host_key

# 默认登录账号与密码
SSH_USERNAME=root
SSH_PASSWORD=123

# 默认发行版 (ubuntu-22.04, arch, debian-12, alpine-3.19)
DEFAULT_DISTRO=ubuntu-22.04
```

### 3. 启动服务

直接运行 `main.py`：

```bash
python main.py
```

支持命令行参数动态覆盖：
```bash
python main.py --port 2222 --distro ubuntu-22.04 --user root --password 123
```

### 4. 使用 SSH 客户端连接

打开任意终端或客户端（Linux/macOS 终端、Windows Terminal、PuTTY、Xshell 等）：

```bash
ssh root@127.0.0.1 -p 2222
```

输入密码：`123`，即可进入模拟 Linux 终端！

---

## 🛠️ 命令支持

### 内置即时命令（纯内存 VFS 执行，毫秒级响应）

| 命令 | 功能说明 |
| :--- | :--- |
| `pwd` | 显示当前所在目录路径 |
| `cd <path>` | 切换目录（支持 `~`、`..`、`-`、绝对与相对路径） |
| `ls [-l] [-a] [-la]` | 列出目录内容，按文件类型展示 ANSI 颜色 |
| `cat <file>` | 查看文件内容 |
| `touch <file>` | 创建新文件或更新修改时间 |
| `mkdir [-p] <dir>` | 创建文件夹（支持 `-p` 递归多级创建） |
| `rm [-r] [-rf] <path>` | 删除文件或递归删除文件夹 |
| `echo "text" [> \| >>] file` | 打印文本，或通过 `>` / `>>` 重定向到文件 |
| `whoami` / `id` / `hostname` | 查看当前用户与系统主机名 |
| `uname -a` | 查看内核版本与架构信息 |
| `date` / `uptime` | 查看当前时间和系统运行时间 |
| `clear` | 清屏（也可使用 `Ctrl+L`） |
| `history` | 查看当前会话执行过的历史命令列表 |
| `distro list` | 查看所有支持的 Linux 发行版列表 |
| `distro <id>` | 动态切换当前会话发行版（如 `distro arch`） |
| `help` / `tutorial` | 查看新手引导与学习建议 |
| `exit` / `logout` | 退出 SSH 连接（也可使用 `Ctrl+D`） |

### 智能命令（由 LLM 模拟输出）

只要输入的不是内置的基础文件命令，SimLinux 就会自动交由大模型处理，例如：
- `apt update` / `apt install nginx`
- `pacman -Syu python`
- `python3 -c "print('Hello SimLinux')"`
- `git status` / `git log`
- `top` / `htop` / `ps aux`
- `curl ipinfo.io`
- `systemctl status sshd`

---

## 🧪 自动化测试

项目已编写完整的测试套件：

```bash
# 1. 运行虚拟文件系统测试
python test_vfs.py

# 2. 运行终端按键规程测试（退格、历史上下键、Tab补全）
python test_line_editor.py

# 3. 运行端到端 SSH 真实连接与 LLM 集成测试
python test_integration.py
```
