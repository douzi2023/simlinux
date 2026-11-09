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
        try:
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

            # 1. Handle Subsystem request (e.g. sftp)
            if process.subsystem:
                logger.info("[%s] Subsystem requested: %s (closing subsystem channel)", username, process.subsystem)
                process.exit(1)
                return

            # 2. Check if client executed a one-shot command (e.g. ssh user@host "uname -a")
            raw_cmd = process.command
            if raw_cmd:
                raw_cmd_str = raw_cmd.strip()
                # Intercept MobaXterm background remote monitoring loop
                if "##Moba##" in raw_cmd_str or raw_cmd_str.startswith("while"):
                    logger.info("[%s] MobaXterm background monitoring probe handled cleanly", username)
                    process.exit(0)
                    return

                logger.info("[%s] Executing one-shot command: %s", username, raw_cmd)
                try:
                    await session.dispatcher.dispatch(raw_cmd, process.stdout)
                except Exception as e:
                    logger.debug("[%s] One-shot command error: %s", username, e)
                finally:
                    try:
                        process.exit(0)
                    except Exception:
                        pass
                return

            # 3. Check for PTY
            has_pty = process.get_terminal_type() is not None
            logger.info("[%s] Shell started (PTY: %s, term: %s)", username, has_pty, process.get_terminal_type())

            # Non-interactive shell (no PTY)
            if not has_pty:
                try:
                    line = await process.stdin.readline()
                    if line:
                        await session.dispatcher.dispatch(line.strip(), process.stdout)
                except Exception as e:
                    logger.debug("[%s] Non-PTY read error: %s", username, e)
                finally:
                    try:
                        process.exit(0)
                    except Exception:
                        pass
                return

            # 4. Interactive Shell Session with PTY
            editor = getattr(process.channel, "_editor", None)
            if editor is not None and hasattr(process.channel, "register_key"):
                def tab_completer(line: str, pos: int):
                    token = line[:pos].split()[-1] if line[:pos].split() else ""
                    matches = session.get_autocompletions(line[:pos])
                    if not matches:
                        return False
                    match = matches[0] if len(matches) == 1 else os.path.commonprefix(matches)
                    if len(match) > len(token):
                        compl = match[len(token):]
                        return (line[:pos] + compl + line[pos:], pos + len(compl))
                    try:
                        process.stdout.write("\n" + "  ".join(matches) + "\n" + session.prompt())
                    except Exception:
                        pass
                    return (line, pos)

                try:
                    process.channel.register_key("\t", tab_completer)
                except Exception as e:
                    logger.debug("Could not register tab key: %s", e)

            # Display welcome banner
            try:
                process.stdout.write(session.get_motd())
                await process.stdout.drain()
            except Exception:
                pass

            # Main REPL
            prompt_needed = True
            while session.is_active:
                try:
                    if prompt_needed:
                        process.stdout.write(session.prompt())
                        await process.stdout.drain()
                        prompt_needed = False
                    cmd_line = await process.stdin.readline()
                    prompt_needed = True
                except asyncssh.TerminalSizeChanged:
                    continue
                except (asyncssh.BreakReceived, asyncssh.SignalReceived):
                    try:
                        process.stdout.write("^C\n")
                    except Exception:
                        pass
                    prompt_needed = True
                    continue
                except (asyncssh.DisconnectError, asyncssh.ConnectionLost, asyncio.CancelledError, ConnectionResetError, BrokenPipeError, OSError):
                    break
                except Exception as e:
                    logger.error("Session read error: %s", e)
                    break

                if not cmd_line or not session.is_active:
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
        except (asyncssh.DisconnectError, asyncssh.ConnectionLost, asyncio.CancelledError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception as e:
            logger.error("[%s] Session channel error: %s", username, e)
        finally:
            try:
                process.exit(0)
            except Exception:
                pass

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
        line_editor=True,
        line_echo=True,
        keepalive_interval=30,
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
