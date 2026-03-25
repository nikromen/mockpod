from __future__ import annotations

from click.testing import CliRunner

from mockpod.cli import cli


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "mockpod" in result.output
        assert "build" in result.output
        assert "shell" in result.output
        assert "sandbox" in result.output
        assert "list" in result.output
        assert "--unsafe" in result.output

    def test_build_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["build", "--help"])
        assert result.exit_code == 0
        assert "--srpm-only" in result.output
        assert "--no-cache" in result.output
        assert "--clean" in result.output
        assert "--shell" in result.output

    def test_shell_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["shell", "--help"])
        assert result.exit_code == 0
        assert "--chroot" in result.output

    def test_list_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--help"])
        assert result.exit_code == 0
        assert "--history" in result.output
        assert "--json" in result.output

    def test_logs_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "--help"])
        assert result.exit_code == 0
        assert "--show-nth" in result.output

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--bind" in result.output

    def test_clean_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["clean", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output
        assert "--cache" in result.output
        assert "--older-than" in result.output
        assert "--keep-n" in result.output

    def test_init_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "--global" in result.output
        assert "--force" in result.output

    def test_sandbox_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["sandbox", "--help"])
        assert result.exit_code == 0
        assert "artifact repo" in result.output.lower() or "sandbox" in result.output.lower()
        assert "--chroot" in result.output

    def test_repo_file_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["repo-file", "--help"])
        assert result.exit_code == 0
        assert "--baseurl" in result.output
        assert "--repo-id" in result.output
        assert "--priority" in result.output
        assert "--output" in result.output
