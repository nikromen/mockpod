from __future__ import annotations

import functools
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

import click


def start_server(
    resultdir: Path,
    *,
    chroot: Optional[str] = None,
    port: int = 8080,
    bind: str = "127.0.0.1",
) -> None:
    """Serve the artifact repo over HTTP for use as a DNF repo."""
    serve_dir = resultdir / chroot if chroot else resultdir
    if not serve_dir.exists():
        raise click.ClickException(f"Directory does not exist: {serve_dir}")

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(serve_dir))

    server = HTTPServer((bind, port), handler)
    url = f"http://{bind}:{port}"
    click.echo(f"Serving {serve_dir} at {url}")

    if chroot:
        click.echo(f"DNF repo URL: {url}/")
    else:
        click.echo("Available chroots:")
        for d in sorted(serve_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                click.echo(f"  {url}/{d.name}/")

    click.echo("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        server.server_close()
