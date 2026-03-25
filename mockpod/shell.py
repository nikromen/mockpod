"""
Unified shell command building API.

All container commands should be constructed through this module.
The safe path (cmd()) is the default --- injection is structurally impossible
because every string argument is individually shlex.quote()'d.
"""

from __future__ import annotations

import shlex

_PRINTF_ESCAPE = str.maketrans({"\\": "\\\\", "%": "%%", "'": "'\\''"})


class _ShellVar:
    """Shell variable reference ($VAR). Not quoted in cmd()."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        if not name.isidentifier():
            raise ValueError(f"Invalid shell variable name: {name}")
        self.name = name

    def __repr__(self) -> str:
        return f"var({self.name!r})"


Arg = str | _ShellVar


def var(name: str) -> _ShellVar:
    """Reference a shell variable. Expands as $NAME (unquoted) in cmd()."""
    return _ShellVar(name)


def cmd(*args: Arg) -> str:
    """
    Build a shell-safe command string.

    str args are individually shlex.quote()'d.
    var() args expand as $NAME (not quoted).
    """
    if not args:
        raise ValueError("cmd() requires at least one argument")

    parts: list[str] = []
    for a in args:
        if isinstance(a, _ShellVar):
            parts.append(f"${a.name}")
        else:
            parts.append(shlex.quote(str(a)))

    return " ".join(parts)


def pipe(*commands: str) -> str:
    """Pipe cmd() outputs together: cmd(...) | cmd(...)"""
    if not commands:
        raise ValueError("pipe() requires at least one command")

    return " | ".join(commands)


def assign(varname: str, value_cmd: str) -> str:
    """Capture command output into a variable: VAR=$(cmd)"""
    if not varname.isidentifier():
        raise ValueError(f"Invalid variable name: {varname}")

    return f"{varname}=$({value_cmd})"


def write_file(content: str, dest: str) -> str:
    """
    Safely write string content to a file via printf.

    Content is printf-escaped (backslashes, percent, single quotes).
    Dest is shlex-quoted.
    """
    escaped = content.translate(_PRINTF_ESCAPE).replace("\n", "\\n")
    return f"printf '{escaped}' > {shlex.quote(dest)}"


def heredoc(dest: str, content: str, delimiter: str = "EOF") -> str:
    """Write content via quoted heredoc (no variable expansion in content)."""
    return f"cat > {shlex.quote(dest)} <<'{delimiter}'\n{content}\n{delimiter}"
