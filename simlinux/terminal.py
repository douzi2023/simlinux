import asyncio
from typing import List, Optional, Callable
import asyncssh


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    CLEAR_SCREEN = "\033[2J\033[H"
    CLEAR_LINE = "\033[2K\r"
    CLEAR_TO_EOL = "\033[K"


def colorize(text: str, color_code: str) -> str:
    return f"{color_code}{text}{Ansi.RESET}"


class LineEditor:
    """
    Asynchronous line editor providing shell line discipline for SSH PTY sessions.
    Handles echo, line editing, cursor movement, history (Up/Down), Tab-completion,
    and control keys (Ctrl+C, Ctrl+D, Ctrl+L).
    """

    def __init__(self, history_limit: int = 200):
        self.history: List[str] = []
        self.history_index: int = 0
        self.history_limit = history_limit
        self._prev_was_cr: bool = False

    async def read_line(
        self,
        reader,
        writer,
        prompt: str,
        completer: Optional[Callable[[str], List[str]]] = None
    ) -> Optional[str]:
        """
        Reads a single line interactively from the reader, echoing to writer.
        Returns the command string, or None on EOF (Ctrl+D on empty line).
        """
        writer.write(prompt)
        await writer.drain()

        buffer: List[str] = []
        cursor_pos = 0
        self.history_index = len(self.history)
        saved_current_buffer = ""

        def redraw_line():
            # Clear current line and reprint prompt + buffer
            buf_str = "".join(buffer)
            writer.write(f"\r{Ansi.CLEAR_TO_EOL}{prompt}{buf_str}")
            # Move cursor back to cursor_pos if not at end
            move_back = len(buffer) - cursor_pos
            if move_back > 0:
                writer.write(f"\033[{move_back}D")

        while True:
            try:
                char = await reader.read(1)
            except asyncssh.TerminalSizeChanged:
                # Terminal resized (e.g. MobaXterm minimized / restored / resized)
                # Keep session alive and continue reading
                continue
            except (asyncssh.DisconnectError, asyncssh.ConnectionLost, asyncio.CancelledError, ConnectionResetError, OSError):
                return None
            except Exception:
                return None

            if not char:  # Connection closed
                return None

            # Ignore trailing \n if previous character was \r (handles CRLF sent by some SSH clients)
            if char == "\n" and self._prev_was_cr:
                self._prev_was_cr = False
                continue
            self._prev_was_cr = (char == "\r")

            # Handle Enter (\r or \n)
            if char in ("\r", "\n"):
                writer.write("\n")
                await writer.drain()
                cmd = "".join(buffer).strip()
                if cmd and (not self.history or self.history[-1] != cmd):
                    self.history.append(cmd)
                    if len(self.history) > self.history_limit:
                        self.history.pop(0)
                return "".join(buffer)

            # Ctrl+C (\x03)
            elif char == "\x03":
                writer.write("^C\n")
                await writer.drain()
                return ""

            # Ctrl+D (\x04)
            elif char == "\x04":
                if len(buffer) == 0:
                    writer.write("exit\n")
                    await writer.drain()
                    return None  # Signal logout / EOF
                # If buffer not empty, ignore or delete char at cursor
                if cursor_pos < len(buffer):
                    buffer.pop(cursor_pos)
                    redraw_line()
                    await writer.drain()

            # Ctrl+L (\x0c) - Clear Screen
            elif char == "\x0c":
                writer.write(Ansi.CLEAR_SCREEN)
                redraw_line()
                await writer.drain()

            # Ctrl+U (\x15) - Clear line before cursor
            elif char == "\x15":
                buffer = buffer[cursor_pos:]
                cursor_pos = 0
                redraw_line()
                await writer.drain()

            # Backspace (\x7f or \x08)
            elif char in ("\x7f", "\x08", "\b"):
                if cursor_pos > 0:
                    cursor_pos -= 1
                    buffer.pop(cursor_pos)
                    if cursor_pos == len(buffer):
                        writer.write("\b \b")
                    else:
                        redraw_line()
                    await writer.drain()

            # Tab (\t) - Autocompletion
            elif char == "\t":
                if completer:
                    curr_text = "".join(buffer[:cursor_pos])
                    matches = completer(curr_text)
                    if len(matches) == 1:
                        # Exact single match: complete the remainder
                        match = matches[0]
                        token = curr_text.split()[-1] if curr_text.split() else ""
                        completion = match[len(token):]
                        for c in completion:
                            buffer.insert(cursor_pos, c)
                            cursor_pos += 1
                        redraw_line()
                        await writer.drain()
                    elif len(matches) > 1:
                        # Multiple matches: print them on a new line and re-prompt
                        writer.write("\n" + "  ".join(matches) + "\n")
                        redraw_line()
                        await writer.drain()

            # ANSI Escape Sequence (\x1b)
            elif char == "\x1b":
                seq = await self._read_escape_sequence(reader)
                if seq == "[A":  # Arrow Up
                    if self.history and self.history_index > 0:
                        if self.history_index == len(self.history):
                            saved_current_buffer = "".join(buffer)
                        self.history_index -= 1
                        buffer = list(self.history[self.history_index])
                        cursor_pos = len(buffer)
                        redraw_line()
                        await writer.drain()

                elif seq == "[B":  # Arrow Down
                    if self.history_index < len(self.history):
                        self.history_index += 1
                        if self.history_index == len(self.history):
                            buffer = list(saved_current_buffer)
                        else:
                            buffer = list(self.history[self.history_index])
                        cursor_pos = len(buffer)
                        redraw_line()
                        await writer.drain()

                elif seq == "[D":  # Arrow Left
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        writer.write("\033[D")
                        await writer.drain()

                elif seq == "[C":  # Arrow Right
                    if cursor_pos < len(buffer):
                        cursor_pos += 1
                        writer.write("\033[C")
                        await writer.drain()

                elif seq in ("[H", "[1~", "OH"):  # Home
                    cursor_pos = 0
                    redraw_line()
                    await writer.drain()

                elif seq in ("[F", "[4~", "OF"):  # End
                    cursor_pos = len(buffer)
                    redraw_line()
                    await writer.drain()

                elif seq == "[3~":  # Delete
                    if cursor_pos < len(buffer):
                        buffer.pop(cursor_pos)
                        redraw_line()
                        await writer.drain()

            # Normal printable characters
            elif ord(char) >= 32:
                buffer.insert(cursor_pos, char)
                cursor_pos += 1
                if cursor_pos == len(buffer):
                    writer.write(char)
                else:
                    redraw_line()
                await writer.drain()

    async def _read_escape_sequence(self, reader) -> str:
        """Reads subsequent bytes of an escape sequence with a fast timeout."""
        seq = ""
        while True:
            try:
                ch = await asyncio.wait_for(reader.read(1), timeout=0.03)
                if not ch:
                    break
                seq += ch
                # Common terminal sequence termination conditions
                if ch.isalpha() or ch == "~":
                    break
                if len(seq) >= 5:
                    break
            except asyncio.TimeoutError:
                break
        return seq
