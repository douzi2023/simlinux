import unittest
from simlinux.vfs import VirtualFileSystem
from simlinux.config import DistroConfig


class TestVFS(unittest.TestCase):
    def setUp(self):
        self.vfs = VirtualFileSystem()
        distro = {
            "name": "Ubuntu 22.04 LTS",
            "os_release": {"NAME": "Ubuntu", "VERSION": "22.04"},
            "uname": "Linux {hostname} 5.15.0 x86_64",
            "uname_vars": {"hostname": "simlinux", "kernel": "Linux", "release": "5.15.0", "arch": "x86_64"},
            "issue": "Ubuntu 22.04 LTS\n"
        }
        self.vfs.init_standard_linux_tree(distro, "simlinux")

    def test_standard_dirs(self):
        for d in ["/etc", "/bin", "/root", "/proc", "/home/user"]:
            self.assertTrue(self.vfs.is_dir(d), f"Dir {d} should exist")

    def test_file_operations(self):
        # Write and read
        self.vfs.write_file("/root/hello.txt", "World")
        self.assertEqual(self.vfs.read_file("/root/hello.txt"), "World")

        # Append
        self.vfs.write_file("/root/hello.txt", " Again", append=True)
        self.assertEqual(self.vfs.read_file("/root/hello.txt"), "World Again")

        # List
        files = [n.name for n in self.vfs.list_dir("/root")]
        self.assertIn("hello.txt", files)

        # Remove
        self.vfs.remove("/root/hello.txt")
        self.assertFalse(self.vfs.exists("/root/hello.txt"))

    def test_relative_paths(self):
        self.vfs.mkdir("/root/sub1/sub2", recursive=True)
        resolved = self.vfs.resolve_path("../../../etc", cwd="/root/sub1/sub2")
        self.assertEqual(resolved, "/etc")

        resolved_root = self.vfs.resolve_path("../../etc", cwd="/root/sub1/sub2")
        self.assertEqual(resolved_root, "/root/etc")

        home_resolved = self.vfs.resolve_path("~/notes.txt", cwd="/root")
        self.assertEqual(home_resolved, "/root/notes.txt")


if __name__ == "__main__":
    unittest.main()
