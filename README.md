# Braillings

DOS Lemmings in your terminal, rendered in braille characters. Watch lemmings spawn, navigate levels autonomously, and interact with terrain. Pan with arrow keys, quit with Esc.

![Braillings diorama](assets/diorama.gif)

## Quick Start

```bash
git clone https://github.com/peteraxelblom/braillings.git
cd braillings
python3 braillings.py
```

No dependencies beyond Python 3.

## Directory Launcher (optional)

Braillings can also work as a directory picker — menu items become platforms that lemmings walk on. Pick a destination, watch them all explode, and land in that directory.

![Braillings launcher](assets/launcher.gif)

```bash
python3 braillings-launcher.py     # standalone with fun labels
./setup-launcher                   # configure real directories + shell integration
```

Setup will:
- Suggest directories from your shell history (opt-in)
- Let you choose: launch on terminal start, manual command, or screensaver only
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

Edit this file directly or re-run `./setup-launcher`.

## Controls

### Diorama (braillings.py)
- **Arrow keys:** Pan the camera
- **Esc / q / Ctrl-C:** Quit

### Launcher (braillings-launcher.py)
- **Number keys (1-9):** Select a destination
- **Arrow keys:** Pan the camera
- **Esc / q / Ctrl-C:** Quit without selecting
