import logging
from typing import List, Dict, Tuple, Optional
from openai import AsyncOpenAI

logger = logging.getLogger("simlinux")


class LLMEngine:
    def __init__(self, api_key: str, base_url: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.client: Optional[AsyncOpenAI] = None
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def is_configured(self) -> bool:
        return bool(self.api_key and self.client)

    async def execute_command_stream(
        self,
        command: str,
        distro_info: dict,
        cwd: str,
        files_in_cwd: List[str],
        history: List[Tuple[str, str]],
        writer
    ) -> str:
        """
        Stream simulated command output from LLM directly into the terminal writer.
        Returns the complete collected output text.
        """
        if not self.is_configured():
            msg = (
                f"bash: {command.split()[0] if command.split() else 'command'}: "
                f"command not found (LLM API key not configured in .env)\n"
            )
            writer.write(msg)
            await writer.drain()
            return msg

        # Construct concise session history
        history_text = ""
        if history:
            history_lines = []
            for h_cmd, h_out in history[-4:]:
                summary = h_out.strip()
                if len(summary) > 200:
                    summary = summary[:200] + "..."
                history_lines.append(f"$ {h_cmd}\n{summary}")
            history_text = "\n".join(history_lines)

        distro_name = distro_info.get("name", "Linux")
        pkg_manager = distro_info.get("pkg_manager", "apt")
        installed_pkgs = distro_info.get("installed_packages", [])

        system_prompt = (
            f"You are an authentic Linux terminal simulator. You are simulating an interactive shell on {distro_name}.\n"
            f"OS Details:\n"
            f"- Distribution: {distro_name}\n"
            f"- Package Manager: {pkg_manager}\n"
            f"- Pre-installed Packages: {', '.join(installed_pkgs[:25])}\n"
            f"- Current Working Directory (CWD): {cwd}\n"
            f"- Files/Folders currently in CWD: {', '.join(files_in_cwd) if files_in_cwd else '(empty directory)'}\n"
            "\n"
            "STRICT RULES:\n"
            "1. Output ONLY the raw terminal standard output (stdout) and standard error (stderr).\n"
            "2. DO NOT output markdown code blocks (NO ``` or ```bash fences).\n"
            "3. DO NOT output conversational explanations, notes, intros, or apologies.\n"
            "4. Respect the distro specifics (e.g. if package manager is apt, pacman command should fail unless on Arch).\n"
            "5. If a command runs interactively (like top, htop, vi, nano), output a single terminal snapshot representation.\n"
            "6. If the command would normally produce no output (e.g. successful mv, cp, export), produce empty output.\n"
            "7. If the command does not exist, output standard shell error, e.g. `bash: <cmd>: command not found`.\n"
        )

        user_content = f"CWD: {cwd}\n"
        if history_text:
            user_content += f"Recent History:\n{history_text}\n\n"
        user_content += f"Execute command: {command}"

        collected_output = []
        in_code_block = False
        first_chunk = True

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.1,
                stream=True,
                max_tokens=1000
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = delta.content or ""
                if not text:
                    continue

                # Strip potential markdown fences if model mistakenly emitted them
                if first_chunk:
                    text_lstrip = text.lstrip()
                    if text_lstrip.startswith("```"):
                        lines = text.split("\n", 1)
                        text = lines[1] if len(lines) > 1 else ""
                        in_code_block = True
                    first_chunk = False

                if in_code_block and "```" in text:
                    text = text.replace("```", "")

                collected_output.append(text)
                
                # Normalize newlines; asyncssh PTY automatically translates \n to \r\n
                normalized_text = text.replace("\r\n", "\n")
                writer.write(normalized_text)
                await writer.drain()

            full_output = "".join(collected_output)
            # Ensure final newline if output was non-empty and didn't end in newline
            if full_output and not full_output.endswith("\n"):
                writer.write("\n")
                await writer.drain()

            return full_output

        except Exception as e:
            logger.error("LLM execution error: %s", e)
            error_msg = f"simlinux: error communicating with LLM backend: {e}\n"
            writer.write(error_msg)
            await writer.drain()
            return error_msg
