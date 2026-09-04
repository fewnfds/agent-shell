from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from agent_shell.settings import (
    Settings,
    SettingsError,
    bearer_token_is_valid,
    get_settings,
    load_settings,
)
from agent_shell.storage.permissions import secure_file
from agent_shell.storage.environment import (
    InstanceEnvironmentStore,
    SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
)


_MISSING_LOCAL_MANAGEMENT_TOKEN_ACTION = "Configure the management Bearer token."


def _prepare_windows_dependencies(*, data_root: Path, runtime_root: Path) -> None:
    from agent_shell.python_packages.dependencies import prepare_windows_dependencies

    prepare_windows_dependencies(data_root=data_root, runtime_root=runtime_root)


def _activate_package_site(runtime_root: Path) -> None:
    from agent_shell.python_packages.dependencies import activate_package_site

    activate_package_site(runtime_root)


def _create_application(*, settings: Settings, serve_frontend: bool) -> object:
    from agent_shell.langgraph_dev import configure_runtime

    return configure_runtime(settings, serve_frontend=serve_frontend)


def _langgraph_config_path() -> Path:
    from agent_shell import langgraph_dev

    return Path(langgraph_dev.__file__).with_name("langgraph.json").resolve()


def _run_server(*, settings: Settings, config_path: Path) -> None:
    from langgraph_cli.cli import cli

    arguments = [
        "dev",
        "--config",
        str(config_path),
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--no-reload",
        "--no-browser",
        "--allow-blocking",
        "--n-jobs-per-worker",
        str(settings.n_jobs_per_worker),
    ]
    if settings.debug_port is not None:
        arguments.extend(("--debug-port", str(settings.debug_port)))
    cli.main(
        args=arguments,
        prog_name="langgraph",
        standalone_mode=False,
    )


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "port must be an integer between 1 and 65535"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _read_confirmed_credential(
    read_password: Callable[[str], str],
    *,
    prompt: str,
    confirmation_prompt: str,
    invalid_message: str,
    output_stream: TextIO | None = None,
) -> str | None:
    while True:
        try:
            value = read_password(prompt)
            confirmation = read_password(confirmation_prompt)
        except (EOFError, KeyboardInterrupt):
            return None
        if not bearer_token_is_valid(value):
            print(invalid_message, file=output_stream)
            continue
        if value != confirmation:
            print("两次输入不一致，请重新输入。", file=output_stream)
            continue
        return value


def listen_address_is_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_EXCLUSIVEADDRUSE,
                    1,
                )
            listener.bind((host, port))
    except OSError:
        return False
    return True


def _write_management_password(
    password: str,
    *,
    env_path: Path,
) -> None:
    InstanceEnvironmentStore(env_path).patch(
        SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
        set_values={"AGENT_SHELL_MANAGEMENT_TOKEN": password},
    )
    permission = secure_file(env_path)
    if not permission.enforced:
        raise OSError("The management settings file permissions are not private.")


def initialize_local_settings(
    *,
    application_home: Path | None = None,
    data_root: Path | None = None,
    env_path: Path | None = None,
    password_reader: Callable[[str], str] | None = None,
    output_stream: TextIO | None = None,
) -> int:
    home = (application_home or Path.cwd()).resolve()
    root = data_root or (home / "data")
    root = root.resolve() if root.is_absolute() else (home / root).resolve()
    env_path = env_path or root / "config" / "agent-shell.env"
    output_stream = output_stream or sys.stdout
    missing_management_error: SettingsError | None = None
    try:
        get_settings(
            application_home=home,
            data_root=root,
        )
    except SettingsError as exc:
        if not (
            exc.keys == ("AGENT_SHELL_MANAGEMENT_TOKEN",)
            and exc.action == _MISSING_LOCAL_MANAGEMENT_TOKEN_ACTION
        ):
            print(f"Startup configuration error: {exc}", file=sys.stderr)
            return 2
        missing_management_error = exc
    else:
        return 0

    try:
        current_settings = load_settings(
            application_home=home,
            data_root=root,
        )
    except SettingsError as exc:
        print(f"Startup configuration error: {exc}", file=sys.stderr)
        return 2
    if current_settings.deployment_mode != "authenticated_local":
        print(
            f"Startup configuration error: {missing_management_error}",
            file=sys.stderr,
        )
        return 2
    read_password = password_reader or getpass.getpass

    print("首次启动：请设置管理网站密码。", file=output_stream)
    print(
        "这个密码只用于打开管理网站，不会改变 /v1 OpenAI API 使用的 Key。",
        file=output_stream,
    )
    print("请输入不含空格的可打印 ASCII 字符。", file=output_stream)
    password = _read_confirmed_credential(
        read_password,
        prompt="管理密码（输入时不会显示）：",
        confirmation_prompt="请再输入一次：",
        invalid_message="密码格式不对，请输入不含空格的可打印 ASCII 字符。",
        output_stream=output_stream,
    )
    if password is None:
        print("\n已取消，没有创建或修改配置文件。", file=sys.stderr)
        return 1

    try:
        _write_management_password(
            password,
            env_path=env_path,
        )
    except OSError:
        print("无法保存配置文件，请检查 data 目录是否可写。", file=sys.stderr)
        return 1

    print(
        "管理密码已保存。以后双击 start_server.bat 会直接启动。",
        file=output_stream,
    )
    print(file=output_stream)
    return 0


