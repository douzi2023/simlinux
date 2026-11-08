import os
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("simlinux")


@dataclass
class DistroConfig:
    id: str
    name: str
    os_release: Dict[str, str]
    uname: str
    uname_vars: Dict[str, str]
    pkg_manager: str
    installed_packages: list
    issue: str
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], distro_id: str) -> "DistroConfig":
        return cls(
            id=data.get("id", distro_id),
            name=data.get("name", distro_id),
            os_release=data.get("os_release", {}),
            uname=data.get("uname", "Linux {hostname} 5.15.0-generic x86_64 GNU/Linux"),
            uname_vars=data.get("uname_vars", {
                "hostname": "simlinux",
                "kernel": "Linux",
                "release": "5.15.0-generic",
                "arch": "x86_64"
            }),
            pkg_manager=data.get("pkg_manager", "apt"),
            installed_packages=data.get("installed_packages", []),
            issue=data.get("issue", f"{data.get('name', distro_id)} \\n \\l\n"),
            raw_data=data
        )


def load_distros(distros_dir: Path) -> Dict[str, DistroConfig]:
    distros: Dict[str, DistroConfig] = {}
    if not distros_dir.exists():
        distros_dir.mkdir(parents=True, exist_ok=True)

    for item in distros_dir.glob("*.json"):
        try:
            with open(item, "r", encoding="utf-8") as f:
                data = json.load(f)
                d_id = data.get("id", item.stem)
                distros[d_id] = DistroConfig.from_dict(data, d_id)
        except Exception as e:
            logger.warning("Failed to load distro config %s: %s", item, e)

    return distros


@dataclass
class Config:
    base_dir: Path = BASE_DIR
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    base_url: str = os.getenv("BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("OPENAI_MODEL", "deepseek-chat")
    
    ssh_host: str = os.getenv("SSH_HOST", "0.0.0.0")
    ssh_port: int = int(os.getenv("SSH_PORT", "2222"))
    ssh_host_key: str = str(BASE_DIR / os.getenv("SSH_HOST_KEY", "ssh_host_key"))
    
    ssh_username: str = os.getenv("SSH_USERNAME", "root")
    ssh_password: str = os.getenv("SSH_PASSWORD", "123")
    
    hostname: str = os.getenv("HOSTNAME", "simlinux")
    default_distro: str = os.getenv("DEFAULT_DISTRO", "ubuntu-22.04")
    
    distros: Dict[str, DistroConfig] = field(default_factory=dict)

    def __post_init__(self):
        if not self.distros:
            distros_path = self.base_dir / "distros"
            self.distros = load_distros(distros_path)
        if not self.distros:
            # Fallback default distro if distros/ folder is missing or empty
            fallback = DistroConfig.from_dict({
                "id": "ubuntu-22.04",
                "name": "Ubuntu 22.04 LTS",
                "pkg_manager": "apt",
                "os_release": {"PRETTY_NAME": "Ubuntu 22.04 LTS", "NAME": "Ubuntu", "VERSION": "22.04 LTS (Jammy Jellyfish)", "ID": "ubuntu"},
                "uname": "Linux {hostname} 5.15.0-101-generic #111-Ubuntu SMP Wed Mar 27 16:25:27 UTC 2024 x86_64 x86_64 x86_64 GNU/Linux"
            }, "ubuntu-22.04")
            self.distros["ubuntu-22.04"] = fallback
        if self.default_distro not in self.distros:
            self.default_distro = next(iter(self.distros.keys()))

    @classmethod
    def load(cls) -> "Config":
        return cls()


# Global configuration instance
config = Config.load()
