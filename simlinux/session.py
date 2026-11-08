import os
from typing import Dict, List, Tuple, Optional
from simlinux.config import DistroConfig, Config
from simlinux.vfs import VirtualFileSystem
from simlinux.terminal import LineEditor, Ansi, colorize
from simlinux.llm_engine import LLMEngine
from simlinux.commands import CommandDispatcher


class Session:
    def __init__(
        self,
        username: str,
        hostname: str,
        distro: DistroConfig,
        all_distros: Dict[str, DistroConfig],
        cfg: Config
    ):
        self.username = username
        self.hostname = hostname
        self.distro = distro
        self.available_distros = all_distros
        self.cfg = cfg

        # Virtual File System
        self.vfs = VirtualFileSystem()
        self.vfs.init_standard_linux_tree(self.distro.raw_data, self.hostname)

        # Working Directories
        self.cwd = "/root" if self.username == "root" else f"/home/{self.username}"
        if not self.vfs.exists(self.cwd):
            self.vfs.mkdir(self.cwd, recursive=True, owner=self.username)
        self.oldpwd = self.cwd

        # Command & Context History
        self.command_history: List[str] = []
        self.llm_history: List[Tuple[str, str]] = []

        # Engines & Handlers
        self.line_editor = LineEditor()
        self.llm_engine = LLMEngine(
            api_key=cfg.openai_api_key,
            base_url=cfg.base_url,
            model=cfg.model
        )
        self.dispatcher = CommandDispatcher(self)
        self.is_active = True

    def switch_distro(self, new_distro: DistroConfig) -> None:
        self.distro = new_distro
        # Update system files in VFS
        os_release_text = "\n".join(f'{k}="{v}"' for k, v in new_distro.os_release.items()) + "\n"
        self.vfs.write_file("/etc/os-release", os_release_text)
        self.vfs.write_file("/etc/issue", new_distro.issue)

        uname_vars = dict(new_distro.uname_vars)
        uname_vars.setdefault("hostname", self.hostname)
        self.vfs.write_file("/proc/version", new_distro.uname.format(**uname_vars) + "\n")

    def prompt(self) -> str:
        symbol = "#" if self.username == "root" else "$"
        # Convert path to ~ if in home
        home = "/root" if self.username == "root" else f"/home/{self.username}"
        display_path = self.cwd
        if display_path == home:
            display_path = "~"
        elif display_path.startswith(home + "/"):
            display_path = "~" + display_path[len(home):]

        user_host = colorize(f"{self.username}@{self.hostname}", Ansi.BOLD + Ansi.GREEN)
        path_colored = colorize(display_path, Ansi.BOLD + Ansi.BLUE)
        return f"{user_host}:{path_colored}{symbol} "

    def get_autocompletions(self, text: str) -> List[str]:
        """Provide autocompletions for Tab key."""
        text = text.lstrip()
        tokens = text.split()
        is_first_token = len(tokens) <= 1 and not text.endswith(" ")

        # Builtin commands to complete
        builtins = [
            "ls", "ll", "cd", "pwd", "cat", "touch", "mkdir", "rm", "cp", "mv",
            "echo", "whoami", "id", "hostname", "uname", "date", "uptime",
            "clear", "history", "distro", "tutorial", "help", "exit", "logout"
        ]

        if is_first_token:
            prefix = tokens[0] if tokens else ""
            matches = [b for b in builtins if b.startswith(prefix)]
            return sorted(matches)

        # Path completion for arguments
        prefix = tokens[-1] if not text.endswith(" ") else ""
        parent_dir = self.cwd
        file_prefix = prefix

        if "/" in prefix:
            parent_dir = self.vfs.resolve_path(prefix.rsplit("/", 1)[0], self.cwd)
            file_prefix = prefix.rsplit("/", 1)[1]

        try:
            nodes = self.vfs.list_dir(parent_dir, self.cwd)
            matches = []
            for n in nodes:
                if n.name.startswith(file_prefix):
                    full_match = n.name + ("/" if n.is_dir else "")
                    if "/" in prefix:
                        matches.append(prefix.rsplit("/", 1)[0] + "/" + full_match)
                    else:
                        matches.append(full_match)
            return sorted(matches)
        except Exception:
            return []

    def get_motd(self) -> str:
        banner = (
            colorize("=================================================================\n", Ansi.CYAN) +
            colorize(f"  Welcome to SimLinux ({self.distro.name}) - Learning Terminal  \n", Ansi.BOLD + Ansi.WHITE) +
            colorize("=================================================================\n", Ansi.CYAN) +
            f" * OS:       {self.distro.name} ({self.distro.pkg_manager})\n" +
            f" * Hostname: {self.hostname} | User: {self.username}\n" +
            f" * AI Model: {self.cfg.model} via {self.cfg.base_url}\n" +
            f" * Mode:     Simulated Shell (Safe for beginners, no real host changes)\n\n" +
            " Quick Start:\n" +
            f"  - Type {colorize('help', Ansi.YELLOW)} or {colorize('tutorial', Ansi.YELLOW)} for beginner guide & lessons\n" +
            f"  - Type {colorize('distro list', Ansi.YELLOW)} to explore other Linux distributions\n" +
            f"  - Type {colorize('distro <id>', Ansi.YELLOW)} (e.g. 'distro arch') to switch distro anytime\n\n"
        )
        return banner