def prepare_launch_settings(
    *,
    application_home: Path | None = None,
    data_root: Path | None = None,
) -> int:
    """Prepare local settings and print the effective launch tuple in one process."""

    result = initialize_local_settings(
        application_home=application_home,
        data_root=data_root,
        output_stream=sys.stderr,
    )
    if result != 0:
        return result
    return main(
        application_home=application_home,
        data_root=data_root,
        print_launch_settings=True,
        serve_frontend=False,
    )


def main(
    *,
    application_home: Path | None = None,
    data_root: Path | None = None,
    print_launch_settings: bool = False,
    probe_listen_settings: bool = False,
    prepare_dependencies: bool = False,
    port_override: int | None = None,
    serve_frontend: bool = True,
) -> int:
    home = (application_home or Path.cwd()).resolve()
    try:
        settings = get_settings(
            application_home=home,
            data_root=data_root,
        )
    except SettingsError as exc:
        print(f"Startup configuration error: {exc}", file=sys.stderr)
        return 2
    if port_override is not None:
        settings.port = port_override

    if probe_listen_settings:
        if listen_address_is_available(settings.host, settings.port):
            return 0
        print(
            f"Configured listen address {settings.host}:{settings.port} "
            "cannot be bound. The port may be occupied or reserved by the OS.",
            file=sys.stderr,
        )
        return 3

    if print_launch_settings:
        display_host = f"[{settings.host}]" if ":" in settings.host else settings.host
        print(
            f"{settings.host}|{settings.port}|"
            f"http://{display_host}:{settings.port}/admin"
        )
        return 0

    if prepare_dependencies:
        print("Python dependency preparation started...")
        try:
            _prepare_windows_dependencies(
                data_root=settings.data_root,
                runtime_root=settings.resolved_runtime_dir(),
            )
        except Exception as exc:
            print(
                f"Python package dependency preparation failed: {exc}",
                file=sys.stderr,
            )
            return 1
        print("Python dependency preparation finished.")
        display_host = f"[{settings.host}]" if ":" in settings.host else settings.host
        print("Starting Agent Shell...")
        print(f"  http://{display_host}:{settings.port}/admin")
        print()

    if settings.deployment_mode == "authenticated_remote":
        print(
            "WARNING: Remote HTTP backend enabled. Publish it only behind a TLS "
            "reverse proxy and firewall.",
            file=sys.stderr,
        )

    _activate_package_site(settings.resolved_runtime_dir())
    _create_application(settings=settings, serve_frontend=serve_frontend)
    config_path = _langgraph_config_path()
    langgraph_data_dir = settings.resolved_langgraph_dev_dir()
    previous_cwd = Path.cwd()
    try:
        os.chdir(langgraph_data_dir)
        _run_server(settings=settings, config_path=config_path)
    finally:
        os.chdir(previous_cwd)
    return 0


def run_cli(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    parser = argparse.ArgumentParser(prog="python -m agent_shell")
    parser.add_argument(
        "--home",
        required=True,
        type=Path,
        help="Application home containing the program runtime.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Persistent data root. Relative paths are resolved from application home.",
    )
    parser.add_argument("--port", type=_parse_port, metavar="PORT")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--initialize-local-settings", action="store_true")
    action.add_argument(
        "--prepare-launch-settings",
        action="store_true",
        help="Prepare local settings and print host, port, and management URL.",
    )
    action.add_argument("--print-launch-settings", action="store_true")
    action.add_argument("--probe-listen-settings", action="store_true")
    parser.add_argument(
        "--prepare-dependencies",
        action="store_true",
        help="Prepare configuration-owned Python package dependencies before serving.",
    )
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="Run only the API backend for the Vite development proxy.",
    )
    try:
        parsed = parser.parse_args(arguments)
    except SystemExit as exc:
        return int(exc.code)

    home = parsed.home.resolve()
    data_root = parsed.data_dir or (home / "data")
    data_root = (
        data_root.resolve()
        if data_root.is_absolute()
        else (home / data_root).resolve()
    )
    if parsed.initialize_local_settings:
        return initialize_local_settings(
            application_home=home,
            data_root=data_root,
        )
    if parsed.prepare_launch_settings:
        return prepare_launch_settings(
            application_home=home,
            data_root=data_root,
        )
    return main(
        application_home=home,
        data_root=data_root,
        print_launch_settings=parsed.print_launch_settings,
        probe_listen_settings=parsed.probe_listen_settings,
        prepare_dependencies=parsed.prepare_dependencies,
        port_override=parsed.port,
        serve_frontend=not parsed.no_frontend,
    )


if __name__ == "__main__":
    raise SystemExit(run_cli())
