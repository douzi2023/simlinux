import asyncio
import logging
import os
from typing import Optional
import asyncssh
from simlinux.config import Config, config as default_config
from simlinux.session import Session

logger = logging.getLogger("simlinux")


class SimSSHServer(asyncssh.SSHServer):
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._username: Optional[str] = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        peer = conn.get_extra_info("peername")
        logger.info("New SSH connection from %s", peer)

    def begin_auth(self, username: str) -> bool:
        self._username = username
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        # Check against configured credentials
        if username == self.cfg.ssh_username and password == self.cfg.ssh_password:
            logger.info("Authentication successful for user: %s", username)
            return True
        logger.warning("Failed login attempt for user: %s", username)
        return False


def create_process_handler(cfg: Config):
    async def handle_client(process: asyncssh.SSHServerProcess) -> None:
        username = process.get_extra_info("username") or cfg.ssh_username
        default_distro = cfg.distros.get(cfg.default_distro)
        if not default_distro:
            default_distro = next(iter(cfg.distros.values()))

        session = Session(
            username=username,
            hostname=cfg.hostname,
            distro=default_distro,
            all_distros=cfg.distros,
            cfg=cfg
        )

        # Check if client executed a one-shot command (e.g. ssh user@host "uname -a")
        raw_cmd = process.command
        if raw_cmd:
            logger.info("[%s] Executing one-shot command: %s", username, raw_cmd)
            await session.dispatcher.dispatch(raw_cmd, process.stdout)
            process.exit(0)
            return

        # Interactive Shell Session
        has_pty = process.get_terminal_type() is not None
        logger.info("[%s] Shell started (PTY: %s, term: %s)", username, has_pty, process.get_terminal_type())

        # Display welcome banner
        process.stdout.write(session.get_motd())
        await process.stdout.drain()

        # Main REPL
        while session.is_active:
            try:
                cmd_line = await session.line_editor.read_line(
                    reader=process.stdin,
                    writer=process.stdout,
                    prompt=session.prompt(),
                    completer=session.get_autocompletions
                )
            except Exception as e:
                logger.error("Session read error: %s", e)
                break

            # None indicates EOF / exit / Ctrl+D on empty line
            if cmd_line is None or not session.is_active:
                break

            cmd_clean = cmd_line.strip()
            if not cmd_clean:
                continue

            session.command_history.append(cmd_clean)
            logger.info("[%s] CMD: %s", username, cmd_clean)

            output = await session.dispatcher.dispatch(cmd_clean, process.stdout)
            if output:
                session.llm_history.append((cmd_clean, output))
                if len(session.llm_history) > 10:
                    session.llm_history.pop(0)

        logger.info("[%s] Session closed", username)
        process.exit(0)

    return handle_client


async def start_server(cfg: Config = default_config):
    # Ensure SSH host key exists
    host_key_path = cfg.ssh_host_key
    if not os.path.exists(host_key_path):
        logger.info("Generating SSH host key at %s...", host_key_path)
        key_obj = asyncssh.generate_private_key("ssh-rsa")
        key_bytes = key_obj.export_private_key("openssh")
        with open(host_key_path, "wb") as f:
            f.write(key_bytes)
        logger.info("Host key generated successfully.")

    server = await asyncssh.listen(
        cfg.ssh_host,
        cfg.ssh_port,
        server_factory=lambda: SimSSHServer(cfg),
        server_host_keys=[host_key_path],
        process_factory=create_process_handler(cfg),
        line_editor=False,
        line_echo=False,
        keepalive_interval=15,
        keepalive_count_max=5,
        tcp_keepalive=True
    )

    logger.info("=" * 60)
    logger.info("  SimLinux SSH Server is RUNNING on %s:%d", cfg.ssh_host, cfg.ssh_port)
    logger.info("  Default Distribution: %s", cfg.default_distro)
    logger.info("  Login credentials:     ssh %s@<ip> -p %d  (Password: %s)", cfg.ssh_username, cfg.ssh_port, cfg.ssh_password)
    logger.info("  AI Backend:            %s (%s)", cfg.model, cfg.base_url)
    logger.info("=" * 60)

    return server
