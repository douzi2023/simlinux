import asyncio
import sys
import asyncssh
from simlinux.config import Config
from simlinux.server import start_server


async def test_simlinux_flow():
    cfg = Config.load()
    cfg.ssh_port = 2225  # Use a dedicated port for testing
    cfg.ssh_host = "127.0.0.1"

    print("--- Starting SimLinux test server on port 2225 ---")
    server = await start_server(cfg)

    try:
        print("--- Connecting test client via SSH ---")
        async with asyncssh.connect(
            "127.0.0.1",
            port=2225,
            username=cfg.ssh_username,
            password=cfg.ssh_password,
            known_hosts=None
        ) as conn:
            print("SSH connection authenticated successfully!")

            # 1. Test one-shot non-interactive command
            print("\n[Test 1] One-shot command execution:")
            result = await conn.run("uname -a")
            print("One-shot output:", result.stdout.strip())
            assert "Linux" in result.stdout

            # 2. Test interactive shell session with PTY
            print("\n[Test 2] Interactive Shell Session:")
            async with conn.create_process(term_type="xterm-256color") as proc:
                # Read welcome banner until prompt
                banner_data = ""
                while "# " not in banner_data and "$ " not in banner_data:
                    chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=5.0)
                    banner_data += chunk
                print("Received Welcome Banner & Prompt:")
                print(banner_data.strip()[:200] + "...\n")

                # Helper to send command and read output until next prompt
                async def send_cmd(cmd: str) -> str:
                    proc.stdin.write(cmd + "\r")
                    await proc.stdin.drain()
                    out = ""
                    while True:
                        chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=15.0)
                        out += chunk
                        # Clean ANSI escape sequences for checking prompt
                        if ("# " in out or "$ " in out) and cmd in out:
                            # If prompt appeared after the command echo
                            break
                    return out

                # Test navigation & VFS
                print("Testing: pwd")
                out = await send_cmd("pwd")
                print("Output:", repr(out.strip()))
                assert "/root" in out

                print("Testing: mkdir myproject && cd myproject")
                await send_cmd("mkdir myproject")
                await send_cmd("cd myproject")
                out = await send_cmd("pwd")
                print("Output:", repr(out.strip()))
                assert "/root/myproject" in out

                print("Testing: echo 'Hello SimLinux!' > test.txt")
                await send_cmd("echo 'Hello SimLinux!' > test.txt")
                out = await send_cmd("cat test.txt")
                print("Output:", repr(out.strip()))
                assert "Hello SimLinux!" in out

                print("Testing: ls -la")
                out = await send_cmd("ls -la")
                print("Output:", repr(out.strip()))
                assert "test.txt" in out

                # Test distro switching
                print("\n[Test 3] Testing Distro Switch to Arch Linux:")
                out = await send_cmd("distro arch")
                print("Distro switch output:", repr(out.strip()))
                out = await send_cmd("cat /etc/os-release")
                print("os-release output:", repr(out.strip()))
                assert "Arch Linux" in out

                # Test LLM simulated command
                print("\n[Test 4] Testing LLM simulated command:")
                print("Sending command: pacman -Sy")
                out = await send_cmd("pacman -Sy")
                print("LLM simulated output:")
                print(out.strip())

                # Test exit
                print("\n[Test 5] Testing exit command:")
                proc.stdin.write("exit\r")
                await proc.stdin.drain()
                await asyncio.sleep(0.5)

        print("\nAll integration tests passed successfully!")

    finally:
        server.close()
        await server.wait_closed()
        print("Server closed cleanly.")


if __name__ == "__main__":
    asyncio.run(test_simlinux_flow())
