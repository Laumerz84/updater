# Setup instructions for Claude

You are Claude Code on someone's Windows PC, and they asked you to follow this file. It installs the
Laumerz84 tools with the GitHub Updater. Follow the steps in order. Ask the person only where a step
says to; decide everything else yourself and mention what you decided in your final report.
Nothing gets downloaded before step 3's yes.

## 1. Check the PC (change nothing)

- Windows: required. On anything else, stop and say these tools are Windows-only.
- `python --version`: 3.11 or newer.
- `git --version`.
- `gh --version` (GitHub's command-line tool; only needed for the private programs).
- Look for an existing projects folder: one that already holds GitHub clones (folders with a `.git`
  inside), such as `%USERPROFILE%\Python`, `%USERPROFILE%\source\repos` or `%USERPROFILE%\code`. Note whether
  the clones are all in one folder or spread over several.
- Check whether the Updater is already installed: any folder holding a clone of
  `https://github.com/Laumerz84/updater.git`. If it is, this is a re-run: say so in step 3. The
  installer only adds what is missing.

## 2. What will be installed

| Program | What it is | Repo |
| --- | --- | --- |
| App Launcher | Starts and stops these tools from one small window | public |
| GitHub Updater | Checks them for updates once a day and offers to install them | public |
| UtilityBelt | Terminal dashboard for the PC and Claude Code work | public |
| UI Report Tool | Annotated screenshots for Claude Code, from the tray | public |
| Codebase Dashboard | Code stats and git activity for a folder, in the browser | public |
| Ekxel | Excel-style spreadsheet with a Claude panel | **private** |
| Clipper | Instant replay: a hotkey saves the last minute of a game (**AMD graphics cards only**) | **private** |

About 3 GB on disk in total, mostly Ekxel's and UI Report Tool's libraries plus Clipper's ffmpeg. Each
program gets a Start menu or App Launcher entry, and the Updater adds a shortcut to the Startup folder
so its daily check runs at login. The private ones need a GitHub account that is a member of the
Laumerz84 organization.

## 3. Ask the person (one message, then wait)

Show them the table above (shortened is fine), then ask together:

1. "Install these?" Default: all of them.
2. If any of Python 3.11+, Git or gh is missing: "May I install the missing ones with winget?" Without
   winget or a yes, give them the download pages (python.org, git-scm.com, cli.github.com) and stop.
3. "Do you want the private ones (Ekxel, Clipper)? That needs your GitHub account, which must be in the
   Laumerz84 organization." Default: yes if `gh auth status` already shows a login.
4. Only if step 1 found no single obvious projects folder: "Which folder should they go in?" Suggest
   `%USERPROFILE%\Python`, or the folder that holds most of their clones.

## 4. Prerequisites

- Install what they agreed to: `winget install --id Python.Python.3.13 -e`, `winget install --id Git.Git -e`,
  `winget install --id GitHub.cli -e` (add `--accept-package-agreements --accept-source-agreements`).
  Open a new shell afterwards, or find the new exe by its full path, because PATH is not refreshed in a
  running shell.
- Private programs wanted:
  - `gh auth status`. If not logged in: `gh auth login --web --git-protocol https`, and walk them
    through the browser step (it shows a one-time code to type in).
  - `gh auth setup-git`, so git uses that login. The installer switches off git's sign-in pop-ups,
    so without this the private repos are silently skipped.
  - `gh repo view Laumerz84/sheets --json name`. If it fails, they probably have not accepted the
    organization invite yet: send them to https://github.com/orgs/Laumerz84/invitation, then check again.
    If they are not a member at all, go on without the private ones.

## 5. Install

1. Create the folder if needed. Then, in it: `git clone https://github.com/Laumerz84/updater.git Updater`
   (skip if step 1 found it; run `git -C <it> pull --ff-only` instead).
2. Clones spread over several folders? Write `Updater\repos.local.json` listing the folders outside the
   main one, so the installer finds them instead of cloning second copies:
   `{"extra": ["D:\\work\\ui-report-tool", "..."], "ignore": []}`. It is not tracked by git.
3. Leaving programs out: add `--skip <name>` for each one to the command below, e.g.
   `--skip Clipper --skip Ekxel`. The App Launcher and the Updater are always installed. (Private ones
   they have no access to are skipped automatically anyway.)
4. Run `python Updater\install.py` (plus any `--skip`) from the main folder. It asks nothing, takes a few minutes, and ends
   with a "Result" list.
   **If you are the Claude desktop app** (your shell runs inside its sandbox, e.g. `%APPDATA%` writes
   land under `...\Packages\Claude_*\LocalCache\`), run it outside the sandbox. Otherwise pip installs,
   settings and the daily checker go into a private copy that the person's own apps never see:

   ```powershell
   $py = "<full path to python.exe, not the WindowsApps alias>"
   $cmd = "cmd.exe /c cd /d `"<main folder>\Updater`" && `"$py`" install.py > install-log.txt 2>&1 < nul"
   Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd}
   ```

   Wait until `install-log.txt` ends with "Log:" and the process is gone, then read the file.
   (Where `.cmd` files are blocked, `cmd.exe /c` used like this still works. Or give the person
   `Updater\Install.pyw` to double-click instead: it shows the same output in a window.)
5. Exit code 0 / "Install finished" = done. On "Needs attention" lines, fix what you can (a missing
   tool, a failed pip install: rerun install.py, since it only does what is still missing) and report
   the rest.

## 6. Report back

In plain words:

- what is installed and where;
- what was skipped and why (no access, they said no, AMD-only);
- where to start things: **App Launcher** in the Start menu;
- that the GitHub Updater now checks daily and asks before installing anything.

Don't paste the whole log. Mention `%LOCALAPPDATA%\Updater\updater.log` in case they need it.
