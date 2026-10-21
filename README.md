# GitHub Updater

Keeps the GitHub clones on this computer up to date.

Every folder in the Python folder that is a git clone of a GitHub repo, plus any folder listed
under `"extra"` in `repos.json`, is checked once a day. When GitHub has commits this computer does
not, a window lists them and offers to install them.

Installing is a fast-forward and nothing else. A clone with uncommitted changes to tracked files,
or with commits that were never pushed, is shown as blocked and left alone. After an install, a
changed `requirements.txt` is reinstalled with pip, and a locally built `dist\*.exe` is rebuilt
if its box is ticked.

## Use

Double-click `updater.py` to check now and see the window.

| Command | What it does |
| --- | --- |
| `updater.py` | Check now and show the window (double-click) |
| `updater.py --window` | The same with no console (the App Launcher's button) |
| `updater.py --background` | What the Startup shortcut runs: check once a day, open the window only when something is out of date |
| `updater.py --check` | Print the report, change nothing |
| `updater.py --startup on` | Add the Startup-folder shortcut and start the daily checker |
| `updater.py --startup off` | Remove it |

## Settings

`repos.json`: `"extra"` adds clones kept outside the Python folder; `"ignore"` skips
Python-folder clones by folder name.

State and the log live in `%LOCALAPPDATA%\Updater`, out of OneDrive.
