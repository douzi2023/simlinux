#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimLinux: LLM-Powered Simulated Linux Terminal via SSH
For Linux beginners to safely learn and practice shell commands.
"""

import argparse
import asyncio
import logging
import signal
import sys
from simlinux.config import Config
from simlinux.server import start_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("simlinux")


def parse_args():
    parser = argparse.ArgumentParser(
        description="SimLinux: Simulated Linux Terminal via SSH for Beginners",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--host", default=None, help="SSH server bind host")
    parser.add_argument("--port", "-p", type=int, default=None, help="SSH server bind port")
    parser.add_argument("--distro", "-d", default=None, help="Default Linux distribution (e.g. ubuntu-22.04, arch, debian-12, alpine-3.19)")
    parser.add_argument("--user", "-u", default=None, help="SSH login username")
    parser.add_argument("--password", default=None, help="SSH login password")
    parser.add_argument("--model", "-m", default=None, help="LLM model name (e.g. deepseek-chat, gpt-4o-mini)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    return parser.parse_args()


async def main():
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = Config.load()

    # Apply command-line overrides
    if args.host:
        cfg.ssh_host = args.host
    if args.port:
        cfg.ssh_port = args.port
    if args.distro:
        if args.distro in cfg.distros:
            cfg.default_distro = args.distro
        else:
            logger.warning("Specified distro '%s' not found. Available: %s", args.distro, list(cfg.distros.keys()))
    if args.user:
        cfg.ssh_username = args.user
    if args.password:
        cfg.ssh_password = args.password
    if args.model:
        cfg.model = args.model

    server = await start_server(cfg)

    # Setup graceful shutdown
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    
    try:
        if sys.platform == "win32":
            # On Windows, wait until KeyboardInterrupt
            while not stop_event.is_set():
                await asyncio.sleep(1)
        else:
            await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown signal received...")
    finally:
        logger.info("Stopping SimLinux server...")
        server.close()
        await server.wait_closed()
        logger.info("SimLinux server stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
