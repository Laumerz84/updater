"""Updater: keeps the GitHub clones on this computer up to date.

Every folder in the Python folder that is a git clone of a GitHub repo, plus any folder listed
under "extra" in repos.local.json, is checked once a day: fetch, then compare the checked-out branch
with its copy on GitHub. When GitHub has commits this computer does not, a window lists them and
offers to install them.

Installing is a fast-forward and nothing else. A clone with uncommitted changes to tracked files,
or with commits that were never pushed, is shown as blocked and left alone. After the pull:
requirements.txt changed -> pip install -r requirements.txt; the project has a locally built
dist\\*.exe and a build recipe (packaging\\build_exe.py or a single *.spec) -> rebuild it, if
the box is ticked.

    updater.py                  check now and show the window (double-click)
    updater.py --window         the same with no console (the app launcher's button)
    updater.py --background     what the Startup shortcut runs: check once a day, open the
                                window only when something is out of date
    updater.py --check          print the report, change nothing
    updater.py --startup on     add the Startup-folder shortcut and start the daily checker
    updater.py --startup off    remove it

State and the log live in %LOCALAPPDATA%\\Updater, out of OneDrive.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # the Python folder: every clone in it is checked
CONFIG = HERE / "repos.json"
LOCAL_CONFIG = HERE / "repos.local.json"   # this PC's own additions; not in git
DATA = Path(os.environ.get("LOCALAPPDATA") or HERE) / "Updater"
STATE = DATA / "state.json"
LOG = DATA / "updater.log"
LOCK = DATA / "background.lock"
STARTUP_LNK = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
               / "Startup" / "GitHub Updater.lnk")

POLL_SECONDS = 30 * 60      # the background checker wakes this often to see if a new day has started
FETCH_TIMEOUT = 60
BUILD_TIMEOUT = 30 * 60
NEW_TITLES = 5              # commit titles shown per repo
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- helpers
def log(message: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "no details")


def git(folder: Path, *args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run git in *folder*. Never prompts: a missing credential is a failure, not a dialog."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    r = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env,
                       creationflags=NO_WINDOW)
    return r.returncode, r.stdout.rstrip(), r.stderr.strip()


def console_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def windowless_python() -> str:
    exe = Path(sys.executable).with_name("pythonw.exe")
    return str(exe) if exe.is_file() else sys.executable


def python_for(folder: Path) -> str:
    """The project's own .venv if it has one, else this Python."""
    venv = folder / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.is_file() else console_python()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log(f"could not read {path}: {exc}")
        return {}


def save_state(**values) -> None:
    state = load_json(STATE)
    state.update(values)
    DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- checking
@dataclass
class Repo:
    folder: Path
    name: str
    url: str = ""
    branch: str = ""
    upstream: str = ""
    behind: int = 0                 # commits on GitHub this computer does not have
    ahead: int = 0                  # commits here that were never pushed
    dirty: list[str] = field(default_factory=list)   # tracked files with uncommitted changes
    titles: list[str] = field(default_factory=list)  # newest first
    deps_changed: bool = False
    build: Optional[list[str]] = None                # command that rebuilds dist\*.exe
    problem: str = ""               # why it could not be checked

    @property
    def status(self) -> str:
        if self.problem:
            return "error"
        if not self.behind:
            return "current"
        return "blocked" if (self.dirty or self.ahead) else "update"

    @property
    def blocked_reason(self) -> str:
        parts = []
        if self.dirty:
            shown = ", ".join(self.dirty[:3]) + (" ..." if len(self.dirty) > 3 else "")
            parts.append(f"{len(self.dirty)} uncommitted change(s) ({shown})")
        if self.ahead:
            parts.append(f"{self.ahead} unpushed commit(s)")
        return "; ".join(parts)

    def summary(self) -> str:
        if self.status == "error":
            return f"not checked: {self.problem}"
        if self.status == "current":
            return "up to date" + (f" ({self.ahead} unpushed commit(s))" if self.ahead else "")
        text = f"{self.behind} new commit(s) on {self.upstream}"
        if self.status == "blocked":
            text += f" - BLOCKED: {self.blocked_reason}"
        return text


