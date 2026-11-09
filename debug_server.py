#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimLinux Debug Server: High-detail diagnostic runner for troubleshooting SSH connection issues.
Captures all AsyncSSH protocol packets, callbacks, terminal negotiations, and exceptions to a log file.
"""

import argparse
import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import asyncssh
from simlinux.config import Config
from simlinux.session import Session


LOG_FILE = BASE_DIR / "simlinux_debug.log"


def setup_debug_logging(log_path: Path):
    """Sets up verbose logging to both console and a log file."""
    # Reset log file
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("=== SimLinux Debug Log Started ===\n")

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console Handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    # File Handler (UTF-8)
    fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)

    # Configure AsyncSSH deep debugging
    asyncssh.set_log_level(logging.DEBUG)
    # Debug level 2: Full debug logging (packet types, state transitions, channels)
    asyncssh.set_debug_level(2)

    return root_logger


logger = logging.getLogger("simlinux.debug")


def global_exception_handler(loop, context):
    """Captures unhandled exceptions from background asyncio tasks."""
    msg = context.get("message")
    exc = context.get("exception")
    task = context.get("task")
    future = context.get("future")

    logger.critical("=" * 60)
    logger.critical("ASYNCIO LOOP EXCEPTION DETECTED!")
    logger.critical("  Message: %s", msg)
    logger.critical("  Task:    %r", task)
    logger.critical("  Future:  %r", future)
    if exc:
        logger.critical("  Exception: %s: %s", type(exc).__name__, exc)
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.critical("  Traceback:\n%s", "".join(tb_lines))
    logger.critical("=" * 60)


class DebugSSHServer(asyncssh.SSHServer):
    """Instrumented SSHServer that logs every connection event and callback."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._username: Optional[str] = None
        self._conn: Optional[asyncssh.SSHServerConnection] = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._conn = conn
        peer = conn.get_extra_info("peername")
        sock = conn.get_extra_info("sockname")
        logger.info("[EVENT] >>> SSH Connection accepted from %s (local: %s)", peer, sock)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if exc:
            logger.warning("[EVENT] <<< SSH Connection lost with EXCEPTION: %s: %s", type(exc).__name__, exc)
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            logger.warning("Connection lost traceback:\n%s", "".join(tb))
        else:
            logger.info("[EVENT] <<< SSH Connection closed normally (no error)")

    def begin_auth(self, username: str) -> bool:
        self._username = username
        logger.info("[AUTH] Client started authentication for username: %r", username)
        return True

    def password_auth_supported(self) -> bool:
        logger.debug("[AUTH] Query: password_auth_supported -> True")
        return True

    def kbdint_auth_supported(self) -> bool:
        logger.debug("[AUTH] Query: kbdint_auth_supported -> True")
        return True

    def validate_password(self, username: str, password: str) -> bool:
        logger.info("[AUTH] Validating password for %r", username)
        matched = (username == self.cfg.ssh_username and password == self.cfg.ssh_password)
        if matched:
            logger.info("[AUTH] Password matched successfully for %r", username)
        else:
            logger.warning("[AUTH] Password MISMATCH for %r (received: %r)", username, password)
        return matched

    def auth_completed(self) -> None:
        logger.info("[AUTH] Authentication COMPLETED for user: %r", self._username)

    def session_requested(self) -> bool:
        logger.info("[SESSION] Client requested new session channel")
        return True

    def server_requested(self, listen_host: str, listen_port: int) -> bool:
        logger.info("[TCP_FWD] Client requested remote port forwarding server on %s:%d (denied)",
                    listen_host, listen_port)
        return False

    def connection_requested(self, dest_host: str, dest_port: int,
                             orig_host: str, orig_port: int) -> bool:
        logger.info("[TCP_FWD] Client requested direct TCP forwarding to %s:%d from %s:%d (denied)",
                    dest_host, dest_port, orig_host, orig_port)
        return False

    def debug_msg_received(self, msg: str, lang: str, always_display: bool) -> None:
        logger.debug("[CLIENT_DEBUG_MSG] %r (lang=%s, always_display=%s)", msg, lang, always_display)


