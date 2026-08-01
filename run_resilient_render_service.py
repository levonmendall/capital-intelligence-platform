"""Run the Render supervisor with resilient operator and Streamlit entrypoints."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

import run_render_service as service

_ORIGINAL_MANAGED_PROCESSES = service.managed_processes


def resilient_managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
):
    processes = _ORIGINAL_MANAGED_PROCESSES(
        port=port,
        python_executable=python_executable,
    )
    result = []
    for process in processes:
        if process.name == "cio-paper-operator":
            python = process.command[0]
            result.append(
                replace(
                    process,
                    command=(python, "run_resilient_paper_operator.py", "--loop"),
                )
            )
        elif process.name == "streamlit":
            result.append(
                replace(
                    process,
                    command=tuple(
                        "render_app_resilient.py" if part == "render_app.py" else part
                        for part in process.command
                    ),
                )
            )
        else:
            result.append(process)
    return tuple(result)


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("run_resilient_render_service.py does not accept arguments")
    service.managed_processes = resilient_managed_processes
    return service.main()


if __name__ == "__main__":
    raise SystemExit(main())
