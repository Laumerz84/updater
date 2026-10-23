"""One-click install for a fresh PC: download this file, double-click it, press Install.

It gets the GitHub Updater (git clone) into your projects folder, then runs its install.py,
which installs every recommended program (App Launcher, UtilityBelt, UI Report Tool, Ekxel,
Codebase Dashboard), makes their Start menu shortcuts and App Launcher cards, and turns on the
daily update check. A .pyw, not a .cmd or .bat, because many work PCs block those; it runs with
the Python that opened it and shows its own window, no console.

Needs: Windows, Python 3.11+ (with "py launcher"/file association, as python.org's installer sets
up), and Git. If Git is missing it offers to install it with winget, or opens the download page.
Standard library only. Safe to run again: it updates what is there and installs what is missing.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

REPO = "https://github.com/Laumerz84/updater.git"
MIN_PYTHON = (3, 11)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GIT_DOWNLOAD = "https://git-scm.com/download/win"


def console_python() -> str:
    """python.exe next to the pythonw.exe running this (install.py prints to a console stream)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def find_git() -> str | None:
    git = shutil.which("git")
    if git:
        return git
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
        for sub in (r"Git\cmd\git.exe", r"Programs\Git\cmd\git.exe"):
            p = Path(base) / sub
            if base and p.is_file():
                return str(p)
    return None


def default_folder() -> Path:
    """The folder that already holds an Updater clone, or %USERPROFILE%\\Python (the README's default)."""
    here = Path(__file__).resolve().parent
    if (here / ".git").exists() and (here / "install.py").is_file():
        return here.parent                                  # run from inside a clone: use its folder
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Python"


