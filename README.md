# Braillings

DOS Lemmings in your terminal, rendered in braille characters. Watch lemmings spawn, navigate levels autonomously, and interact with terrain. Pan with arrow keys, quit with Esc.

![Diorama mode](assets/diorama.png)

![Directory launcher](assets/launcher.png)

## Quick Start

```bash
git clone https://github.com/peteraxelblom/braillings.git
cd braillings
python3 braillings.py
```

No dependencies beyond Python 3.

## Directory Launcher (optional)

Braillings can also work as a directory picker — menu items become platforms that lemmings walk on. Pick a destination, watch them all explode, and land in that directory.

```bash
python3 braillings-launcher.py     # standalone with fun labels
./setup-launcher                   # configure real directories + shell integration
```

Setup will:
- Suggest directories from your shell history (opt-in)
- Let you choose: launch on terminal start, manual command, or screensaver only
- Optionally start Claude in the selected directory
- Show you exactly what it adds to your shell config before changing anything

### Warp Terminal

Auto-launch is intentionally skipped in [Warp](https://www.warp.dev). Warp routes anything that runs during shell startup into an output block that doesn't pass keystrokes through, so the launcher would render but ignore your input. The shell snippet checks `$TERM_PROGRAM` and bails out under Warp; the `braillings` function (manual mode) is still defined, so you can type `braillings` once the prompt appears and it works normally.

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
