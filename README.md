# mockpod

Paranoid mock. Build RPM packages inside isolated Podman containers (krun microVM)
so you can safely build untrusted or potentially malicious software without risking
your host system.

## Installation

Fedora:

```bash
sudo dnf copr enable nikromen/mockpod
sudo dnf install mockpod
```

Latest from main branch:

```bash
sudo dnf install mockpod-git
```

## Usage

```bash
mockpod --help
```

## Security Model

mockpod is designed for building **untrusted software**. The default mode assumes
the code you're building may be malicious and isolates it accordingly.

### Modes

| Mode            | VM           | Internet | LAN / localhost | Host volumes     |
| --------------- | ------------ | -------- | --------------- | ---------------- |
| default         | krun microVM | yes      | blocked         | none             |
| `--host-mounts` | krun microVM | yes      | blocked         | configured paths |
| `--unsafe`      | none         | yes      | open            | all configured   |

### Isolation layers (default mode)

**Layer 1: krun microVM** — The build runs inside a lightweight VM with its own
kernel. Even if malware gets root inside the VM, it cannot escape to the host.

**Layer 2: iptables + privilege drop** — The container starts as root, sets
iptables rules blocking all RFC1918/link-local/ULA output, then drops to an
unprivileged `builder` user via `runuser`. The builder has no `CAP_NET_ADMIN`,
so malware cannot flush the firewall rules.

**Layer 3: pasta network (host mapping disabled)** — Podman's pasta network
backend is configured with `--map-guest-addr,none`, blocking the implicit
host localhost mapping. Set at `podman run` time, unreachable from inside the VM.

**Layer 4: user namespace (rootless Podman)** — Podman runs rootless. There is
no host root anywhere in the chain.

### Why `--privileged`?

mock requires `--privileged` for `dnf --installroot`, chroot operations, and
`seteuid`. In rootless Podman, `--privileged` grants capabilities only within
the user namespace — it does **not** give actual root on the host. From mock's
own documentation: "podman run --privileged is a completely different thing from
docker run --privileged".

### Why SELinux disabled?

mock's SELinux plugin expects to control labeling inside the build chroot. In
containers, it detects SELinux as disabled. `label=disable` on the Podman side
is consistent with this — and it only affects the inside of the VM.

### What remains open

- **Internet** (public IPs) — required for DNF to download build dependencies
  from Fedora/EPEL repos.
- **`/results` (read-write)** — build artifacts (RPMs, logs) are written here.
  These may be infected — do not install them on your host without verification.

### What the software being built cannot do (default mode)

- Access your LAN (NAS, printers, other PCs)
- Connect to host localhost (databases, SSH agent, web servers)
- Sniff or listen to network traffic outside the VM
- Modify your source code (`/src` is read-only)
- Escape the VM to the host kernel
- Flush iptables rules (no `CAP_NET_ADMIN` as builder)
