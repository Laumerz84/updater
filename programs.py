"""Programs: the recommended GitHub programs (catalog.json), which of them this PC has, which GitHub
clones have a card in the App Launcher, and installing what is missing.

Installing a program: clone it next to the Updater's folder, set it up (its own .venv, or pip into this
Python), add its Start menu shortcut if it has one, then add its App Launcher card using the launcher's
own add_companions.py. An existing card is never replaced: one the user edited stays as it is.
Each step is safe to repeat. Standard library only.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import updater as u

CATALOG = u.HERE / "catalog.json"
PROGRAMS_MENU = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
CLONE_TIMEOUT = 10 * 60
PIP_TIMEOUT = 20 * 60

# Run in the App Launcher's folder: add_companions makes the card for argv[2] with function argv[1].
ADD_CARD = """
import sys
from pathlib import Path
import add_companions
make = getattr(add_companions, sys.argv[1], None)
if make is None:
    sys.exit(3)
print("; ".join(add_companions.add_entries(Path("apps.json"), [make(Path(sys.argv[2]))])))
"""


@dataclass
class Program:
    name: str
    repo: str
    folder: str
    about: str = ""
    setup: str = ""
    doctor: str = ""
    launcher: str = ""
    role: str = ""
    start_menu: dict = field(default_factory=dict)
    path: Optional[Path] = None     # where this PC's clone is; None = not installed
    card: bool = False              # the App Launcher has a card for it

    @property
    def status(self) -> str:
        if self.path is None:
            return "not installed"
        if self.launcher and not self.card:
            return "installed, no App Launcher card"
        return "installed"


@dataclass
class Clone:
    """A GitHub clone that is not in the catalog."""
    name: str
    path: Path
    card: bool


def same_repo(a: str, b: str) -> bool:
    def norm(url: str) -> str:
        url = url.strip().lower().rstrip("/").replace("git@github.com:", "https://github.com/")
        return url[:-4] if url.endswith(".git") else url
    return norm(a) == norm(b)


def load_catalog() -> list[Program]:
    data = u.load_json(CATALOG)
    known = Program.__dataclass_fields__.keys() - {"path", "card"}
    return [Program(**{k: v for k, v in raw.items() if k in known}) for raw in data.get("programs", [])]


def launcher_cards(launcher: Optional[Path]) -> list[dict]:
    if launcher is None:
        return []
    try:
        data = json.loads((launcher / "apps.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [a for a in data.get("apps", []) if isinstance(a, dict)]


def has_card(folder: Path, cards: list[dict]) -> bool:
    """True when a card runs something in *folder* (its working folder, command or arguments)."""
    root = os.path.normcase(str(folder.resolve()))
    for card in cards:
        args = card.get("args", [])
        texts = [card.get("working_dir", ""), card.get("cwd", ""), card.get("command", "")]
        texts += args if isinstance(args, list) else [args]
        for text in texts:
            text = os.path.normcase(os.path.expandvars(str(text)).strip('"'))
            if text == root or text.startswith(root + os.sep):
                return True
    return False


def survey(repos: Optional[list] = None) -> tuple[list[Program], list[Clone]]:
    """The catalog with this PC's state filled in, and the other GitHub clones with theirs.
    *repos*: the Updater's discovered clones (anything with .folder and .url); found afresh if omitted."""
    repos = u.discover() if repos is None else repos
    programs = load_catalog()
    for program in programs:
        program.path = next((r.folder for r in repos if same_repo(r.url, program.repo)), None)
    cards = launcher_cards(launcher_of(programs))
    for program in programs:
        program.card = program.path is not None and has_card(program.path, cards)
    others = [Clone(r.name, r.folder, has_card(r.folder, cards)) for r in repos
              if not any(same_repo(r.url, p.repo) for p in programs)]
    return programs, others


# --------------------------------------------------------------------------- installing
def run(cmd: list[str], folder: Path, timeout: int) -> tuple[bool, str]:
    """Run *cmd*, log it, and return (ok, the last line of output)."""
    u.log(f"run    {folder.name}: {subprocess.list2cmdline(cmd)}")
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1", PYTHONIOENCODING="utf-8")
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    try:
        r = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL, creationflags=u.NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        u.log(f"       failed: {exc}")
        return False, str(exc)
    output = (r.stdout + r.stderr).strip()
    if output:
        u.log("       " + "\n       ".join(output.splitlines()[-40:]))
    u.log(f"       exit code {r.returncode}")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return r.returncode == 0, lines[-1] if lines else f"exit code {r.returncode}"


