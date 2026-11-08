import datetime
import re
import shlex
import time
from typing import List, Tuple, Optional, Any
from simlinux.terminal import Ansi, colorize
from simlinux.vfs import VFSNode


class CommandDispatcher:
    def __init__(self, session):
        self.session = session

    async def dispatch(self, cmd_line: str, writer) -> str:
        cmd_line = cmd_line.strip()
        if not cmd_line:
            return ""

        # Check for redirection: > or >>
        redirect_mode = None
        target_file = None
        main_cmd = cmd_line

        # Simple regex for redirecting output to file: cmd > file or cmd >> file
        redir_match = re.search(r"\s*(>>|>)\s*([^\s|;&]+)$", cmd_line)
        if redir_match:
            op = redir_match.group(1)
            target_file = redir_match.group(2).strip()
            main_cmd = cmd_line[:redir_match.start()].strip()
            redirect_mode = "append" if op == ">>" else "write"

        # Split arguments safely
        try:
            tokens = shlex.split(main_cmd)
        except ValueError:
            tokens = main_cmd.split()

        if not tokens:
            return ""

        cmd_name = tokens[0]
        args = tokens[1:]

        # Dispatch to builtin if available
        builtin_func = getattr(self, f"cmd_{cmd_name.replace('-', '_')}", None)
        output = ""

        if builtin_func:
            try:
                output = await builtin_func(args, writer)
            except Exception as e:
                output = f"bash: {cmd_name}: {e}\n"
        else:
            # Fallback to LLM Engine
            output = await self._dispatch_to_llm(main_cmd, writer)
            self._post_llm_vfs_sync(main_cmd, output)

        # Handle file redirection if requested
        if redirect_mode and target_file:
            try:
                clean_output = output.replace("\n", "\n")
                self.session.vfs.write_file(
                    target_file,
                    clean_output,
                    cwd=self.session.cwd,
                    append=(redirect_mode == "append"),
                    owner=self.session.username
                )
                output = ""  # Redirection silences terminal output
            except Exception as e:
                err = f"bash: {target_file}: {e}\n"
                writer.write(err)
                await writer.drain()
                return err

        return output

    async def _dispatch_to_llm(self, command: str, writer) -> str:
        vfs = self.session.vfs
        cwd_nodes = []
        try:
            cwd_nodes = [node.name for node in vfs.list_dir(self.session.cwd)]
        except Exception:
            pass

        return await self.session.llm_engine.execute_command_stream(
            command=command,
            distro_info=self.session.distro.raw_data,
            cwd=self.session.cwd,
            files_in_cwd=cwd_nodes,
            history=self.session.llm_history,
            writer=writer
        )

    def _post_llm_vfs_sync(self, command: str, output: str) -> None:
        """Heuristic to keep VFS in sync after LLM command outputs."""
        vfs = self.session.vfs
        cwd = self.session.cwd
        tokens = command.split()
        if not tokens:
            return

        cmd = tokens[0]
        # Detect git clone
        if cmd == "git" and len(tokens) >= 3 and tokens[1] == "clone":
            repo_url = tokens[2]
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            try:
                vfs.mkdir(repo_name, cwd=cwd, owner=self.session.username)
                vfs.mkdir(f"{repo_name}/.git", cwd=cwd, recursive=True, owner=self.session.username)
                vfs.write_file(f"{repo_name}/README.md", f"# {repo_name}\nCloned via SimLinux\n", cwd=cwd, owner=self.session.username)
            except Exception:
                pass

        # Detect wget / curl -O
        elif cmd == "wget" and len(tokens) >= 2:
            url = tokens[-1]
            fname = url.rstrip("/").split("/")[-1] or "index.html"
            try:
                vfs.write_file(fname, "Simulated downloaded content\n", cwd=cwd, owner=self.session.username)
            except Exception:
                pass
        elif cmd == "curl" and "-O" in tokens:
            url = tokens[-1]
            fname = url.rstrip("/").split("/")[-1] or "download"
            try:
                vfs.write_file(fname, "Simulated downloaded content\n", cwd=cwd, owner=self.session.username)
            except Exception:
                pass

    # ---------------- Builtin Commands ----------------

    async def cmd_pwd(self, args: List[str], writer) -> str:
        out = f"{self.session.cwd}\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_cd(self, args: List[str], writer) -> str:
        target = args[0] if args else "~"
        if target == "-":
            target = self.session.oldpwd

        resolved = self.session.vfs.resolve_path(target, self.session.cwd)
        node = self.session.vfs.get_node(resolved)

        if node is None:
            out = f"bash: cd: {target}: No such file or directory\n"
            writer.write(out)
            await writer.drain()
            return out
        if not node.is_dir:
            out = f"bash: cd: {target}: Not a directory\n"
            writer.write(out)
            await writer.drain()
            return out

        self.session.oldpwd = self.session.cwd
        self.session.cwd = resolved
        return ""

    async def cmd_ls(self, args: List[str], writer) -> str:
        show_all = False
        long_format = False
        target_path = self.session.cwd

        for arg in args:
            if arg.startswith("-"):
                if "a" in arg:
                    show_all = True
                if "l" in arg:
                    long_format = True
            else:
                target_path = arg

        try:
            nodes = self.session.vfs.list_dir(target_path, self.session.cwd)
        except Exception as e:
            out = f"{e}\n"
            writer.write(out)
            await writer.drain()
            return out

        if not show_all:
            nodes = [n for n in nodes if not n.name.startswith(".")]

        lines = []
        if long_format:
            total_size = sum(n.size for n in nodes)
            lines.append(f"total {total_size // 1024 + 1}")
            for n in nodes:
                date_str = datetime.datetime.fromtimestamp(n.mtime).strftime("%b %d %H:%M")
                name_colored = n.name
                if n.is_dir:
                    name_colored = colorize(n.name, Ansi.BOLD + Ansi.BLUE)
                elif "x" in n.mode:
                    name_colored = colorize(n.name, Ansi.BOLD + Ansi.GREEN)
                lines.append(f"{n.mode} 1 {n.owner} {n.group} {n.size:5d} {date_str} {name_colored}")
        else:
            colored_names = []
            for n in nodes:
                if n.is_dir:
                    colored_names.append(colorize(n.name, Ansi.BOLD + Ansi.BLUE))
                elif "x" in n.mode:
                    colored_names.append(colorize(n.name, Ansi.BOLD + Ansi.GREEN))
                else:
                    colored_names.append(n.name)
            if colored_names:
                lines.append("  ".join(colored_names))

        out = "\n".join(lines)
        if out:
            out += "\n"
            writer.write(out)
            await writer.drain()
        return out

    async def cmd_ll(self, args: List[str], writer) -> str:
        return await self.cmd_ls(["-la"] + args, writer)

    async def cmd_cat(self, args: List[str], writer) -> str:
        if not args:
            return ""
        out_chunks = []
        for file_path in args:
            try:
                content = self.session.vfs.read_file(file_path, self.session.cwd)
                content_fmt = content.replace("\n", "\n").replace("\n", "\n")
                out_chunks.append(content_fmt)
            except Exception as e:
                out_chunks.append(f"{e}\n")

        out = "".join(out_chunks)
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_touch(self, args: List[str], writer) -> str:
        if not args:
            out = "touch: missing file operand\n"
            writer.write(out)
            await writer.drain()
            return out

        for path in args:
            try:
                if self.session.vfs.exists(path, self.session.cwd):
                    node = self.session.vfs.get_node(path, self.session.cwd)
                    if node:
                        node.mtime = time.time()
                else:
                    self.session.vfs.write_file(path, "", cwd=self.session.cwd, owner=self.session.username)
            except Exception as e:
                err = f"touch: cannot touch '{path}': {e}\n"
                writer.write(err)
                await writer.drain()
                return err
        return ""

    async def cmd_mkdir(self, args: List[str], writer) -> str:
        recursive = False
        dirs = []
        for a in args:
            if a in ("-p", "--parents"):
                recursive = True
            else:
                dirs.append(a)

        if not dirs:
            out = "mkdir: missing operand\n"
            writer.write(out)
            await writer.drain()
            return out

        for d in dirs:
            try:
                self.session.vfs.mkdir(d, cwd=self.session.cwd, recursive=recursive, owner=self.session.username)
            except Exception as e:
                err = f"{e}\n"
                writer.write(err)
                await writer.drain()
                return err
        return ""

    async def cmd_rm(self, args: List[str], writer) -> str:
        recursive = False
        force = False
        targets = []
        for a in args:
            if a.startswith("-"):
                if "r" in a or "R" in a:
                    recursive = True
                if "f" in a:
                    force = True
            else:
                targets.append(a)

        if not targets and not force:
            out = "rm: missing operand\n"
            writer.write(out)
            await writer.drain()
            return out

        for t in targets:
            try:
                self.session.vfs.remove(t, cwd=self.session.cwd, recursive=recursive, force=force)
            except Exception as e:
                err = f"{e}\n"
                writer.write(err)
                await writer.drain()
                return err
        return ""

    async def cmd_echo(self, args: List[str], writer) -> str:
        text = " ".join(args)
        out = f"{text}\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_whoami(self, args: List[str], writer) -> str:
        out = f"{self.session.username}\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_id(self, args: List[str], writer) -> str:
        if self.session.username == "root":
            out = "uid=0(root) gid=0(root) groups=0(root)\n"
        else:
            out = f"uid=1000({self.session.username}) gid=1000({self.session.username}) groups=1000({self.session.username}),27(sudo)\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_hostname(self, args: List[str], writer) -> str:
        out = f"{self.session.hostname}\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_uname(self, args: List[str], writer) -> str:
        distro = self.session.distro
        template = distro.uname
        vars_dict = dict(distro.uname_vars)
        vars_dict.setdefault("hostname", self.session.hostname)
        vars_dict.setdefault("kernel", "Linux")
        vars_dict.setdefault("release", "5.15.0-generic")
        vars_dict.setdefault("arch", "x86_64")

        flags = "".join(args)
        if "-r" in flags and "-a" not in flags:
            out = f"{vars_dict['release']}\n"
        elif "-m" in flags and "-a" not in flags:
            out = f"{vars_dict['arch']}\n"
        elif "-s" in flags and "-a" not in flags:
            out = f"{vars_dict['kernel']}\n"
        elif "-n" in flags and "-a" not in flags:
            out = f"{vars_dict['hostname']}\n"
        else:
            out = template.format(**vars_dict) + "\n"

        writer.write(out)
        await writer.drain()
        return out

    async def cmd_date(self, args: List[str], writer) -> str:
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y")
        out = f"{now_str}\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_uptime(self, args: List[str], writer) -> str:
        t_str = datetime.datetime.now().strftime("%H:%M:%S")
        out = f" {t_str} up 12 days,  4:18,  1 user,  load average: 0.12, 0.08, 0.03\n"
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_clear(self, args: List[str], writer) -> str:
        writer.write(Ansi.CLEAR_SCREEN)
        await writer.drain()
        return ""

    async def cmd_history(self, args: List[str], writer) -> str:
        lines = []
        for i, cmd in enumerate(self.session.command_history, 1):
            lines.append(f"  {i:4d}  {cmd}")
        out = "\n".join(lines) + ("\n" if lines else "")
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_distro(self, args: List[str], writer) -> str:
        """Switch or list distributions in the current session."""
        all_distros = self.session.available_distros
        if not args or args[0] in ("list", "-l"):
            lines = [
                colorize("Available Linux Distributions:", Ansi.BOLD + Ansi.CYAN),
            ]
            for d_id, d_cfg in all_distros.items():
                active = " (current)" if d_id == self.session.distro.id else ""
                lines.append(f"  - {colorize(d_id, Ansi.BOLD + Ansi.GREEN)}{active}: {d_cfg.name} [pkg: {d_cfg.pkg_manager}]")
            lines.append("\nTo switch distro, run: " + colorize("distro <id>", Ansi.YELLOW) + " (e.g. 'distro arch')")
            out = "\n".join(lines) + "\n"
            writer.write(out)
            await writer.drain()
            return out

        target_id = args[0]
        if target_id not in all_distros:
            out = f"distro: unknown distro '{target_id}'. Type 'distro list' to view options.\n"
            writer.write(out)
            await writer.drain()
            return out

        self.session.switch_distro(all_distros[target_id])
        out = colorize(f"[*] Switched session distribution to {all_distros[target_id].name}!\n", Ansi.BOLD + Ansi.GREEN)
        writer.write(out)
        await writer.drain()
        return out

    async def cmd_tutorial(self, args: List[str], writer) -> str:
        return await self.cmd_help(args, writer)

    async def cmd_help(self, args: List[str], writer) -> str:
        text = (
            colorize("=================================================================\n", Ansi.CYAN) +
            colorize("         SimLinux - Interactive Beginner Linux Guide             \n", Ansi.BOLD + Ansi.WHITE) +
            colorize("=================================================================\n\n", Ansi.CYAN) +
            colorize("1. Essential Navigation:\n", Ansi.BOLD + Ansi.YELLOW) +
            "   pwd                  Print current working directory\n" +
            "   ls -la               List all files in current directory with details\n" +
            "   cd <dir>             Change directory (e.g. 'cd /etc' or 'cd ~')\n\n" +
            colorize("2. File Management (In-Memory Virtual Filesystem):\n", Ansi.BOLD + Ansi.YELLOW) +
            "   touch <filename>     Create a new empty file\n" +
            "   mkdir <dirname>      Create a new directory (e.g. 'mkdir mydir')\n" +
            "   cat <filename>       View file content (e.g. 'cat /etc/os-release')\n" +
            "   echo 'text' > file   Write text to file (use >> to append)\n" +
            "   rm <filename>        Delete a file (use 'rm -rf' for directories)\n\n" +
            colorize("3. Distribution Switching:\n", Ansi.BOLD + Ansi.YELLOW) +
            "   distro list          View available distros (Ubuntu, Arch, Debian, Alpine)\n" +
            "   distro arch          Switch environment to Arch Linux on the fly\n\n" +
            colorize("4. LLM-Powered Commands (Simulated by AI):\n", Ansi.BOLD + Ansi.YELLOW) +
            "   apt update / apt install nginx\n" +
            "   python3 -c \"print('Hello from SimLinux!')\"\n" +
            "   top / htop / ps aux / curl ipinfo.io / git status\n\n" +
            colorize("5. Shortcuts:\n", Ansi.BOLD + Ansi.YELLOW) +
            "   Tab: Autocomplete    Up/Down: Command History    Ctrl+C: Cancel\n" +
            "   Ctrl+L: Clear Screen exit: Disconnect\n"
        )
        writer.write(text)
        await writer.drain()
        return text

    async def cmd_exit(self, args: List[str], writer) -> str:
        writer.write("logout\n")
        await writer.drain()
        self.session.is_active = False
        return ""

    async def cmd_logout(self, args: List[str], writer) -> str:
        return await self.cmd_exit(args, writer)
