<div align="right">
  <strong>English</strong> | <a href="README_CN.md">简体中文</a>
</div>

# SimLinux 🐧

> **An LLM-Powered Simulated Linux SSH Terminal for Beginners**  
> Connect via standard SSH clients, experience authentic terminal interactions, and practice Linux commands in a completely safe, sandbox environment.

---

## ✨ Features

- **🛡️ 100% Virtual & Safe**:  
  No commands are ever executed on your host operating system. Core filesystem operations run inside an in-memory Virtual File System (VFS), while advanced commands are realistically simulated by Large Language Models (LLMs, default: DeepSeek).
- **🖥️ Native Terminal Experience (PTY Line Discipline)**:  
  - Real-time keystroke echo
  - Full line editing: Backspace, Delete, Left/Right arrow cursor movement
  - Command history navigation with Up/Down arrows
  - Standard Unix shortcut keys: `Ctrl+C` (cancel), `Ctrl+D` (exit/EOF), `Ctrl+L` (clear screen), `Ctrl+U` (clear line)
  - **Tab Key Autocompletion** for builtin commands and files/folders in the current working directory
  - ANSI color-coded prompt and `ls` outputs (directories in bold blue, executables in bold green).
- **🌐 Dynamic Multi-Distro Switching**:  
  - Pre-configured distributions: Ubuntu 22.04 LTS, Arch Linux, Debian 12, Alpine Linux 3.19
  - Run `distro list` to browse available distros inside your SSH session
  - Run `distro <id>` (e.g., `distro arch`) to switch distribution on the fly. Dynamically updates `/etc/os-release`, `/etc/issue`, `/proc/version`, and package manager behavior.
- **🧠 LLM Simulation Engine**:  
  - Non-builtin commands (such as `apt install nginx`, `pacman -Syu`, `git status`, `python3 -c "..."`, `top`, `curl`, `systemctl status`) are dispatched to the LLM with full context (distro, CWD, directory contents, and recent command history), streaming authentic terminal output line-by-line.
  - Heuristic VFS synchronization: commands like `git clone` or `wget` automatically create dummy records in the in-memory VFS, ensuring consistent subsequent `ls` results.
- **📖 Beginner Interactive Guide**:  
  - Informative Message of the Day (MOTD) banner on login.
  - Interactive `help` and `tutorial` commands to guide beginners step-by-step through Linux fundamentals.

---

## 📁 Project Structure

```text
simlinux/
├── distros/                     # Linux distribution JSON configurations
│   ├── ubuntu-22.04.json
│   ├── arch.json
│   ├── debian-12.json
│   └── alpine-3.19.json
├── simlinux/                    # Core Python package
│   ├── __init__.py
│   ├── config.py                # Configuration & distro loader
│   ├── vfs.py                   # In-memory virtual filesystem & path resolution
│   ├── terminal.py              # ANSI color formatting & terminal codes
│   ├── commands.py              # Builtin command dispatcher & VFS integration
│   ├── llm_engine.py            # DeepSeek / OpenAI async streaming engine
│   ├── session.py               # User session state isolation (CWD, history, prompt)
│   └── server.py                # AsyncSSH server, auth & process handler
├── .env.example                 # Environment configuration template
├── .env                         # Active local settings (API key, ports, credentials)
├── requirements.txt             # Project dependencies
├── ssh_host_key                 # RSA host key for SSH server (auto-generated if missing)
├── main.py                      # Server CLI entry point
├── test_vfs.py                  # Unit tests for Virtual File System
└── test_integration.py          # End-to-end SSH integration tests
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Edit the `.env` file in the project root:

```ini
# LLM API Settings (DeepSeek or any OpenAI-compatible API)
OPENAI_API_KEY=sk-your-deepseek-api-key
BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

# SSH Server Settings
SSH_HOST=0.0.0.0
SSH_PORT=2222
SSH_HOST_KEY=ssh_host_key

# Default Authentication Credentials
SSH_USERNAME=root
SSH_PASSWORD=123

# Default Distribution (ubuntu-22.04, arch, debian-12, alpine-3.19)
DEFAULT_DISTRO=ubuntu-22.04
```

### 3. Launch the Server

Run `main.py`:

```bash
python main.py
```

Command-line flags and custom hardware specifications are fully supported:
```bash
# Standard startup
python main.py

