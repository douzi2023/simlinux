# -*- coding: utf-8 -*-
import datetime
import re
import shlex
import time
from typing import List, Optional
from simlinux.terminal import Ansi, colorize


class CommandDispatcher:
    def __init__(self, session):
        self.session = session

    async def _write(self, writer, text: str) -> str:
        if text:
            try:
                writer.write(text)
                await writer.drain()
            except Exception:
                pass
        return text

    async def dispatch(self, cmd_line: str, writer) -> str:
        cmd_line = cmd_line.strip()
        if not cmd_line:
            return ""

        # Handle chained commands (e.g. cmd1; cmd2; cmd3)
        if ";" in cmd_line:
            sub_cmds = [c.strip() for c in cmd_line.split(";") if c.strip()]
            outputs = []
            for sub in sub_cmds:
                out = await self.dispatch_single(sub, writer)
                if out:
                    outputs.append(out)
            return "".join(outputs)

        return await self.dispatch_single(cmd_line, writer)

    async def dispatch_single(self, cmd_line: str, writer) -> str:
        cmd_line = cmd_line.strip()
        if not cmd_line:
            return ""

        # Redirection check (> or >>)
        redirect_mode = None
        target_file = None
        main_cmd = cmd_line

        redir_match = re.search(r"\s*(>>|>)\s*([^\s|;&]+)$", cmd_line)
        if redir_match:
            op = redir_match.group(1)
            target_file = redir_match.group(2).strip()
            main_cmd = cmd_line[:redir_match.start()].strip()
            redirect_mode = "append" if op == ">>" else "write"

        try:
            tokens = shlex.split(main_cmd)
        except ValueError:
            tokens = main_cmd.split()

        if not tokens:
            return ""

        cmd_name = tokens[0]
        args = tokens[1:]

        builtin_func = getattr(self, f"cmd_{cmd_name.replace('-', '_')}", None)
        if builtin_func:
            try:
                output = await builtin_func(args, writer)
            except Exception as e:
                output = await self._write(writer, f"bash: {cmd_name}: {e}\n")
        else:
            output = await self._dispatch_to_llm(main_cmd, writer)
            self._post_llm_vfs_sync(main_cmd, output)

        if redirect_mode and target_file:
            try:
                self.session.vfs.write_file(
                    target_file,
                    output,
                    cwd=self.session.cwd,
                    append=(redirect_mode == "append"),
                    owner=self.session.username
                )
                output = ""
            except Exception as e:
                return await self._write(writer, f"bash: {target_file}: {e}\n")

        return output

    async def _dispatch_to_llm(self, command: str, writer) -> str:
        vfs = self.session.vfs
        try:
            cwd_nodes = [node.name for node in vfs.list_dir(self.session.cwd)]
        except Exception:
            cwd_nodes = []

        hardware = {
            "cpu_cores": getattr(self.session.cfg, "cpu_cores", 2),
            "cpu_model": getattr(self.session.cfg, "cpu_model", "Intel(R) Core(TM) Virtual CPU @ 2.80GHz"),
            "memory_gb": getattr(self.session.cfg, "memory_gb", 8),
            "disk_gb": getattr(self.session.cfg, "disk_gb", 40)
        }

        return await self.session.llm_engine.execute_command_stream(
            command=command,
            distro_info=self.session.distro.raw_data,
            cwd=self.session.cwd,
            files_in_cwd=cwd_nodes,
            history=self.session.llm_history,
            hardware=hardware,
            writer=writer
        )

    def _post_llm_vfs_sync(self, command: str, output: str) -> None:
        tokens = command.split()
        if not tokens:
            return
        cmd = tokens[0]
        vfs, cwd, user = self.session.vfs, self.session.cwd, self.session.username
        try:
            if cmd == "git" and len(tokens) >= 3 and tokens[1] == "clone":
                repo_name = tokens[2].rstrip("/").split("/")[-1].replace(".git", "")
                vfs.mkdir(repo_name, cwd=cwd, owner=user)
                vfs.mkdir(f"{repo_name}/.git", cwd=cwd, recursive=True, owner=user)
                vfs.write_file(f"{repo_name}/README.md", f"# {repo_name}\nCloned via SimLinux\n", cwd=cwd, owner=user)
            elif (cmd == "wget" and len(tokens) >= 2) or (cmd == "curl" and "-O" in tokens):
                fname = tokens[-1].rstrip("/").split("/")[-1] or "download"
                vfs.write_file(fname, "Simulated downloaded content\n", cwd=cwd, owner=user)
        except Exception:
            pass

    # --- Builtin Commands ---

    async def cmd_unset(self, args: List[str], writer) -> str:
        return ""

    async def cmd_export(self, args: List[str], writer) -> str:
        return ""

    async def cmd_true(self, args: List[str], writer) -> str:
        return ""

    async def cmd_sleep(self, args: List[str], writer) -> str:
        return ""

    async def cmd_pwd(self, args: List[str], writer) -> str:
        return await self._write(writer, f"{self.session.cwd}\n")

    async def cmd_cd(self, args: List[str], writer) -> str:
        target = args[0] if args else "~"
        if target == "-":
            target = self.session.oldpwd

        resolved = self.session.vfs.resolve_path(target, self.session.cwd)
        node = self.session.vfs.get_node(resolved)
        if node is None:
            return await self._write(writer, f"bash: cd: {target}: No such file or directory\n")
        if not node.is_dir:
            return await self._write(writer, f"bash: cd: {target}: Not a directory\n")

        self.session.oldpwd = self.session.cwd
        self.session.cwd = resolved
        return ""

    async def cmd_ls(self, args: List[str], writer) -> str:
        show_all = any("a" in a for a in args if a.startswith("-"))
        long_format = any("l" in a for a in args if a.startswith("-"))
        target_path = next((a for a in args if not a.startswith("-")), self.session.cwd)

        try:
            nodes = self.session.vfs.list_dir(target_path, self.session.cwd)
        except Exception as e:
            return await self._write(writer, f"{e}\n")

        if not show_all:
            nodes = [n for n in nodes if not n.name.startswith(".")]

        lines = []
        if long_format:
            total_size = sum(n.size for n in nodes)
            lines.append(f"total {total_size // 1024 + 1}")
            for n in nodes:
                date_str = datetime.datetime.fromtimestamp(n.mtime).strftime("%b %d %H:%M")
                name_col = colorize(n.name, Ansi.BOLD + Ansi.BLUE) if n.is_dir else (
                    colorize(n.name, Ansi.BOLD + Ansi.GREEN) if "x" in n.mode else n.name
                )
                lines.append(f"{n.mode} 1 {n.owner} {n.group} {n.size:5d} {date_str} {name_col}")
        else:
            names = [
                colorize(n.name, Ansi.BOLD + Ansi.BLUE) if n.is_dir else (
                    colorize(n.name, Ansi.BOLD + Ansi.GREEN) if "x" in n.mode else n.name
                ) for n in nodes
            ]
            if names:
                lines.append("  ".join(names))

        out = "\n".join(lines) + ("\n" if lines else "")
        return await self._write(writer, out)

    async def cmd_ll(self, args: List[str], writer) -> str:
        return await self.cmd_ls(["-la"] + args, writer)

    async def cmd_cat(self, args: List[str], writer) -> str:
        if not args:
            return ""
        out_chunks = []
        for file_path in args:
            try:
                out_chunks.append(self.session.vfs.read_file(file_path, self.session.cwd))
            except Exception as e:
                out_chunks.append(f"{e}\n")
        return await self._write(writer, "".join(out_chunks))

    async def cmd_touch(self, args: List[str], writer) -> str:
        if not args:
            return await self._write(writer, "touch: missing file operand\n")
        for path in args:
            try:
                node = self.session.vfs.get_node(path, self.session.cwd)
                if node:
                    node.mtime = time.time()
                else:
                    self.session.vfs.write_file(path, "", cwd=self.session.cwd, owner=self.session.username)
            except Exception as e:
                return await self._write(writer, f"touch: cannot touch '{path}': {e}\n")
        return ""

    async def cmd_mkdir(self, args: List[str], writer) -> str:
        recursive = any(a in ("-p", "--parents") for a in args)
        dirs = [a for a in args if a not in ("-p", "--parents")]
        if not dirs:
            return await self._write(writer, "mkdir: missing operand\n")
        for d in dirs:
            try:
                self.session.vfs.mkdir(d, cwd=self.session.cwd, recursive=recursive, owner=self.session.username)
            except Exception as e:
                return await self._write(writer, f"{e}\n")
        return ""

    async def cmd_rm(self, args: List[str], writer) -> str:
        recursive = any("r" in a or "R" in a for a in args if a.startswith("-"))
        force = any("f" in a for a in args if a.startswith("-"))
        targets = [a for a in args if not a.startswith("-")]
        if not targets and not force:
            return await self._write(writer, "rm: missing operand\n")
        for t in targets:
            try:
                self.session.vfs.remove(t, cwd=self.session.cwd, recursive=recursive, force=force)
            except Exception as e:
                return await self._write(writer, f"{e}\n")
        return ""

    async def cmd_echo(self, args: List[str], writer) -> str:
        if args == ["$$"]:
            return await self._write(writer, "1234\n")
        return await self._write(writer, f"{' '.join(args)}\n")

    async def cmd_whoami(self, args: List[str], writer) -> str:
        return await self._write(writer, f"{self.session.username}\n")

    async def cmd_id(self, args: List[str], writer) -> str:
        out = (
            "uid=0(root) gid=0(root) groups=0(root)\n" if self.session.username == "root" else
            f"uid=1000({self.session.username}) gid=1000({self.session.username}) groups=1000({self.session.username}),27(sudo)\n"
        )
        return await self._write(writer, out)

    async def cmd_hostname(self, args: List[str], writer) -> str:
        return await self._write(writer, f"{self.session.hostname}\n")

    async def cmd_uname(self, args: List[str], writer) -> str:
        distro = self.session.distro
        vars_dict = {
            "hostname": self.session.hostname,
            "kernel": "Linux",
            "release": "5.15.0-generic",
            "arch": "x86_64",
            **distro.uname_vars
        }
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
            out = distro.uname.format(**vars_dict) + "\n"
        return await self._write(writer, out)

    async def cmd_df(self, args: List[str], writer) -> str:
        human = any("h" in a for a in args if a.startswith("-"))
        disk_gb = getattr(self.session.cfg, "disk_gb", 40)
        total_kb = disk_gb * 1024 * 1024
        used_kb = int(total_kb * 0.18)
        avail_kb = total_kb - used_kb
        pct = int(used_kb / total_kb * 100)

        if human:
            out = (
                "Filesystem      Size  Used Avail Use% Mounted on\n"
                f"/dev/root       {disk_gb}G  {used_kb // (1024*1024) + 1}G   {avail_kb // (1024*1024)}G  {pct}% /\n"
                "tmpfs           3.9G     0  3.9G   0% /dev/shm\n"
            )
        else:
            out = (
                "Filesystem     1K-blocks      Used Available Use% Mounted on\n"
                f"/dev/root       {total_kb:8d}  {used_kb:8d}  {avail_kb:8d}  {pct}% /\n"
                "tmpfs            4096000         0   4096000   0% /dev/shm\n"
            )
        return await self._write(writer, out)

    async def cmd_free(self, args: List[str], writer) -> str:
        human = any("h" in a or "m" in a or "g" in a for a in args if a.startswith("-"))
        mem_gb = getattr(self.session.cfg, "memory_gb", 8)
        total_kb = mem_gb * 1024 * 1024
        used_kb = int(total_kb * 0.22)
        free_kb = int(total_kb * 0.65)
        buff_kb = int(total_kb * 0.13)
        avail_kb = total_kb - used_kb

        if human:
            out = (
                "               total        used        free      shared  buff/cache   available\n"
                f"Mem:           {mem_gb:.1f}Gi       {used_kb / (1024*1024):.1f}Gi       {free_kb / (1024*1024):.1f}Gi        12Mi       {buff_kb / (1024*1024):.1f}Gi       {avail_kb / (1024*1024):.1f}Gi\n"
                "Swap:          2.0Gi          0B       2.0Gi\n"
            )
        else:
            out = (
                "               total        used        free      shared  buff/cache   available\n"
                f"Mem:        {total_kb:8d}    {used_kb:8d}    {free_kb:8d}       12288    {buff_kb:8d}    {avail_kb:8d}\n"
                "Swap:        2097148           0     2097148\n"
            )
        return await self._write(writer, out)

    async def cmd_nproc(self, args: List[str], writer) -> str:
        cores = getattr(self.session.cfg, "cpu_cores", 2)
        return await self._write(writer, f"{cores}\n")

    async def cmd_lscpu(self, args: List[str], writer) -> str:
        cores = getattr(self.session.cfg, "cpu_cores", 2)
        model = getattr(self.session.cfg, "cpu_model", "Intel(R) Core(TM) Virtual CPU @ 2.80GHz")
        core_list = f"0-{cores-1}" if cores > 1 else "0"
        out = (
            "Architecture:                    x86_64\n"
            "CPU op-mode(s):                  32-bit, 64-bit\n"
            "Byte Order:                      Little Endian\n"
            f"CPU(s):                          {cores}\n"
            f"On-line CPU(s) list:             {core_list}\n"
            "Vendor ID:                       GenuineIntel\n"
            f"Model name:                      {model}\n"
            "CPU MHz:                         2800.000\n"
            "BogoMIPS:                        5600.00\n"
            "Virtualization:                  VT-x\n"
            "L1d cache:                       64 KiB\n"
            "L1i cache:                       64 KiB\n"
            "L2 cache:                        1 MiB\n"
            "L3 cache:                        16 MiB\n"
        )
        return await self._write(writer, out)

    async def cmd_ps(self, args: List[str], writer) -> str:
        out = (
            "UID        PID  PPID  C STIME TTY          TIME CMD\n"
            "root         1     0  0 00:00 ?        00:00:01 /sbin/init\n"
            f"{self.session.username}      1234     1  0 00:00 ?        00:00:00 -bash\n"
            f"{self.session.username}      1235  1234  0 00:00 ?        00:00:00 ps\n"
        )
        return await self._write(writer, out)

    async def cmd_head(self, args: List[str], writer) -> str:
        lines_n = 10
        target = None
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try: lines_n = int(args[i + 1])
                except ValueError: pass
                i += 2
            elif args[i].startswith("-n"):
                try: lines_n = int(args[i][2:])
                except ValueError: pass
                i += 1
            elif not args[i].startswith("-"):
                target = args[i]
                i += 1
            else:
                i += 1
        if not target:
            return ""
        try:
            content = self.session.vfs.read_file(target, self.session.cwd)
            lines = content.splitlines()[:lines_n]
            return await self._write(writer, "\n".join(lines) + ("\n" if lines else ""))
        except Exception as e:
            return await self._write(writer, f"head: {target}: {e}\n")

    async def cmd_tail(self, args: List[str], writer) -> str:
        lines_n = 10
        target = None
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                try: lines_n = int(args[i + 1])
                except ValueError: pass
                i += 2
            elif args[i].startswith("-n"):
                try: lines_n = int(args[i][2:])
                except ValueError: pass
                i += 1
            elif not args[i].startswith("-"):
                target = args[i]
                i += 1
            else:
                i += 1
        if not target:
            return ""
        try:
            content = self.session.vfs.read_file(target, self.session.cwd)
            lines = content.splitlines()[-lines_n:]
            return await self._write(writer, "\n".join(lines) + ("\n" if lines else ""))
        except Exception as e:
            return await self._write(writer, f"tail: {target}: {e}\n")

    async def cmd_date(self, args: List[str], writer) -> str:
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%a %b %d %H:%M:%S UTC %Y")
        return await self._write(writer, f"{now_str}\n")

    async def cmd_uptime(self, args: List[str], writer) -> str:
        t_str = datetime.datetime.now().strftime("%H:%M:%S")
        return await self._write(writer, f" {t_str} up 12 days,  4:18,  1 user,  load average: 0.12, 0.08, 0.03\n")

    async def cmd_clear(self, args: List[str], writer) -> str:
        return await self._write(writer, Ansi.CLEAR_SCREEN)

    async def cmd_history(self, args: List[str], writer) -> str:
        lines = [f"  {i:4d}  {cmd}" for i, cmd in enumerate(self.session.command_history, 1)]
        return await self._write(writer, "\n".join(lines) + ("\n" if lines else ""))

    async def cmd_distro(self, args: List[str], writer) -> str:
        all_distros = self.session.available_distros
        if not args or args[0] in ("list", "-l"):
            lines = [colorize("Available Linux Distributions:", Ansi.BOLD + Ansi.CYAN)]
            for d_id, d_cfg in all_distros.items():
                active = " (current)" if d_id == self.session.distro.id else ""
                lines.append(f"  - {colorize(d_id, Ansi.BOLD + Ansi.GREEN)}{active}: {d_cfg.name} [pkg: {d_cfg.pkg_manager}]")
            lines.append("\nTo switch distro, run: " + colorize("distro <id>", Ansi.YELLOW) + " (e.g. 'distro arch')")
            return await self._write(writer, "\n".join(lines) + "\n")

        target_id = args[0]
        if target_id not in all_distros:
            return await self._write(writer, f"distro: unknown distro '{target_id}'. Type 'distro list' to view options.\n")

        self.session.switch_distro(all_distros[target_id])
        return await self._write(writer, colorize(f"[*] Switched session distribution to {all_distros[target_id].name}!\n", Ansi.BOLD + Ansi.GREEN))

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
        return await self._write(writer, text)

    async def cmd_exit(self, args: List[str], writer) -> str:
        self.session.is_active = False
        return await self._write(writer, "logout\n")

    async def cmd_logout(self, args: List[str], writer) -> str:
        return await self.cmd_exit(args, writer)