def discover() -> list[Repo]:
    """Every GitHub clone in the Python folder, plus "extra", minus "ignore" (repos.json and repos.local.json)."""
    configs = [load_json(CONFIG), load_json(LOCAL_CONFIG)]
    ignore = {name.lower() for c in configs for name in c.get("ignore", [])}
    folders = sorted((p for p in ROOT.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    folders += [Path(os.path.expandvars(os.path.expanduser(p))) for c in configs for p in c.get("extra", [])]
    repos, seen = [], set()
    for folder in folders:
        if folder.name.lower() in ignore or not (folder / ".git").exists():
            continue
        key = os.path.normcase(str(folder.resolve()))
        if key in seen:
            continue
        seen.add(key)
        code, url, _ = git(folder, "remote", "get-url", "origin")
        if code == 0 and "github.com" in url.lower():
            repos.append(Repo(folder, folder.name, url))
    return repos


def check(repo: Repo) -> Repo:
    """A fresh look at *repo*: fetch, then compare its branch with GitHub's copy."""
    repo = Repo(repo.folder, repo.name, repo.url)
    try:
        code, _, err = git(repo.folder, "fetch", "--quiet", "--prune", "origin", timeout=FETCH_TIMEOUT)
        if code:
            repo.problem = "could not reach GitHub: " + first_line(err)
            return repo
        code, repo.branch, _ = git(repo.folder, "symbolic-ref", "--short", "-q", "HEAD")
        if code:
            repo.problem = "no branch checked out (detached HEAD)"
            return repo
        code, repo.upstream, _ = git(repo.folder, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if code:
            repo.problem = f"branch {repo.branch} is not tracking a branch on GitHub"
            return repo
        _, counts, _ = git(repo.folder, "rev-list", "--left-right", "--count", "HEAD...@{u}")
        repo.ahead, repo.behind = (int(n) for n in counts.split())
        _, status, _ = git(repo.folder, "status", "--porcelain", "--untracked-files=no")
        repo.dirty = [line[3:] for line in status.splitlines() if line.strip()]
        if repo.behind:
            _, titles, _ = git(repo.folder, "log", "--format=%s  (%an, %ar)", f"-n{NEW_TITLES}", "HEAD..@{u}")
            repo.titles = titles.splitlines()
            _, deps, _ = git(repo.folder, "diff", "--name-only", "HEAD", "@{u}", "--", "requirements.txt")
            repo.deps_changed = bool(deps.strip())
            repo.build = build_command(repo.folder)
    except subprocess.TimeoutExpired:
        repo.problem = "git timed out"
    except Exception as exc:  # one odd repo must not stop the others
        repo.problem = f"{type(exc).__name__}: {exc}"
    return repo


def check_all() -> list[Repo]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        repos = list(pool.map(check, discover()))
    for repo in repos:
        log(f"check  {repo.name}: {repo.summary()}")
    return repos


def build_command(folder: Path) -> Optional[list[str]]:
    """How to rebuild the project's dist\\*.exe, if it has one built here and a known recipe."""
    dist = folder / "dist"
    if not dist.is_dir() or not (any(dist.glob("*.exe")) or any(dist.glob("*/*.exe"))):
        return None
    py = python_for(folder)
    if (folder / "packaging" / "build_exe.py").is_file():
        return [py, str(Path("packaging") / "build_exe.py")]
    specs = sorted(folder.glob("*.spec"))
    if len(specs) == 1:
        return [py, "-m", "PyInstaller", "--noconfirm", specs[0].name]
    return None


# --------------------------------------------------------------------------- installing
def run_logged(cmd: list[str], folder: Path, timeout: int) -> bool:
    log(f"run    {folder.name}: {subprocess.list2cmdline(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"       failed: {exc}")
        return False
    output = (r.stdout + r.stderr).strip()
    if output:
        log("       " + "\n       ".join(output.splitlines()[-40:]))
    log(f"       exit code {r.returncode}")
    return r.returncode == 0


def install(repo: Repo, rebuild: bool) -> tuple[bool, str]:
    """Fast-forward *repo* to GitHub's copy, then install requirements / rebuild as needed."""
    repo = check(repo)              # the state may have changed since the window opened
    if repo.status != "update":
        return False, repo.summary()
    code, out, err = git(repo.folder, "merge", "--ff-only", "@{u}", timeout=120)
    if code:
        log(f"merge  {repo.name}: {err or out}")
        return False, "git could not fast-forward: " + first_line(err or out)
    log(f"merge  {repo.name}: fast-forwarded {repo.behind} commit(s)")
    done, ok = [f"installed {repo.behind} commit(s)"], True
    if repo.deps_changed:
        if run_logged([python_for(repo.folder), "-m", "pip", "install", "-r", "requirements.txt"],
                      repo.folder, 15 * 60):
            done.append("requirements installed")
        else:
            done.append("pip install FAILED (see log)")
            ok = False
    if rebuild and repo.build:
        if run_logged(repo.build, repo.folder, BUILD_TIMEOUT):
            done.append(".exe rebuilt")
        else:
            done.append(".exe rebuild FAILED (see log; close the program if it is running)")
            ok = False
    return ok, ", ".join(done)


# --------------------------------------------------------------------------- Startup shortcut
def write_shortcut(lnk: Path, target: str, args: str, folder: Path, description: str, icon: str = "") -> None:
    """Create or refresh a .lnk. Values go in through the environment so paths with spaces need no quoting."""
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:UPD_LNK); "
              "$s.TargetPath = $env:UPD_TARGET; $s.Arguments = $env:UPD_ARGS; "
              "$s.WorkingDirectory = $env:UPD_DIR; $s.Description = $env:UPD_DESC; "
              "if ($env:UPD_ICON) { $s.IconLocation = $env:UPD_ICON }; $s.Save()")
    env = dict(os.environ, UPD_LNK=str(lnk), UPD_TARGET=target, UPD_ARGS=args, UPD_DIR=str(folder),
               UPD_DESC=description, UPD_ICON=icon)
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                   check=True, capture_output=True, creationflags=NO_WINDOW)


def set_startup(on: bool) -> None:
    if not on:
        STARTUP_LNK.unlink(missing_ok=True)
        log("startup shortcut removed")
        return
    write_shortcut(STARTUP_LNK, windowless_python(), f'"{Path(__file__).resolve()}" --background', HERE,
                   "Checks the GitHub clones for updates once a day")
    log("startup shortcut created")
    # Start the checker now too, so the daily check runs without logging off first.
    # A second copy exits at once if one is already running.
    subprocess.Popen([windowless_python(), str(Path(__file__).resolve()), "--background"], cwd=HERE,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | NO_WINDOW,
                     close_fds=True)


# --------------------------------------------------------------------------- window
class Window:
    def __init__(self, repos: Optional[list[Repo]]):
        """repos=None opens the window at once and checks from inside it."""
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = tk.Tk()
        self.root.title("GitHub Updater")
        self.root.minsize(620, 200)
        self.events: queue.Queue = queue.Queue()
        self.busy = False

        self.header = ttk.Label(self.root, font=("Segoe UI", 10, "bold"))
        self.header.pack(anchor="w", padx=12, pady=(10, 4))
        self.body = ttk.Frame(self.root)
        self.body.pack(fill="both", expand=True, padx=12)
        self.programs = ttk.Frame(self.root)
        self.programs.pack(fill="x", padx=12, pady=(12, 0))
        self.program_btns: list = []

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=12, pady=10)
        self.startup = tk.BooleanVar(value=STARTUP_LNK.exists())
        ttk.Checkbutton(bottom, text="Check daily at login", variable=self.startup,
                        command=self.toggle_startup).pack(side="left")
        self.close_btn = ttk.Button(bottom, text="Close", command=self.root.destroy)
        self.close_btn.pack(side="right")
        ttk.Button(bottom, text="Open log", command=lambda: os.startfile(LOG) if LOG.exists() else None
                   ).pack(side="right", padx=4)
        self.check_btn = ttk.Button(bottom, text="Check now", command=self.recheck)
        self.check_btn.pack(side="right", padx=4)
        self.install_btn = ttk.Button(bottom, text="Install selected", command=self.install_selected)
        self.install_btn.pack(side="right", padx=4)
        self.progress = ttk.Label(self.root, foreground="#555555")
        self.progress.pack(anchor="w", padx=12, pady=(0, 8))

        self.render(repos or [])
        if repos is None:
            self.header.config(text="Checking GitHub for updates...")
            self.recheck()
        else:
            self.render_programs(survey_programs(repos))
        self.root.after(200, self.poll)

    def render(self, repos: list[Repo]) -> None:
        tk, ttk = self.tk, self.ttk
        for child in self.body.winfo_children():
            child.destroy()
        self.repos = repos
        self.picks: dict[str, tuple] = {}
        updates = [r for r in repos if r.status == "update"]
        blocked = [r for r in repos if r.status == "blocked"]
        errors = [r for r in repos if r.status == "error"]
        current = [r for r in repos if r.status == "current"]
        self.header.config(text=f"Checked {dt.datetime.now():%I:%M %p, %d %b %Y}:  "
                                f"{len(updates)} update(s) available, {len(blocked)} blocked, "
                                f"{len(current)} up to date")
        row = 0

        def titles(repo: Repo) -> None:
            nonlocal row
            more = repo.behind - len(repo.titles)
            text = "\n".join("    - " + t for t in repo.titles) + (f"\n    ... and {more} more" if more > 0 else "")
            ttk.Label(self.body, text=text, foreground="#555555", font=("Consolas", 9),
                      justify="left").grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1

        for repo in updates:
            pick = tk.BooleanVar(value=True)
            rebuild = tk.BooleanVar(value=repo.build is not None)
            extra = " - also installs requirements.txt" if repo.deps_changed else ""
            ttk.Checkbutton(self.body, variable=pick,
                            text=f"{repo.name}   [{repo.branch}]   {repo.behind} new commit(s){extra}"
                            ).grid(row=row, column=0, sticky="w", pady=(6, 0))
            if repo.build:
                ttk.Checkbutton(self.body, text="rebuild .exe afterwards", variable=rebuild
                                ).grid(row=row, column=1, sticky="e", pady=(6, 0))
            row += 1
            titles(repo)
            self.picks[repo.name] = (repo, pick, rebuild)

        for repo in blocked:
            ttk.Label(self.body, text=f"{repo.name}   [{repo.branch}]   {repo.behind} new commit(s) - blocked",
                      foreground="#9a3412").grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
            row += 1
            ttk.Label(self.body, text=f"    {repo.blocked_reason}. Commit and push, or discard, then Check now.",
                      foreground="#9a3412", wraplength=600, justify="left"
                      ).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            titles(repo)

        for repo in errors:
            ttk.Label(self.body, text=f"{repo.name}: {repo.problem}", foreground="#b91c1c", wraplength=600,
                      justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
            row += 1

        if current:
            ttk.Label(self.body, text="Up to date: " + ", ".join(r.name for r in current), wraplength=600,
                      justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.body.columnconfigure(0, weight=1)
        self.install_btn.state(["!disabled"] if updates else ["disabled"])

    def render_programs(self, listing) -> None:
        """The recommended programs (installed or not, App Launcher card or not) and the other clones."""
        ttk = self.ttk
        for child in self.programs.winfo_children():
            child.destroy()
        self.program_btns = []
        if listing is None:
            return
        catalog, others = listing
        ttk.Separator(self.programs).grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        ttk.Label(self.programs, text="Recommended programs", font=("Segoe UI", 10, "bold")
                  ).grid(row=1, column=0, columnspan=4, sticky="w")
        row = 2
        for program in catalog:
            ttk.Label(self.programs, text=program.name).grid(row=row, column=0, sticky="w", padx=(0, 10))
            ttk.Label(self.programs, text=program.about, foreground="#555555").grid(row=row, column=1, sticky="w")
            ttk.Label(self.programs, text=program.status,
                      foreground="#555555" if program.status == "installed" else "#9a3412"
                      ).grid(row=row, column=2, sticky="w", padx=10)
            action = "Install" if program.path is None else "Add card" if program.status != "installed" else ""
            if action:
                btn = ttk.Button(self.programs, text=action, command=lambda p=program: self.install_program(p))
                btn.grid(row=row, column=3, sticky="e", pady=1)
                self.program_btns.append(btn)
            row += 1
        if others:
            with_card = [c.name for c in others if c.card]
            without = [c.name for c in others if not c.card]
            parts = ([f"in the App Launcher: {', '.join(with_card)}"] if with_card else []) + \
                    ([f"not in the App Launcher: {', '.join(without)}"] if without else [])
            ttk.Label(self.programs, text="Your other GitHub clones - " + "; ".join(parts), wraplength=600,
                      justify="left", foreground="#555555").grid(row=row, column=0, columnspan=4, sticky="w",
                                                                 pady=(6, 0))
        self.programs.columnconfigure(1, weight=1)
        if self.busy:
            for btn in self.program_btns:
                btn.state(["disabled"])

    def install_program(self, chosen) -> None:
        self.set_busy(True, f"Installing {chosen.name}... (setting up its libraries can take a few minutes)")

        def work() -> None:
            import programs
            try:
                catalog, _ = programs.survey()     # afresh: the App Launcher may have been installed meanwhile
                program = next(p for p in catalog if p.name == chosen.name)
                ok, message = programs.install(program, programs.launcher_of(catalog))
            except Exception as exc:
                ok, message = False, f"{type(exc).__name__}: {exc}"
                log(f"install {chosen.name}: {traceback.format_exc()}")
            log(f"result {chosen.name}: {'OK' if ok else 'PROBLEM'} - {message}")
            self.events.put(("installed", [f"{chosen.name}: {message}"]))
            self.events.put(("checked", check_all()))

        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        for btn in (self.install_btn, self.check_btn, self.close_btn, *self.program_btns):
            btn.state(["disabled"] if busy else ["!disabled"])
        if not busy and not self.picks:
            self.install_btn.state(["disabled"])
        self.progress.config(text=text)

    def recheck(self) -> None:
        self.set_busy(True, "Checking GitHub...")
        threading.Thread(target=lambda: self.events.put(("checked", check_all())), daemon=True).start()

    def install_selected(self) -> None:
        chosen = [(repo, rebuild.get()) for repo, pick, rebuild in self.picks.values() if pick.get()]
        if not chosen:
            return
        self.set_busy(True, "Installing...")

        def work() -> None:
            results = []
            for repo, rebuild in chosen:
                self.events.put(("progress", f"Installing {repo.name}..."
                                 + (" (rebuilding the .exe can take a few minutes)" if rebuild and repo.build else "")))
                try:
                    ok, message = install(repo, rebuild)
                except Exception as exc:
                    ok, message = False, f"{type(exc).__name__}: {exc}"
                    log(f"install {repo.name}: {traceback.format_exc()}")
                log(f"result {repo.name}: {'OK' if ok else 'PROBLEM'} - {message}")
                results.append(f"{repo.name}: {message}")
            self.events.put(("installed", results))
            self.events.put(("checked", check_all()))

        threading.Thread(target=work, daemon=True).start()

    def poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.progress.config(text=value)
                elif kind == "installed":
                    from tkinter import messagebox
                    messagebox.showinfo("GitHub Updater", "\n".join(value), parent=self.root)
                elif kind == "checked":
                    save_state(last_check=dt.date.today().isoformat())
                    self.render(value)
                    self.set_busy(False)
                    self.render_programs(survey_programs(value))
        except queue.Empty:
            pass
        self.root.after(200, self.poll)

    def toggle_startup(self) -> None:
        try:
            set_startup(self.startup.get())
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("GitHub Updater", f"Could not change the Startup shortcut:\n{exc}",
                                 parent=self.root)
            self.startup.set(STARTUP_LNK.exists())

    def show(self) -> None:
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))
        self.root.mainloop()


