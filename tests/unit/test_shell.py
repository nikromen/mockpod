from __future__ import annotations

import pytest

from mockpod.shell import _ShellVar, assign, cmd, heredoc, pipe, var, write_file


class TestCmd:
    def test_simple_command(self) -> None:
        assert cmd("ls", "-la") == "ls -la"

    def test_quoting_spaces(self) -> None:
        result = cmd("echo", "hello world")
        assert result == "echo 'hello world'"

    def test_quoting_special_chars(self) -> None:
        result = cmd("echo", "$(rm -rf /)")
        assert result == "echo '$(rm -rf /)'"

    def test_quoting_semicolons(self) -> None:
        result = cmd("echo", "foo; rm -rf /")
        assert result == "echo 'foo; rm -rf /'"

    def test_quoting_backticks(self) -> None:
        result = cmd("echo", "`whoami`")
        assert result == "echo '`whoami`'"

    def test_quoting_pipes(self) -> None:
        result = cmd("echo", "foo | bar")
        assert result == "echo 'foo | bar'"

    def test_single_quotes_in_value(self) -> None:
        result = cmd("echo", "it's a test")
        assert "echo" in result

    def test_empty_string_arg(self) -> None:
        result = cmd("echo", "")
        assert result == "echo ''"

    def test_no_args_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one argument"):
            cmd()

    def test_var_expansion(self) -> None:
        result = cmd("mock", "--rebuild", var("SRPM"))
        assert result == "mock --rebuild $SRPM"

    def test_var_not_quoted(self) -> None:
        result = cmd("echo", var("HOME"))
        assert result == "echo $HOME"

    def test_mixed_args_and_vars(self) -> None:
        result = cmd("cp", var("SRC"), "/dest/path with spaces")
        assert result == "cp $SRC '/dest/path with spaces'"

    def test_find_exec_pattern(self) -> None:
        result = cmd("find", "/tmp", "-exec", "ln", "-sf", "{}", "/dest/", ";")
        assert "{}" in result


class TestVar:
    def test_valid_name(self) -> None:
        v = var("SRPM")
        assert isinstance(v, _ShellVar)
        assert v.name == "SRPM"

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid shell variable name"):
            var("bad-name")

    def test_invalid_name_with_spaces(self) -> None:
        with pytest.raises(ValueError, match="Invalid shell variable name"):
            var("bad name")

    def test_invalid_name_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid shell variable name"):
            var("x; rm -rf /")


class TestPipe:
    def test_simple_pipe(self) -> None:
        result = pipe(cmd("find", "/tmp"), cmd("head", "-1"))
        assert result == "find /tmp | head -1"

    def test_no_commands_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one command"):
            pipe()

    def test_single_command(self) -> None:
        result = pipe(cmd("ls"))
        assert result == "ls"


class TestAssign:
    def test_simple_assignment(self) -> None:
        result = assign("SRPM", pipe(cmd("find", "/tmp", "-name", "*.src.rpm"), cmd("head", "-1")))
        assert result == "SRPM=$(find /tmp -name '*.src.rpm' | head -1)"

    def test_invalid_varname(self) -> None:
        with pytest.raises(ValueError, match="Invalid variable name"):
            assign("bad-var", "echo hi")

    def test_injection_in_varname(self) -> None:
        with pytest.raises(ValueError, match="Invalid variable name"):
            assign("x$(rm)", "echo hi")


class TestWriteFile:
    def test_simple_content(self) -> None:
        result = write_file("hello", "/tmp/test.txt")
        assert result == "printf 'hello' > /tmp/test.txt"

    def test_newlines_escaped(self) -> None:
        result = write_file("line1\nline2", "/tmp/test.txt")
        assert "\\n" in result

    def test_backslashes_escaped(self) -> None:
        result = write_file("path\\to\\file", "/tmp/test.txt")
        assert "\\\\" in result

    def test_dest_quoted(self) -> None:
        result = write_file("content", "/tmp/my file.txt")
        assert "'/tmp/my file.txt'" in result

    def test_dest_injection_prevented(self) -> None:
        result = write_file("content", "/tmp/$(whoami).txt")
        assert "'/tmp/$(whoami).txt'" in result

    def test_percent_escaped(self) -> None:
        result = write_file("100%", "/tmp/test.txt")
        assert "%%" in result


class TestHeredoc:
    def test_simple_heredoc(self) -> None:
        result = heredoc("/tmp/test.conf", "[repo]\nname=test")
        assert result == "cat > /tmp/test.conf <<'EOF'\n[repo]\nname=test\nEOF"

    def test_custom_delimiter(self) -> None:
        result = heredoc("/tmp/test.conf", "content", "MYEOF")
        assert "<<'MYEOF'" in result
        assert result.endswith("\nMYEOF")

    def test_dest_quoted(self) -> None:
        result = heredoc("/tmp/my file.conf", "content")
        assert "'/tmp/my file.conf'" in result

    def test_no_variable_expansion(self) -> None:
        result = heredoc("/tmp/test", "$HOME is here")
        assert "<<'EOF'" in result


class TestInjectionAttempts:
    """Comprehensive injection attack scenarios."""

    def test_chroot_injection_in_path(self) -> None:
        malicious = "fedora-39-x86_64; rm -rf /"
        result = cmd("createrepo_c", f"/results/{malicious}")
        assert "'" in result

    def test_command_substitution_in_arg(self) -> None:
        result = cmd("echo", "$(cat /etc/passwd)")
        assert result == "echo '$(cat /etc/passwd)'"

    def test_newline_injection(self) -> None:
        result = cmd("echo", "safe\nrm -rf /")
        assert "'" in result

    def test_glob_expansion_prevented(self) -> None:
        result = cmd("ls", "*.txt")
        assert result == "ls '*.txt'"

    def test_environment_variable_expansion_prevented(self) -> None:
        result = cmd("echo", "${PATH}")
        assert result == "echo '${PATH}'"

    def test_write_file_content_injection(self) -> None:
        malicious_content = "safe' > /dev/null; rm -rf / #"
        result = write_file(malicious_content, "/tmp/test")
        assert result.startswith("printf '")
        assert "> /tmp/test" in result
