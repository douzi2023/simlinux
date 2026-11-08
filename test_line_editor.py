import asyncio
import unittest
from simlinux.terminal import LineEditor


class MockReader:
    def __init__(self, data: str):
        self.data = data
        self.index = 0

    async def read(self, n: int = 1):
        if self.index >= len(self.data):
            return ""
        ch = self.data[self.index]
        self.index += 1
        return ch


class MockWriter:
    def __init__(self):
        self.output = ""

    def write(self, s: str):
        self.output += s

    async def drain(self):
        pass


class TestLineEditor(unittest.IsolatedAsyncioTestCase):
    async def test_simple_input(self):
        editor = LineEditor()
        reader = MockReader("ls -la\r")
        writer = MockWriter()
        line = await editor.read_line(reader, writer, "$ ")
        self.assertEqual(line, "ls -la")
        self.assertIn("ls -la", editor.history)

    async def test_backspace(self):
        editor = LineEditor()
        # Type 'helx' then backspace (delete 'x') then 'lo\r'
        reader = MockReader("helx\x7flo\r")
        writer = MockWriter()
        line = await editor.read_line(reader, writer, "$ ")
        self.assertEqual(line, "hello")

    async def test_history_navigation(self):
        editor = LineEditor()
        editor.history = ["uname -a", "df -h"]

        # Press Up arrow (\x1b[A) then Enter (\r)
        reader = MockReader("\x1b[A\r")
        writer = MockWriter()
        line = await editor.read_line(reader, writer, "$ ")
        self.assertEqual(line, "df -h")

    async def test_tab_completion(self):
        editor = LineEditor()
        # Completer knows 'status'
        def completer(text):
            candidates = ["status", "start", "stop"]
            token = text.split()[-1] if text.split() else ""
            return [c for c in candidates if c.startswith(token)]

        # Type 'sta' then Tab, should produce multiple matches
        reader = MockReader("sta\ttus\r")
        writer = MockWriter()
        line = await editor.read_line(reader, writer, "$ ", completer=completer)
        self.assertEqual(line, "status")


if __name__ == "__main__":
    unittest.main()
