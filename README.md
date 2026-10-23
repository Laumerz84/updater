# GitHub Updater

Keeps the GitHub clones on this computer up to date, and installs the recommended programs.

Every folder in the Python folder that is a git clone of a GitHub repo, plus any folder listed
under `"extra"` in `repos.local.json`, is checked once a day. When GitHub has commits this
computer does not, a window lists them and offers to install them.

Installing an update is a fast-forward and nothing else. A clone with uncommitted changes to
tracked files, or with commits that were never pushed, is shown as blocked and left alone. After
an update, a changed `requirements.txt` is reinstalled with pip, and a locally built `dist\*.exe`
is rebuilt if its box is ticked.

## Install everything (or have Claude do it)

Needs Windows, Python 3.11+ and Git. Clone this repo into the folder that holds your projects,
then run `install.py` in it:

```
cd <your projects folder>
git clone https://github.com/Laumerz84/updater.git Updater
python Updater\install.py
```

`install.py` asks nothing. For each recommended program it clones what is missing next to the
Updater, installs its libraries, makes its Start menu shortcut, and adds its App Launcher card;
then it turns on the daily update check. It ends with a list of what is installed, and exits 0
when everything that could be installed is. A program in a private repository you have no access
to is skipped and named. Run it again any time; it only does what is still missing.
`python install.py --list` shows the state and changes nothing.

To hand it to someone else's Claude Code, give them this:

> Install the GitHub Updater and its recommended programs, without asking me anything.
> Use the folder that already holds my GitHub clones; if there is none, create `%USERPROFILE%\Python`.
> In that folder run `git clone https://github.com/Laumerz84/updater.git Updater`, then
> `python Updater\install.py`. If it says Python 3.11+ or Git is missing, stop and tell me.
> When it finishes, tell me what its Result list says, including anything skipped or needing attention.

## The recommended programs

Listed in `catalog.json` (the App Launcher, this Updater, UtilityBelt, UI Report Tool, Ekxel and
Codebase Dashboard). The window's **Recommended programs** list shows each one as installed, not
installed, or installed without an App Launcher card, with an **Install** or **Add card** button.
Below it, your other GitHub clones are listed by whether they have an App Launcher card.
Existing cards are never replaced. Because the catalog is part of this repo, a new recommendation
reaches everyone with the next daily update.

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
| `install.py` | Install the recommended programs that are missing, and turn on the daily check |
| `install.py --list` | Show what is installed, change nothing |

## Settings

`repos.local.json` (create it if you need it; it is not in git, so editing it never blocks an
update): `"extra"` adds clones kept outside the Python folder; `"ignore"` skips Python-folder
clones by folder name. `repos.json` has the same shape and is shared by everyone.

State and the log live in `%LOCALAPPDATA%\Updater`, out of OneDrive.