def create_debug_process_handler(cfg: Config):
    """Creates a debug-instrumented process handler for SSH sessions."""

    async def debug_handle_client(process: asyncssh.SSHServerProcess) -> None:
        chan = process.channel
        chan_id = getattr(chan, "_chan_id", id(chan))
        username = process.get_extra_info("username") or cfg.ssh_username
        term_type = process.get_terminal_type()
        term_size = process.get_terminal_size()
        subsystem = process.subsystem
        command = process.command
        has_pty = term_type is not None

        logger.info("[PROCESS_INIT] New process on channel [chan_id=%s]: user=%r, pty=%s (term=%s, size=%s), subsystem=%r, cmd=%r",
                    chan_id, username, has_pty, term_type, term_size, subsystem, command)

        # 1. Subsystem request check
        if subsystem:
            logger.info("[PROCESS_SUBSYSTEM] Subsystem requested: %r on chan=%s. Exiting subsystem cleanly.", subsystem, chan_id)
            process.exit(1)
            return

        # Initialize user session
        default_distro = cfg.distros.get(cfg.default_distro)
        if not default_distro and cfg.distros:
            default_distro = next(iter(cfg.distros.values()))

        session = Session(
            username=username,
            hostname=cfg.hostname,
            distro=default_distro,
            all_distros=cfg.distros,
            cfg=cfg
        )

        # 2. One-shot command
        if command:
            logger.info("[PROCESS_CMD] Executing one-shot command: %r on chan=%s", command, chan_id)
            try:
                await session.dispatcher.dispatch(command, process.stdout)
            except Exception as e:
                logger.exception("[PROCESS_CMD_ERR] Error executing one-shot command %r: %s", command, e)
            finally:
                process.exit(0)
            return

        # 3. Non-PTY Shell Session
        if not has_pty:
            logger.info("[PROCESS_NON_PTY] Non-interactive / non-PTY session on chan=%s. Waiting for input...", chan_id)
            try:
                line = await process.stdin.readline()
                logger.info("[PROCESS_NON_PTY] Read line: %r on chan=%s", line, chan_id)
                if line:
                    await session.dispatcher.dispatch(line.strip(), process.stdout)
            except Exception as e:
                logger.warning("[PROCESS_NON_PTY_ERR] Non-PTY session error on chan=%s: %s", chan_id, e)
            finally:
                process.exit(0)
            return

        # 4. Interactive PTY Shell Session
        editor = getattr(chan, "_editor", None)
        logger.info("[PROCESS_PTY] Interactive PTY session started on chan=%s. (channel._editor=%r)", chan_id, editor)

        if editor is not None and hasattr(chan, "register_key"):
            def tab_completer(line: str, pos: int):
                logger.debug("[TAB_KEY] Tab pressed at pos %d, line: %r", pos, line)
                token = line[:pos].split()[-1] if line[:pos].split() else ""
                matches = session.get_autocompletions(line[:pos])
                logger.debug("[TAB_KEY] Autocompletions found: %r", matches)
                if not matches:
                    return False
                if len(matches) == 1:
                    match = matches[0]
                    completion = match[len(token):]
                    return (line[:pos] + completion + line[pos:], pos + len(completion))

                import os
                common = os.path.commonprefix(matches)
                if len(common) > len(token):
                    completion = common[len(token):]
                    return (line[:pos] + completion + line[pos:], pos + len(completion))

                process.stdout.write("\n" + "  ".join(matches) + "\n" + session.prompt())
                return (line, pos)

            try:
                chan.register_key("\t", tab_completer)
                logger.info("[PROCESS_PTY] Tab-completion key registered successfully on chan=%s", chan_id)
            except Exception as e:
                logger.warning("[PROCESS_PTY] Could not register tab completer: %s", e)

        # Write Welcome MOTD
        motd = session.get_motd()
        logger.debug("[PROCESS_PTY] Sending MOTD banner (%d chars)...", len(motd))
        process.stdout.write(motd)
        await process.stdout.drain()
        logger.debug("[PROCESS_PTY] MOTD banner drained successfully.")

        # Interactive REPL Loop
        prompt_needed = True
        logger.info("[PROCESS_PTY] Entering main REPL loop on chan=%s", chan_id)
        while session.is_active:
            try:
                if prompt_needed:
                    prompt_str = session.prompt()
                    logger.debug("[REPL] Sending prompt: %r", prompt_str)
                    process.stdout.write(prompt_str)
                    await process.stdout.drain()
                    prompt_needed = False

                logger.debug("[REPL] Awaiting process.stdin.readline()...")
                cmd_line = await process.stdin.readline()
                logger.debug("[REPL] Readline returned: %r", cmd_line)
                prompt_needed = True

            except asyncssh.TerminalSizeChanged:
                new_size = process.get_terminal_size()
                logger.info("[REPL_EVENT] TerminalSizeChanged: new_size=%s on chan=%s", new_size, chan_id)
                continue

            except (asyncssh.BreakReceived, asyncssh.SignalReceived) as sig:
                logger.info("[REPL_EVENT] Signal / Break received: %r on chan=%s", sig, chan_id)
                process.stdout.write("^C\n")
                prompt_needed = True
                continue

            except (asyncssh.DisconnectError, asyncssh.ConnectionLost, asyncio.CancelledError, ConnectionResetError, OSError) as disc:
                logger.info("[REPL_DISC] Connection/channel disconnected (%s: %s) on chan=%s", type(disc).__name__, disc, chan_id)
                break

            except Exception as err:
                logger.exception("[REPL_EXC] Unexpected exception reading stdin on chan=%s: %s", chan_id, err)
                break

            if not cmd_line or not session.is_active:
                logger.info("[REPL_EOF] EOF or session inactive on chan=%s. Exiting loop.", chan_id)
                break

            cmd_clean = cmd_line.strip()
            if not cmd_clean:
                continue

            logger.info("[CMD_EXEC] User command on chan=%s: %r", chan_id, cmd_clean)
            session.command_history.append(cmd_clean)

            try:
                output = await session.dispatcher.dispatch(cmd_clean, process.stdout)
                if output:
                    session.llm_history.append((cmd_clean, output))
                    if len(session.llm_history) > 10:
                        session.llm_history.pop(0)
            except Exception as cmd_err:
                logger.exception("[CMD_EXEC_ERR] Exception executing command %r: %s", cmd_clean, cmd_err)

        logger.info("[PROCESS_PTY] Process exiting on chan=%s", chan_id)
        process.exit(0)

    return debug_handle_client