# Custom hardware specs: 4 vCPU, 16GB RAM, 100GB Disk, custom hostname
python main.py --cpu 4 --memory 16G --disk 100G --hostname dev-box

# Advanced configuration with custom CPU model, distro, and credentials
python main.py --port 2222 --cpu 8 --cpu-model "AMD EPYC 7763" --memory 32G --disk 500G --distro arch
```

#### CLI Startup Options:
| Flag | Description | Default |
| :--- | :--- | :--- |
| `--cpu`, `--cpu-cores` | Number of virtual CPU cores (`/proc/cpuinfo`, `nproc`, `lscpu`) | `2` |
| `--cpu-model` | Virtual CPU model name string | `Intel(R) Core(TM) Virtual CPU @ 2.80GHz` |
| `--memory`, `--ram` | Virtual RAM size, e.g. `4G`, `16G`, `32G`, `8192M` (`free -h`, `/proc/meminfo`) | `8G` |
| `--disk`, `--disk-size` | Virtual disk size, e.g. `20G`, `100G`, `500G` (`df -h`) | `40G` |
| `--hostname` | Machine hostname displayed in prompt and `/etc/hostname` | `simlinux` |
| `--distro`, `-d` | Default Linux distribution (`ubuntu-22.04`, `arch`, `debian-12`, `alpine-3.19`) | `ubuntu-22.04` |
| `--port`, `-p` | SSH server listening port | `2222` |
| `--host` | SSH server bind address | `0.0.0.0` |
| `--user`, `-u` | SSH login username | `root` |
| `--password` | SSH login password | `123` |
| `--model`, `-m` | LLM model name | `deepseek-chat` |
| `--base-url` | LLM API base URL | `https://api.deepseek.com` |
| `--debug` | Enable verbose debug logging | `False` |

### 4. Connect via SSH

Open any standard terminal (Windows Terminal, macOS Terminal, PuTTY, OpenSSH, etc.):

```bash
ssh root@127.0.0.1 -p 2222
```

Password: `123`. Welcome to SimLinux!

---

## 🛠️ Command Reference

### Built-in Instant Commands (In-Memory VFS, sub-millisecond latency)

| Command | Description |
| :--- | :--- |
| `pwd` | Print current working directory |
| `cd <path>` | Change directory (supports `~`, `..`, `-`, absolute & relative paths) |
| `ls [-l] [-a] [-la]` | List directory contents with ANSI color highlighting |
| `cat <file>` | Display file contents |
| `touch <file>` | Create an empty file or update timestamp |
| `mkdir [-p] <dir>` | Create a directory (supports `-p` parent directory creation) |
| `rm [-r] [-rf] <path>` | Remove files or directories recursively |
| `echo "text" [> \| >>] file` | Print text or redirect output to file |
| `whoami` / `id` / `hostname` | Display current user and host information |
| `uname -a` | Print kernel, release, and machine architecture |
| `date` / `uptime` | Display system time and simulated uptime |
| `clear` | Clear terminal screen (or use `Ctrl+L`) |
| `history` | List command history in the current session |
| `distro list` | List all available Linux distributions |
| `distro <id>` | Switch the current session distribution (e.g. `distro arch`) |
| `help` / `tutorial` | Interactive beginner tutorial & lessons |
| `exit` / `logout` | Terminate SSH session (or use `Ctrl+D`) |

### Simulated Commands (Powered by LLM)

Any command not handled natively by the VFS is simulated by the LLM, including:
- Package management: `apt update`, `apt install nginx`, `pacman -Syu python`
- Interpreters: `python3 -c "print('Hello SimLinux')"`
- Git: `git status`, `git log`, `git clone <url>`
- Process & System: `top`, `htop`, `ps aux`, `systemctl status sshd`
- Network: `curl ipinfo.io`, `ping baidu.com`, `wget <url>`

---

## 🧪 Automated Testing

SimLinux includes a full automated test suite:

```bash
# 1. Test Virtual File System
python -m unittest test_vfs.py

# 2. Test End-to-End SSH Connection & Live LLM Simulation
python test_integration.py
```