class Installer:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Install Laumerz84 tools")
        self.root.geometry("760x520")
        self.root.minsize(560, 380)
        self.lines: queue.Queue = queue.Queue()
        self.busy = False

        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Installs the GitHub Updater and the recommended programs.",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(top, text="App Launcher · UtilityBelt · UI Report Tool · Ekxel · Codebase Dashboard · Clipper, "
                            "plus a daily update check.").pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(top)
        row.pack(fill="x")
        ttk.Label(row, text="Install into:").pack(side="left")
        self.folder = tk.StringVar(value=str(default_folder()))
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Change…", command=self.pick).pack(side="left")

        buttons = ttk.Frame(top)
        buttons.pack(fill="x", pady=(10, 0))
        self.go = ttk.Button(buttons, text="Install", command=self.start)
        self.go.pack(side="left")
        self.git_btn = ttk.Button(buttons, text="Install Git for me", command=self.install_git)
        self.close = ttk.Button(buttons, text="Close", command=self.root.destroy)
        self.close.pack(side="right")
        self.status = ttk.Label(top, text="")
        self.status.pack(anchor="w", pady=(8, 0))

        box = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        box.pack(fill="both", expand=True)
        self.out = tk.Text(box, wrap="word", height=16, font=("Consolas", 9), state="disabled")
        bar = ttk.Scrollbar(box, command=self.out.yview)
        self.out.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)

        self.preflight()
        self.root.after(100, self.drain)

    # -- checks before anything changes
    def preflight(self) -> None:
        problems = []
        if sys.platform != "win32":
            problems.append("This installer is for Windows.")
        if sys.version_info < MIN_PYTHON:
            problems.append(f"Python {'.'.join(map(str, MIN_PYTHON))} or newer is needed; this is "
                            f"{sys.version.split()[0]}. Install a newer one from python.org, then open this again.")
        if find_git() is None:
            problems.append("Git is not installed. Press \"Install Git for me\", or install Git for Windows "
                            "from git-scm.com, then press Install.")
            self.git_btn.pack(side="left", padx=6)
        if problems:
            self.say("\n".join(problems))
            self.status.configure(text="Not ready yet: see below.")
        else:
            self.status.configure(text="Ready. Press Install. Takes a few minutes (it downloads the programs "
                                       "and their libraries).")

    def pick(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder.get(), title="Folder for your projects")
        if chosen:
            self.folder.set(str(Path(chosen)))

    # -- output
    def say(self, text: str) -> None:
        self.lines.put(text)

    def drain(self) -> None:
        try:
            while True:
                text = self.lines.get_nowait()
                self.out.configure(state="normal")
                self.out.insert("end", text.rstrip("\n") + "\n")
                self.out.see("end")
                self.out.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def run(self, cmd: list[str], cwd: Path) -> int:
        """Run a command, streaming its output into the window."""
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                env=env, creationflags=NO_WINDOW)
        for line in proc.stdout:
            self.say(line)
        return proc.wait()

    # -- Git, if missing
    def install_git(self) -> None:
        if shutil.which("winget") is None:
            webbrowser.open(GIT_DOWNLOAD)
            self.say("winget is not available here, so the Git download page was opened. "
                     "Install it, then press Install.")
            return
        self.git_btn.configure(state="disabled")
        self.say("Installing Git with winget (Windows may ask for permission)…")

        def work() -> None:
            code = self.run(["winget", "install", "--id", "Git.Git", "-e", "--silent",
                             "--accept-package-agreements", "--accept-source-agreements"], Path.home())
            if find_git():
                self.say("Git is installed. Press Install.")
                self.root.after(0, lambda: self.status.configure(text="Ready. Press Install."))
            else:
                self.say(f"winget finished (code {code}) but Git was not found. Opening the download page.")
                webbrowser.open(GIT_DOWNLOAD)
            self.root.after(0, lambda: self.git_btn.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    # -- the install
    def start(self) -> None:
        if self.busy:
            return
        git = find_git()
        if git is None or sys.version_info < MIN_PYTHON:
            self.preflight()
            return
        self.busy = True
        self.go.configure(state="disabled")
        self.status.configure(text="Installing… (keep this window open)")
        threading.Thread(target=self.work, args=(git, Path(self.folder.get())), daemon=True).start()

    def work(self, git: str, folder: Path) -> None:
        ok = False
        try:
            ok = self.install(git, folder)
        except Exception as exc:                           # shown, never a silent crash
            self.say(f"\nStopped: {type(exc).__name__}: {exc}")
        self.root.after(0, lambda: self.finish(ok))

    def install(self, git: str, folder: Path) -> bool:
        folder.mkdir(parents=True, exist_ok=True)
        updater = self.find_updater(git, folder)
        if updater is None:
            updater = folder / "Updater"
            self.say(f"Getting the GitHub Updater into {updater}…")
            if self.run([git, "clone", "--quiet", REPO, str(updater)], folder) != 0:
                self.say("Could not download it. Check the internet connection (and that github.com is "
                         "reachable from this PC), then press Install again.")
                return False
        else:
            self.say(f"The GitHub Updater is already at {updater}; updating it…")
            self.run([git, "-C", str(updater), "pull", "--ff-only", "--quiet"], updater)
        self.say("\nInstalling the programs…\n")
        # put git's folder on PATH for install.py, in case it was just installed
        os.environ["PATH"] = str(Path(git).parent) + os.pathsep + os.environ.get("PATH", "")
        return self.run([console_python(), "install.py"], updater) == 0

    def find_updater(self, git: str, folder: Path) -> Path | None:
        """An existing Updater clone in the folder, whatever it is called."""
        for p in [folder / "Updater", *sorted(x for x in folder.iterdir() if x.is_dir())]:
            if (p / ".git").exists() and (p / "install.py").is_file():
                try:
                    url = subprocess.run([git, "-C", str(p), "remote", "get-url", "origin"], capture_output=True,
                                         text=True, creationflags=NO_WINDOW).stdout.strip().lower()
                except OSError:
                    continue
                if "laumerz84/updater" in url:
                    return p
        return None

    def finish(self, ok: bool) -> None:
        self.busy = False
        self.go.configure(state="normal", text="Run again")
        if ok:
            self.status.configure(text="Done. Open the App Launcher from the Start menu.")
            self.say("\nDone. Open \"App Launcher\" from the Start menu.")
        else:
            self.status.configure(text="Finished with problems: see below (anything installed stays installed).")

    def show(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Installer().show()
