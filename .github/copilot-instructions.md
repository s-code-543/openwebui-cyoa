# CYOA Game Server — Copilot Instructions (must follow)

## Runtime truth
- The server runs in Docker via docker-compose. Do not propose running the Django server on the host as the primary path.
- Host Python is for: tests, linters, one-off scripts, Django management commands when explicitly requested.
- Whisper.cpp runs natively on macOS (LaunchAgent) and is accessed from containers via host.docker.internal.
- Ollama runs natively on macOS and is accessed from containers via host.docker.internal.

## Python environment (host)
- Use a dedicated CONDA ENV for this repo. Never install into:
  - system Python (/usr/bin/python3)
  - conda base
- Do not create conda envs with `conda create -p ./venv ...`.
- The env name for this repo is: `cyoa-py312` (Python 3.12).
- When giving host commands, assume the user will run:
  - `conda activate cyoa-py312`
  before running python/pip/pytest/manage.py.

## Dependency changes
- If a dependency is required for runtime, update the container build path (requirements.txt/pyproject + Dockerfile/build steps) and show docker rebuild commands.
- If a dependency is only for dev tooling/tests, it may be installed into `cyoa-py312`, but still prefer pinning it in requirements/dev requirements if the project expects reproducibility.

## Commands and output expectations
- Provide copy/paste-ready commands.
- Be explicit about which context the command runs in:
  - HOST (conda env) vs DOCKER (compose service container).
- For Docker networking: containers reach host services at `http://host.docker.internal:<port>`.
