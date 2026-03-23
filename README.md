# Braillings

A terminal directory picker that renders DOS Lemmings levels using braille characters. Menu items become solid platforms that lemmings walk on. Pick a destination and watch them all explode.

## Quick Start

```bash
git clone https://github.com/peteraxelblom/braillings.git
cd braillings
python3 braillings.py
```

That's it. No dependencies beyond Python 3.

## Setup for Directory Switching

Want to use it as an actual directory picker?

```bash
./setup
```

Setup will:
- Suggest directories from your shell history (opt-in)
- Let you choose: launch on terminal start, manual command, or standalone fun mode
- Optionally start Claude in the selected directory
- Show you exactly what it adds to your shell config before changing anything

## Requirements

- Python 3 (stdlib only, no pip packages). Gamedata was baked with Python 3.9.6.
- A terminal that supports Unicode braille characters and ANSI truecolor
- macOS or Linux

## Config

After running setup, destinations live in `~/.config/braillings/config`:

```
# display_name|/path/to/directory
projects|~/projects
work|~/work/repo
```

Edit this file directly or re-run `./setup`.

## Controls

- **Number keys (1-9):** Select a destination
- **Arrow keys:** Pan the camera
- **Esc / q / Ctrl-C:** Quit without selecting
