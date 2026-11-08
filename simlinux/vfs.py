import time
from typing import Dict, List, Optional, Tuple


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
        if self.is_dir:
            return 4096
        return len(self.content.encode("utf-8"))


class VirtualFileSystem:
    def __init__(self):
        self.root = VFSNode("", is_dir=True)

    def resolve_path(self, path: str, cwd: str = "/") -> str:
        """Resolve a path with CWD and relative tokens into an absolute canonical path."""
        path = path.strip()
        if not path:
            return cwd

        # Handle home directory shorthand
        if path == "~" or path.startswith("~/"):
            home = "/root" if cwd.startswith("/root") else "/home/user"
            path = home + path[1:]

        if not path.startswith("/"):
            path = cwd.rstrip("/") + "/" + path

        # Normalize segments
        parts = [p for p in path.split("/") if p and p != "."]
        stack: List[str] = []
        for part in parts:
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

        parts = [p for p in abs_path.split("/") if p]
        curr = self.root
        for part in parts:
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
            if append:
                existing.content += content
            else:
                existing.content = content
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
        parent_parts = parts[:-1]
        target_name = parts[-1]

        curr = self.root
        for part in parent_parts:
            if part not in curr.children:
                if force:
                    return
                raise FileNotFoundError(f"rm: cannot remove '{path}': No such file or directory")
            curr = curr.children[part]
            if not curr.is_dir:
                raise NotADirectoryError(f"rm: '{part}' is not a directory")

        if target_name not in curr.children:
            if force:
                return
            raise FileNotFoundError(f"rm: cannot remove '{path}': No such file or directory")

        target = curr.children[target_name]
        if target.is_dir:
            if not recursive:
                raise IsADirectoryError(f"rm: cannot remove '{path}': Is a directory")
        del curr.children[target_name]

    def init_standard_linux_tree(self, distro_info: dict, hostname: str = "simlinux") -> None:
        """Create standard Linux directories and essential system files."""
        dirs = [
            "/bin", "/boot", "/dev", "/etc", "/home/user", "/lib", "/media",
            "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv",
            "/sys", "/tmp", "/usr/bin", "/usr/lib", "/usr/local/bin",
            "/usr/share", "/var/log", "/var/tmp"
        ]
        for d in dirs:
            self.mkdir(d, recursive=True)

        # /etc/os-release
        os_release_data = distro_info.get("os_release", {})
        os_release_text = "\n".join(f'{k}="{v}"' for k, v in os_release_data.items()) + "\n"
        self.write_file("/etc/os-release", os_release_text)

        # /etc/issue
        issue_text = distro_info.get("issue", f"{distro_info.get('name', 'SimLinux')} \\n \\l\n")
        self.write_file("/etc/issue", issue_text)

        # /etc/hostname
        self.write_file("/etc/hostname", f"{hostname}\n")

        # /etc/passwd
        passwd_text = (
            "root:x:0:0:root:/root:/bin/bash\n"
            "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
            "bin:x:2:2:bin:/bin:/usr/sbin/nologin\n"
            "sys:x:3:3:sys:/dev:/usr/sbin/nologin\n"
            "user:x:1000:1000:user:/home/user:/bin/bash\n"
            "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        )
        self.write_file("/etc/passwd", passwd_text)

        # /etc/hosts
        hosts_text = (
            "127.0.0.1   localhost\n"
            f"127.0.1.1   {hostname}\n"
            "::1         localhost ip6-localhost ip6-loopback\n"
        )
        self.write_file("/etc/hosts", hosts_text)

        # /proc pseudo files
        uname_template = distro_info.get("uname", "Linux {hostname} 5.15.0-generic x86_64 GNU/Linux")
        uname_vars = dict(distro_info.get("uname_vars", {}))
        uname_vars.setdefault("hostname", hostname)
        uname_vars.setdefault("kernel", "Linux")
        uname_vars.setdefault("release", "5.15.0-generic")
        uname_vars.setdefault("arch", "x86_64")
        version_str = uname_template.format(**uname_vars) + "\n"
        self.write_file("/proc/version", version_str)

        cpuinfo_text = (
            "processor\t: 0\n"
            "vendor_id\t: GenuineIntel\n"
            "model name\t: Intel(R) Core(TM) Virtual CPU @ 2.80GHz\n"
            "cpu MHz\t\t: 2800.000\n"
            "cache size\t: 16384 KB\n"
            "cpu cores\t: 2\n"
        )
        self.write_file("/proc/cpuinfo", cpuinfo_text)

        meminfo_text = (
            "MemTotal:        8148992 kB\n"
            "MemFree:         5214560 kB\n"
            "MemAvailable:    6890124 kB\n"
            "Buffers:          210456 kB\n"
            "Cached:          1845124 kB\n"
        )
        self.write_file("/proc/meminfo", meminfo_text)

        # /root/README.txt & /root/tutorial.txt
        readme_text = (
            "====================================================\n"
            "       Welcome to SimLinux - Virtual Learning OS    \n"
            "====================================================\n\n"
            "This is a simulated Linux environment designed for beginners.\n"
            "- It does NOT run commands on the host machine.\n"
            "- Standard Linux commands (ls, cd, mkdir, touch, cat, echo, rm, etc.) are built-in.\n"
            "- Advanced commands (apt, python, curl, top, systemctl, etc.) are simulated by LLM.\n\n"
            "Type 'tutorial' or 'help' for interactive learning lessons!\n"
            "Type 'distro list' to view available Linux distributions.\n"
            "Type 'distro <id>' (e.g., distro arch) to switch distro on the fly.\n"
        )
        self.write_file("/root/README.txt", readme_text)

        tutorial_text = (
            "Linux Beginner Quickstart Guide:\n\n"
            "1. Navigation:\n"
            "   pwd               Show current directory path\n"
            "   ls -la            List all files with details\n"
            "   cd /etc           Change directory to /etc\n"
            "   cd ~              Go back to home directory\n\n"
            "2. File Operations:\n"
            "   touch test.txt    Create an empty file\n"
            "   mkdir mydir       Create a directory\n"
            "   echo 'hi' > a.txt Write text into a file\n"
            "   cat a.txt         Display file contents\n"
            "   rm test.txt       Delete a file\n\n"
            "3. System Info:\n"
            "   uname -a          Kernel and machine architecture\n"
            "   whoami            Current logged-in user\n"
            "   cat /etc/os-release Show Linux distribution version\n"
        )
        self.write_file("/root/tutorial.txt", tutorial_text)
