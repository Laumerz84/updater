"""Set up the GitHub Updater and every recommended program, start to finish, with no questions.

Run it from the Updater's folder, which must be a clone sitting in the folder that holds (or will hold)
your projects: the recommended programs are cloned next to it.

    install.py          install everything that is missing (double-click, or let Claude run it)
    install.py --list   show what is installed and what is not, change nothing

For each program in catalog.json, in order: clone it if missing, install its libraries, make its Start
menu shortcut, add its App Launcher card. Then turn on the Updater's daily check at login. A program
that cannot be cloned (no access to a private repository) is skipped and reported. Safe to run again.

Exit code 0 when everything that could be installed is; 1 when something needs a person.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

import programs
import updater as u

MIN_PYTHON = (3, 11)


def preflight() -> list[str]:
    """Problems that stop the install before it changes anything."""
    problems = []
    if sys.platform != "win32":
        problems.append("This is for Windows.")
    if sys.version_info < MIN_PYTHON:
        problems.append(f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is needed (this is "
                        f"{sys.version.split()[0]}). Install it from python.org, then run install.py again.")
    if not shutil.which("git"):
        problems.append("Git is not installed (or not on PATH). Install Git for Windows, then run install.py again.")
    elif not (u.HERE / ".git").exists():
        problems.append(f"{u.HERE} is not a git clone. Clone https://github.com/Laumerz84/updater.git "
                        "instead of downloading it, then run install.py in the clone.")
    return problems


def show(catalog: list[programs.Program], others: list[programs.Clone]) -> None:
    width = max(len(p.name) for p in catalog) + 2
    for p in catalog:
        print(f"  {p.name:<{width}}{p.status}" + (f"  ({p.path})" if p.path else ""))
    if others:
        print("\n  Other GitHub clones:")
        for c in others:
            print(f"  {c.name:<{width}}{'has an App Launcher card' if c.card else 'no App Launcher card'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the GitHub Updater and the recommended programs.")
    parser.add_argument("--list", action="store_true", help="show what is installed, change nothing")
    args = parser.parse_args()

    problems = preflight()
    if problems:
        print("Install cannot start:\n" + "\n".join("  - " + p for p in problems))
        return 1
    print(f"Programs folder: {u.ROOT}\n")
    catalog, others = programs.survey()
    if args.list:
        show(catalog, others)
        return 0

    failed, skipped = [], []
    for program in catalog:
        action = "Installing" if program.path is None else "Checking"
        print(f"{action} {program.name}...", flush=True)
        launcher = programs.launcher_of(catalog)
        try:
            ok, message = programs.install(program, launcher, setup_existing=True)
        except Exception as exc:  # one program must not stop the rest
            ok, message = False, f"{type(exc).__name__}: {exc}"
        u.log(f"setup  {program.name}: {'OK' if ok else 'PROBLEM'} - {message}")
        print(f"  {'ok' if ok else 'PROBLEM'}: {message}")
        if not ok:
            (skipped if "no access" in message else failed).append(f"{program.name}: {message}")

    print("Turning on the daily update check at login...")
    try:
        if not u.STARTUP_LNK.exists():
            u.set_startup(True)
        print(f"  ok: {u.STARTUP_LNK}")
    except (OSError, subprocess.CalledProcessError) as exc:
        failed.append(f"daily check: could not make the Startup shortcut ({exc})")
        print(f"  PROBLEM: {exc}")

    print("\nResult:")
    show(*programs.survey())
    for line in skipped:
        print(f"\nSkipped - {line}")
    for line in failed:
        print(f"\nNeeds attention - {line}")
    print(f"\nLog: {u.LOG}")
    if not failed:
        print("Install finished. Open the App Launcher from the Start menu.")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    if sys.stdin and sys.stdin.isatty():    # double-clicked: keep the window open. Run by a tool: don't wait.
        try:
            input("\nPress Enter to close")
        except (EOFError, RuntimeError):
            pass
    sys.exit(code)