def clone(program: Program) -> tuple[bool, str]:
    target = u.ROOT / program.folder
    if target.exists() and any(target.iterdir()):
        return False, f"{target} already exists and is not a clone of {program.repo}"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    u.log(f"clone  {program.repo} -> {target}")
    try:
        r = subprocess.run(["git", "clone", "--quiet", program.repo, str(target)], cwd=u.ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=CLONE_TIMEOUT, env=env,
                           stdin=subprocess.DEVNULL, creationflags=u.NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"git clone failed: {exc}"
    if r.returncode:
        u.log(f"       {r.stderr.strip()}")
        detail = u.first_line(r.stderr)
        if "not found" in detail.lower() or "authentication" in detail.lower() or "could not read" in detail.lower():
            detail = "no access (the repository is private or does not exist for this GitHub account)"
        return False, "could not clone: " + detail
    program.path = target
    return True, "cloned"


def python_of(program: Program) -> str:
    venv = program.path / ".venv" / "Scripts" / "python.exe"
    return str(venv) if program.setup == "venv" else u.console_python()


def set_up(program: Program) -> tuple[bool, str]:
    """Libraries and the doctor check. Repeatable: an existing .venv is updated, not remade."""
    folder, done = program.path, []
    if program.setup == "venv" and not (folder / ".venv" / "Scripts" / "python.exe").is_file():
        ok, last = run([u.console_python(), "-m", "venv", str(folder / ".venv")], folder, 5 * 60)
        if not ok:
            return False, "could not make .venv: " + last
        done.append(".venv made")
    if program.setup in ("venv", "pip") and (folder / "requirements.txt").is_file():
        ok, last = run([python_of(program), "-m", "pip", "install", "-r", "requirements.txt"], folder, PIP_TIMEOUT)
        if not ok:
            return False, "pip install failed: " + last
        done.append("libraries installed")
    if program.doctor and (folder / program.doctor).is_file():
        ok, last = run([python_of(program), program.doctor], folder, 5 * 60)
        if not ok:
            return False, f"{program.doctor} reported a problem: {last}"
        done.append("check passed")
    return True, ", ".join(done)


def start_menu(program: Program) -> tuple[bool, str]:
    spec = program.start_menu
    if not spec:
        return True, ""
    lnk = PROGRAMS_MENU / f"{spec['name']}.lnk"
    folder = program.path
    icon = str(folder / spec["icon"]) + ",0" if spec.get("icon") else ""
    try:
        u.write_shortcut(lnk, u.windowless_python(), f'"{folder / spec["script"]}"', folder, program.about, icon)
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, f"could not make the Start menu shortcut: {exc}"
    if spec.get("stamp"):
        run([u.console_python(), *spec["stamp"], str(lnk)], folder, 60)
    return True, f"Start menu shortcut '{spec['name']}'"


def add_card(program: Program, launcher: Optional[Path]) -> tuple[bool, str]:
    if not program.launcher or program.card:
        return True, ""
    if launcher is None:
        return False, "no App Launcher card: the App Launcher is not installed"
    ok, last = run([u.console_python(), "-c", ADD_CARD, program.launcher, str(program.path)], launcher, 60)
    if not ok:
        if last == "exit code 3":
            return False, "no App Launcher card: this App Launcher is too old, update it first"
        return False, "could not add the App Launcher card: " + last
    program.card = True
    return True, "App Launcher card added"


def install(program: Program, launcher: Optional[Path], setup_existing: bool = False) -> tuple[bool, str]:
    """Clone if missing, then set up, Start menu shortcut and App Launcher card. *setup_existing*: also
    run the setup step for a program that was already installed (an existing .venv is kept)."""
    steps, fresh = [], program.path is None
    if fresh:
        ok, message = clone(program)
        if not ok:
            return False, message
        steps.append(message)
    if fresh or setup_existing:
        ok, message = set_up(program)
        steps.append(message)
        if not ok:
            return False, "; ".join(s for s in steps if s)
    missing_shortcut = program.start_menu and not (PROGRAMS_MENU / f"{program.start_menu['name']}.lnk").exists()
    for step in (lambda: start_menu(program) if fresh or missing_shortcut else (True, ""),
                 lambda: add_card(program, launcher)):
        ok, message = step()
        steps.append(message)
        if not ok:
            return False, "; ".join(s for s in steps if s)
    return True, "; ".join(s for s in steps if s) or "nothing to do"


def launcher_of(programs: list[Program]) -> Optional[Path]:
    return next((p.path for p in programs if p.role == "launcher"), None)
