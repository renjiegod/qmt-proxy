# QMT Proxy Agent Notes

## Core Workflow

- Prefer `make` targets and `scripts/make.ps1` over ad-hoc shell commands for backend and web workflows.
- When adding or changing developer commands, keep Windows PowerShell as the primary execution environment.
- After changing `Makefile`, `scripts/make.ps1`, or the web toolchain, verify the real command path instead of relying only on unit tests.

## Windows Shared-Folder Constraints

- This repo is often used from a Windows VM against a shared-folder path such as `Z:\code\qmt-proxy`.
- Do not assume `npm run` from a UNC/shared-folder path is reliable. Prefer the PowerShell wrapper and direct Node CLI entrypoints when needed.
- Treat `web/node_modules/.bin` as fragile on shared folders. Prefer installs that avoid bin-link dependence when possible.
- If Windows reports `EINVAL`, `lstat`, `stat`, or access-denied errors inside `web/node_modules/.bin`, treat it as corrupted install state before changing app code.
- If Windows cannot delete `web/node_modules`, remove it from the host filesystem first, then reinstall from Windows.

## Frontend Toolchain Policy

- Keep the default web toolchain on versions that are known to work on Windows ARM64 in this repo.
- Do not upgrade `vite`, `vitest`, or `@vitejs/plugin-react` across major versions without verifying Windows ARM64 compatibility first.
- In particular, avoid toolchain versions that force `rolldown` native bindings unless they have been explicitly validated in this environment.
- If intentionally changing the supported toolchain major version, update `tests/unit/test_web_toolchain_versions.py` in the same change.

## Frontend Dependency Recovery

- Use `make ui-install` for frontend installs instead of running custom install commands.
- If frontend startup fails with messages like `Cannot find native binding`, `ERR_DLOPEN_FAILED`, or `not a valid Win32 application`, check dependency/runtime compatibility before changing application code.
- If dependency repair is needed, prefer reinstalling `web/node_modules` cleanly rather than patching individual generated files.

## Required Verification

- After changing `Makefile` or `scripts/make.ps1`, run:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File "tests/unit/test_make_start_args.ps1"`
  - `powershell -NoProfile -ExecutionPolicy Bypass -File "tests/unit/test_make_helpers.ps1"`
- After changing frontend toolchain versions, run:
  - `python -m pytest tests/unit/test_web_toolchain_versions.py`
  - `make ui-install`
- After changing the combined dev workflow, run `make dev` and confirm both frontend and backend start successfully.

