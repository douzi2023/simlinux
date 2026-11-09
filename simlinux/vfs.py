# -*- coding: utf-8 -*-
import time
from typing import Dict, List, Optional


class VFSNode:
    def __init__(
        self,
        name: str,
        is_dir: bool = False,
        content: str = "",
        mode: str = "",
        owner: str = "root",
        group: str = "root"
    ):
        self.name = name
        self.is_dir = is_dir
        self.content = content
        self.owner = owner
        self.group = group
        self.mtime = time.time()
        self.mode = mode or ("drwxr-xr-x" if is_dir else "-rw-r--r--")
        self.children: Dict[str, "VFSNode"] = {} if is_dir else {}

    @property
    def size(self) -> int:
        return 4096 if self.is_dir else len(self.content.encode("utf-8"))


class VirtualFileSystem:
    def __init__(self):
        self.root = VFSNode("", is_dir=True)

    def resolve_path(self, path: str, cwd: str = "/") -> str:
        path = path.strip()
        if not path:
            return cwd

        if path == "~" or path.startswith("~/"):
            home = "/root" if cwd.startswith("/root") else "/home/user"
            path = home + path[1:]

        if not path.startswith("/"):
            path = cwd.rstrip("/") + "/" + path

        stack: List[str] = []
        for part in path.split("/"):
            if part and part != ".":
                if part == "..":
                    if stack:
                        stack.pop()
                else:
                    stack.append(part)

        return "/" + "/".join(stack)

    def get_node(self, path: str, cwd: str = "/") -> Optional[VFSNode]:
        abs_path = self.resolve_path(path, cwd)
        if abs_path == "/":
            return self.root

        curr = self.root
        for part in [p for p in abs_path.split("/") if p]:
            if not curr.is_dir or part not in curr.children:
                return None
            curr = curr.children[part]
        return curr

    def exists(self, path: str, cwd: str = "/") -> bool:
        return self.get_node(path, cwd) is not None

    def is_dir(self, path: str, cwd: str = "/") -> bool:
        node = self.get_node(path, cwd)
        return node.is_dir if node else False

    def is_file(self, path: str, cwd: str = "/") -> bool:
        node = self.get_node(path, cwd)
        return not node.is_dir if node else False

    def mkdir(self, path: str, cwd: str = "/", recursive: bool = False, owner: str = "root") -> VFSNode:
        abs_path = self.resolve_path(path, cwd)
        if abs_path == "/":
            return self.root

        parts = [p for p in abs_path.split("/") if p]
        curr = self.root

        for idx, part in enumerate(parts):
            is_last = (idx == len(parts) - 1)
            if part in curr.children:
                node = curr.children[part]
                if not node.is_dir:
                    raise NotADirectoryError(f"'{part}' is not a directory")
                curr = node
            else:
                if not is_last and not recursive:
                    raise FileNotFoundError(f"cannot create directory '{path}': No such file or directory")
                new_dir = VFSNode(part, is_dir=True, owner=owner, group=owner)
                curr.children[part] = new_dir
                curr = new_dir

        return curr

    def write_file(
        self,
        path: str,
        content: str,
        cwd: str = "/",
        append: bool = False,
        owner: str = "root"
    ) -> VFSNode:
        abs_path = self.resolve_path(path, cwd)
        if abs_path == "/":
            raise IsADirectoryError("cannot write to root directory as file")

        parts = [p for p in abs_path.split("/") if p]
        parent_parts = parts[:-1]
        file_name = parts[-1]

        curr = self.root
        for part in parent_parts:
            if part not in curr.children:
                raise FileNotFoundError(f"cannot write to '{path}': No such file or directory")
            curr = curr.children[part]
            if not curr.is_dir:
                raise NotADirectoryError(f"'{part}' is not a directory")

        if file_name in curr.children:
            existing = curr.children[file_name]
            if existing.is_dir:
                raise IsADirectoryError(f"'{path}' is a directory")
            existing.content = (existing.content + content) if append else content
            existing.mtime = time.time()
            return existing
        else:
            new_file = VFSNode(file_name, is_dir=False, content=content, owner=owner, group=owner)
            curr.children[file_name] = new_file
            return new_file

    def read_file(self, path: str, cwd: str = "/") -> str:
        node = self.get_node(path, cwd)
        if node is None:
            raise FileNotFoundError(f"cat: {path}: No such file or directory")
        if node.is_dir:
            raise IsADirectoryError(f"cat: {path}: Is a directory")
        return node.content

    def list_dir(self, path: str = "/", cwd: str = "/") -> List[VFSNode]:
        node = self.get_node(path, cwd)
        if node is None:
            raise FileNotFoundError(f"ls: cannot access '{path}': No such file or directory")
        if not node.is_dir:
            return [node]
        return sorted(node.children.values(), key=lambda n: n.name)

    def remove(self, path: str, cwd: str = "/", recursive: bool = False, force: bool = False) -> None:
        abs_path = self.resolve_path(path, cwd)
        if abs_path == "/":
            raise PermissionError("rm: it is dangerous to operate recursively on '/'")

        parts = [p for p in abs_path.split("/") if p]
        curr = self.root
        for part in parts[:-1]:
            if part not in curr.children:
                if force:
                    return
                raise FileNotFoundError(f"rm: cannot remove '{path}': No such file or directory")
            curr = curr.children[part]
            if not curr.is_dir:
                raise NotADirectoryError(f"rm: '{part}' is not a directory")

        target_name = parts[-1]
        if target_name not in curr.children:
            if force:
                return
            raise FileNotFoundError(f"rm: cannot remove '{path}': No such file or directory")

        target = curr.children[target_name]
        if target.is_dir and not recursive:
            raise IsADirectoryError(f"rm: cannot remove '{path}': Is a directory")
        del curr.children[target_name]

    def init_standard_linux_tree(
        self,
        distro_info: dict,
        hostname: str = "simlinux",
        cpu_cores: int = 2,
        cpu_model: str = "Intel(R) Core(TM) Virtual CPU @ 2.80GHz",
        memory_gb: int = 8,
        disk_gb: int = 40
    ) -> None:
        """Create standard Linux directory structure and base system files."""
        dirs = (
            "/bin /boot /dev /etc /home/user /lib /media /mnt /opt /proc /root /run "
            "/sbin /srv /sys /tmp /usr/bin /usr/lib /usr/local/bin /usr/share /var/log /var/tmp"
        ).split()
        for d in dirs:
            self.mkdir(d, recursive=True)

        # /etc system files
        os_release = "\n".join(f'{k}="{v}"' for k, v in distro_info.get("os_release", {}).items()) + "\n"
        self.write_file("/etc/os-release", os_release)
        self.write_file("/etc/issue", distro_info.get("issue", f"{distro_info.get('name', 'SimLinux')} \\n \\l\n"))
        self.write_file("/etc/hostname", f"{hostname}\n")
        self.write_file("/etc/passwd", (
            "root:x:0:0:root:/root:/bin/bash\n"
            "user:x:1000:1000:user:/home/user:/bin/bash\n"
        ))
        self.write_file("/etc/hosts", f"127.0.0.1   localhost\n127.0.1.1   {hostname}\n::1         localhost\n")

        # /proc pseudo files
        uname_vars = {
            "hostname": hostname, "kernel": "Linux",
            "release": "5.15.0-generic", "arch": "x86_64",
            **distro_info.get("uname_vars", {})
        }
        uname_str = distro_info.get("uname", "Linux {hostname} 5.15.0-generic x86_64 GNU/Linux").format(**uname_vars) + "\n"
        self.write_file("/proc/version", uname_str)

        # Dynamic /proc/cpuinfo according to cpu_cores and cpu_model
        cpu_entries = []
        for i in range(max(1, cpu_cores)):
            cpu_entries.append(
                f"processor\t: {i}\n"
                f"vendor_id\t: GenuineIntel\n"
                f"model name\t: {cpu_model}\n"
                f"cpu MHz\t\t: 2800.000\n"
                f"cache size\t: 16384 KB\n"
                f"cpu cores\t: {cpu_cores}\n"
            )
        self.write_file("/proc/cpuinfo", "\n".join(cpu_entries) + "\n")

        # Dynamic /proc/meminfo according to memory_gb
        mem_total_kb = memory_gb * 1024 * 1024
        mem_free_kb = int(mem_total_kb * 0.65)
        mem_avail_kb = int(mem_total_kb * 0.82)
        meminfo_text = (
            f"MemTotal:        {mem_total_kb:8d} kB\n"
            f"MemFree:         {mem_free_kb:8d} kB\n"
            f"MemAvailable:    {mem_avail_kb:8d} kB\n"
            f"Buffers:           210456 kB\n"
            f"Cached:           1845124 kB\n"
            f"SwapTotal:        2097148 kB\n"
            f"SwapFree:         2097148 kB\n"
        )
        self.write_file("/proc/meminfo", meminfo_text)
        self.write_file("/proc/uptime", "35024.12 68923.45\n")
        self.write_file("/proc/loadavg", "0.15 0.08 0.03 1/142 1236\n")

        # /root user starter guides
        self.write_file("/root/README.txt", (
            "====================================================\n"
            "       Welcome to SimLinux - Virtual Learning OS    \n"
            "====================================================\n\n"
            "Safe simulated Linux terminal for beginners.\n"
            f"- Virtual Hardware: {cpu_cores} vCPU, {memory_gb}GB RAM, {disk_gb}GB Disk\n"
            "- Built-in commands: ls, cd, mkdir, touch, cat, echo, rm, df, free, etc.\n"
            "- LLM simulated commands: apt, python, curl, top, systemctl, etc.\n\n"
            "Type 'tutorial' or 'help' for beginner lessons.\n"
            "Type 'distro list' to view and switch Linux distributions.\n"
        ))
        self.write_file("/root/tutorial.txt", (
            "Linux Beginner Quickstart:\n"
            "1. Navigation:  pwd, ls -la, cd /etc, cd ~\n"
            "2. Files:       touch a.txt, mkdir dir, echo 'hi' > a.txt, cat a.txt, rm a.txt\n"
            "3. System:      uname -a, whoami, cat /etc/os-release\n"
        ))