async def run_debug_server(host: str, port: int, cfg: Config):
    """Starts the debug SSH server."""
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(global_exception_handler)

    # Ensure host key exists
    host_key_path = cfg.ssh_host_key
    if not os.path.exists(host_key_path):
        logger.info("Generating host key at %s...", host_key_path)
        key_obj = asyncssh.generate_private_key("ssh-rsa")
        with open(host_key_path, "wb") as f:
            f.write(key_obj.export_private_key("openssh"))

    server = await asyncssh.listen(
        host,
        port,
        server_factory=lambda: DebugSSHServer(cfg),
        server_host_keys=[host_key_path],
        process_factory=create_debug_process_handler(cfg),
        line_editor=True,
        line_echo=True,
        keepalive_interval=30,
        keepalive_count_max=5,
        tcp_keepalive=True
    )

    logger.info("*" * 65)
    logger.info("  SimLinux DEBUG Server is RUNNING on %s:%d", host, port)
    logger.info("  Credentials:  ssh %s@127.0.0.1 -p %d  (Password: %s)", cfg.ssh_username, port, cfg.ssh_password)
    logger.info("  Log file:     %s", LOG_FILE)
    logger.info("  Connect now with MobaXterm to reproduce the disconnect.")
    logger.info("  Press Ctrl+C to stop the server when done.")
    logger.info("*" * 65)

    try:
        # Keep server running until cancelled
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        logger.info("Debug server stopped cleanly.")


def main():
    parser = argparse.ArgumentParser(description="SimLinux Detailed Diagnostic Server")
    parser.add_argument("--host", default=None, help="Bind host (default: from .env or 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=None, help="Bind port (default: from .env or 2222)")
    args = parser.parse_args()

    setup_debug_logging(LOG_FILE)

    cfg = Config.load()
    host = args.host or cfg.ssh_host
    port = args.port or cfg.ssh_port

    try:
        asyncio.run(run_debug_server(host, port, cfg))
    except KeyboardInterrupt:
        logger.info("Server terminated by user (Ctrl+C).")
        print(f"\n[+] Diagnostic logs have been written to:\n    {LOG_FILE}\n")


if __name__ == "__main__":
    main()
