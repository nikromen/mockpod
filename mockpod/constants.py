import os
import re
from pathlib import Path

IMAGE_NAME = "mockpod-base"
CACHE_VOLUME_PREFIX = "mockpod-cache"
CONFIG_FILENAME = "mockpod.toml"
GLOBAL_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_DIR / CONFIG_FILENAME
LOCAL_CONFIG_PATH = Path(CONFIG_FILENAME)

MOCKPOD_DIR = Path(".mockpod")
ARTIFACTS_SUBDIR = "artifacts"
CACHE_SUBDIR = "cache"
BUILD_HASHES_FILE = ".build-hashes"
LATEST_SYMLINK = "latest"

DEFAULT_MOCK_CHROOT = "fedora-rawhide-x86_64"
CHROOT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
DEFAULT_IMAGE = "fedora:latest"
DEFAULT_SETUP_COMMANDS = [
    "dnf install -y mock rpmdevtools createrepo_c iptables && dnf clean all",
]

CONTAINERFILE_TEMPLATE = """\
FROM {base_image}
{setup_commands}
RUN useradd -u {builder_uid} -m -G mock builder
WORKDIR /src
"""

NETWORK_HARDENING_CMDS = [
    "iptables -A OUTPUT -d 10.0.0.0/8 -j DROP",  # RFC1918 private (class A)
    "iptables -A OUTPUT -d 172.16.0.0/12 -j DROP",  # RFC1918 private (class B)
    "iptables -A OUTPUT -d 192.168.0.0/16 -j DROP",  # RFC1918 private (class C)
    "iptables -A OUTPUT -d 169.254.0.0/16 -j DROP",  # link-local / pasta host mapping
    "iptables -A OUTPUT -d 100.64.0.0/10 -j DROP",  # CGNAT / Tailscale
    "ip6tables -A OUTPUT -d fe80::/10 -j DROP",  # IPv6 link-local
    "ip6tables -A OUTPUT -d fc00::/7 -j DROP",  # IPv6 unique local (ULA)
]
