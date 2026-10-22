import sys
import textwrap

import pytest

from offer_engine import cli


def test_help_lists_check_env(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "check-env" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 0
    assert "check-env" in capsys.readouterr().out


def test_new_command_module_is_discovered_without_editing_cli(tmp_path, monkeypatch, capsys):
    package = tmp_path / "fake_commands"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "hello.py").write_text(
        textwrap.dedent(
            """
            def register(subparsers):
                parser = subparsers.add_parser("hello", help="say hello")
                parser.set_defaults(func=run)

            def run(args):
                print("hello from a discovered command")
                return 3
            """
        )
    )
    (package / "_private.py").write_text("raise RuntimeError('underscore modules are not commands')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "fake_commands", raising=False)
    import fake_commands

    monkeypatch.setattr(cli, "commands", fake_commands)

    assert cli.main(["hello"]) == 3
    assert "hello from a discovered command" in capsys.readouterr().out