# --------------------------------------------------------------------------- modes
def survey_programs(repos: list[Repo]):
    """programs.survey(repos), or None if it fails: the Programs list must never stop the update check."""
    try:
        import programs
        return programs.survey(repos)
    except Exception:
        log("programs survey failed:\n" + traceback.format_exc())
        return None


def record_check(repos: list[Repo]) -> None:
    # Offline (every repo failed to fetch) does not count as today's check: try again later.
    if repos and all(r.status == "error" for r in repos):
        return
    save_state(last_check=dt.date.today().isoformat())


def background() -> None:
    import msvcrt
    DATA.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "a+")
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return                      # another checker is already running
    log("background checker started")
    while True:
        try:
            if load_json(STATE).get("last_check") != dt.date.today().isoformat():
                repos = check_all()
                record_check(repos)
                if any(r.status in ("update", "blocked") for r in repos):
                    Window(repos).show()
        except Exception:
            log("background error:\n" + traceback.format_exc())
        time.sleep(POLL_SECONDS)


def print_report(repos: list[Repo]) -> None:
    if not repos:
        print(f"No GitHub clones found in {ROOT}")
    width = max((len(r.name) for r in repos), default=0) + 2
    for repo in repos:
        print(f"  {repo.name:<{width}}{repo.summary()}")
        for title in repo.titles:
            print(f"  {'':<{width}}  - {title}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep the GitHub clones on this computer up to date.")
    parser.add_argument("--background", action="store_true", help="daily checker (run at login)")
    parser.add_argument("--window", action="store_true", help="no console: open the window and check in it")
    parser.add_argument("--check", action="store_true", help="print the report and change nothing")
    parser.add_argument("--startup", choices=("on", "off"), help="add or remove the login shortcut")
    args = parser.parse_args()

    if args.background:
        background()
        return
    if args.window:
        Window(None).show()
        return
    try:
        if args.startup:
            set_startup(args.startup == "on")
            print(f"Daily check at login: {args.startup}  ({STARTUP_LNK})")
        else:
            print("Checking GitHub for updates...\n")
            repos = check_all()
            print_report(repos)
            if not args.check:
                record_check(repos)
                Window(repos).show()
    except Exception:
        traceback.print_exc()
    try:
        input("\nPress Enter to close")
    except (EOFError, RuntimeError):     # no console (run windowless)
        pass


if __name__ == "__main__":
    main()
