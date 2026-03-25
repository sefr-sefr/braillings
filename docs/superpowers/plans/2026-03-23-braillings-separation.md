# Braillings Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate braillings.py into a standalone diorama viewer and an optional directory launcher extension.

**Architecture:** Extract `prepare_level()` from `main()`, refactor `game_loop()` to accept optional callbacks (`handle_key`, `after_frame`, `exclude_rect`, `focus_x`, `text_pixel_coords`), move launcher-specific code (config, menu, hint bar) into `braillings-launcher.py`, rename setup → setup-launcher, update README.

**Tech Stack:** Python 3 (stdlib only), Bash

**Spec:** `docs/superpowers/specs/2026-03-23-braillings-separation-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `braillings.py` | Modify | Game engine + diorama viewer. Remove launcher code, extract `prepare_level()`, refactor `game_loop()` with callbacks, new diorama `main()`. |
| `braillings-launcher.py` | Create | Directory launcher. Imports from braillings, adds config loading, menu stamping, selection handling, hint bar, stdout output. |
| `setup-launcher` | Create (rename) | Renamed from `setup`. Updated script reference + option c behavior. |
| `setup` | Delete | Replaced by `setup-launcher`. |
| `README.md` | Modify | Restructured: diorama first, launcher as optional extension. |

---

### Task 1: Extract prepare_level() from main()

**Files:**
- Modify: `braillings.py:1252-1320`

Extract the shared level loading and world composition from `main()` into a reusable `prepare_level()` function.

- [ ] **Step 1: Read the current main() to identify the shared section**

Lines 1262-1300 (from `level = random.choice(_LEVELS)` through entrance detection and animation marking) are shared by both diorama and launcher. Lines 1302-1320 (walk_surface_y, terminal width, stamp_menu) are launcher-only.

- [ ] **Step 2: Create prepare_level() function**

Add before `main()` in `braillings.py`:

```python
def prepare_level():
    """Load a random level and compose the world.
    Does NOT call pre_render_braille — caller does that after any menu stamping.
    Returns: (world, exits, traps, water, exit_center, entrances, pool, header, palette)
    """
    level = random.choice(_LEVELS)
    header, objects, terrain_pieces, steel = (
        level["header"], level["objects"], level["terrain"], level["steel"])
    gfx_set = header["graphic_set"]
    assets = _ASSETS[gfx_set]
    tiles, obj_sprites, palette = assets["tiles"], assets["obj_sprites"], assets["palette"]

    world = World(LEVEL_WIDTH, LEVEL_HEIGHT)
    world._bulk = True
    composite_level(world, header, objects, terrain_pieces, steel,
                    tiles, obj_sprites, palette, assets["obj_info"])
    world._bulk = False

    exits, traps, water = build_exit_triggers(objects, assets["obj_info"])

    # Exit center for AI targeting
    exit_obj = None
    for o in objects:
        if o["obj_id"] == 0:
            exit_obj = o
            break
    exit_center = (exit_obj["x"] + 24, exit_obj["y"] + 16) if exit_obj else (LEVEL_WIDTH // 2, LEVEL_HEIGHT // 2)

    # Entrances (may be multiple — round-robin spawning)
    ent_spr = obj_sprites.get(1)
    entrances = []
    for o in objects:
        if o["obj_id"] == 1:
            sx = o["x"] + (ent_spr["w"] // 2 if ent_spr else 24)
            sy = o["y"] + (ent_spr["h"] if ent_spr else 25)
            entrances.append({"x": o["x"], "spawn_x": sx, "spawn_y": sy})
    if not entrances:
        entrances = [{"x": 200, "spawn_x": 224, "spawn_y": 45}]

    # Mark entrance objects as playing their opening animation once
    for ao in getattr(world, 'anim_objects', []):
        if ao["obj_id"] == 1:
            ao["play_once"] = True
            ao["started_tick"] = 0

    pool = build_ability_pool(header["skills"])

    return world, exits, traps, water, exit_center, entrances, pool, header, palette
```

- [ ] **Step 3: Verify prepare_level works**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
python3 -c "
from braillings import prepare_level
result = prepare_level()
print(f'prepare_level returned {len(result)} values')
world, exits, traps, water, exit_center, entrances, pool, header, palette = result
print(f'World: {world.w}x{world.h}, Entrances: {len(entrances)}, Pool: {len(pool)}')
"
```

Expected: returns 9 values, world is 1584x160, at least 1 entrance.

- [ ] **Step 4: Commit**

```bash
git add braillings.py
git commit -m "refactor: extract prepare_level() from main()"
```

---

### Task 2: Refactor game_loop() with optional callbacks

**Files:**
- Modify: `braillings.py` (the `game_loop` function)

**IMPORTANT: Line numbers below are from the pre-Task-1 state.** After Task 1 inserts `prepare_level()` (~48 lines), all line numbers shift by ~48. **Search by the code content shown in each step, not by line number.**

This is the core refactoring. Remove launcher-specific code, add optional callback parameters.

- [ ] **Step 1: Change the function signature**

Replace the current signature (line 1036-1037):
```python
def game_loop(world, exits, traps, water, exit_center, entrances, pool,
              text_pixel_coords, config, header, tty_fd, palette, menu_rect=None):
```

With:
```python
def game_loop(world, exits, traps, water, exit_center, entrances, pool,
              header, tty_fd, palette,
              focus_x=None, text_pixel_coords=None, exclude_rect=None,
              handle_key=None, after_frame=None):
    """Run the game loop.
    focus_x: world-pixel x to center viewport on (default: first entrance).
    text_pixel_coords: list of (x,y) for mischievous lemming targeting.
    exclude_rect: (x,y,w,h) to exclude from animated object rendering.
    handle_key(byte): input callback, returns result value or None.
    after_frame(tty_out): post-render hook. Presence reserves bottom terminal row.
    Returns: result from handle_key, or None if quit.
    """
```

- [ ] **Step 2: Replace standalone/hint bar setup with after_frame detection**

Replace lines 1045-1053 (standalone detection + th calculation):
```python
    standalone = any(path is None for _, path in config)
    if standalone:
        th = rows - 2
    else:
        th = rows - 1
```

With:
```python
    if after_frame:
        th = rows - 2  # reserve bottom row for after_frame hook
    else:
        th = rows - 1
```

- [ ] **Step 3: Replace menu_rect viewport centering with focus_x**

Replace line 1058-1059:
```python
    # Use menu rect from stamp_menu for viewport centering
    menu_x, _menu_y, menu_w, _menu_h = menu_rect
```

With:
```python
    # Viewport centering
    _focus_x = focus_x if focus_x is not None else entrances[0]["spawn_x"]
```

And replace line 1162:
```python
            vx = max(0, min(menu_x + menu_w // 2 - view_pw // 2 + cam_offset,
                            LEVEL_WIDTH - view_pw))
```

With:
```python
            vx = max(0, min(_focus_x - view_pw // 2 + cam_offset,
                            LEVEL_WIDTH - view_pw))
```

- [ ] **Step 4: Remove launcher-specific state variables**

Remove lines 1067-1068 and 1075:
```python
    selected = None
    selected_path = None
    ...
    valid_keys = ''.join(str(i + 1) for i in range(min(len(config), 9)))
```

Replace with:
```python
    _selection_result = None
```

- [ ] **Step 5: Remove the initial hint bar render**

Delete lines 1081-1086 (the `if standalone:` block that renders the hint bar on startup). The launcher's `after_frame` callback handles this.

- [ ] **Step 6: Refactor spawn guard to use _selection_result**

Replace line 1098:
```python
            if (selected is None and spawned < MAX_LEMMINGS
```

With:
```python
            if (_selection_result is None and spawned < MAX_LEMMINGS
```

- [ ] **Step 7: Refactor spawning to use text_pixel_coords parameter**

The spawn block (lines 1101-1119) already uses `text_pixel_coords` correctly. Ensure it handles `None`:

Line 1106 currently reads:
```python
                    tgt = random.choice(text_pixel_coords) if text_pixel_coords else None
```

This already works when `text_pixel_coords` is `None` or empty. No change needed.

- [ ] **Step 8: Replace number key handling with handle_key callback**

Replace lines 1140-1152 (the `elif selected is None and chr(buf[i]) in valid_keys:` block):

```python
                    elif selected is None and chr(buf[i]) in valid_keys:
                        idx = buf[i] - ord('1')
                        selected = idx
                        selected_path = config[idx][1]
                        for lem in lemmings:
                            if not lem.dead and not lem.exited:
                                lem.state = "ohno"
                                lem.frame = 0
                                lem.tick = 0
                                lem.bomb_timer = 0
                        i += 1
                    else:
                        i += 1
```

With:
```python
                    elif handle_key and _selection_result is None:
                        result = handle_key(buf[i])
                        if result is not None:
                            _selection_result = result
                            for lem in lemmings:
                                if not lem.dead and not lem.exited:
                                    lem.state = "ohno"
                                    lem.frame = 0
                                    lem.tick = 0
                                    lem.bomb_timer = 0
                        i += 1
                    else:
                        i += 1
```

- [ ] **Step 9: Pass exclude_rect to stamp_objects**

Replace line 1190:
```python
            obj_overlay = stamp_objects(world, game_tick, palette, menu_rect)
```

With:
```python
            obj_overlay = stamp_objects(world, game_tick, palette, exclude_rect)
```

- [ ] **Step 10: Replace hint bar redraw with after_frame call**

Replace lines 1226-1229:
```python
            # Redraw hint bar every frame (dirty-cell updates may overwrite it)
            if standalone:
                tty_out.write(hint_ansi)
                tty_out.flush()
```

With:
```python
            if after_frame:
                after_frame(tty_out)
```

- [ ] **Step 11: Replace selected check with _selection_result**

Replace line 1232:
```python
            if selected is not None and alive_count == 0:
```

With:
```python
            if _selection_result is not None and alive_count == 0:
```

- [ ] **Step 12: Update return value**

Replace line 1247:
```python
    return selected_path
```

With:
```python
    return _selection_result
```

- [ ] **Step 13: Verify game_loop signature is clean**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
python3 -c "
import inspect
from braillings import game_loop
sig = inspect.signature(game_loop)
print('game_loop parameters:')
for name, param in sig.parameters.items():
    default = param.default if param.default is not inspect.Parameter.empty else '<required>'
    print(f'  {name}: {default}')
"
```

Expected: `focus_x`, `text_pixel_coords`, `exclude_rect`, `handle_key`, `after_frame` all show as optional with `None` defaults. No `config`, `menu_rect`, or `text_pixel_coords` as required.

- [ ] **Step 14: Commit**

```bash
git add braillings.py
git commit -m "refactor: game_loop accepts optional callbacks, remove launcher-specific code"
```

---

### Task 3: Write diorama main() in braillings.py

**Files:**
- Modify: `braillings.py` (replace current `main()`)

Remove the current launcher-based `main()` and replace with a clean diorama entry point.

- [ ] **Step 1: Remove launcher code from top of file**

Delete the following from `braillings.py` (all move to `braillings-launcher.py` in the next task):
- `STANDALONE_LABELS` constant (around line 28-35)
- `load_config()` function (around line 253-292)
- `wrap_text()` (around line 330-348)
- `stamp_menu()` (around line 350-410)
- `from braillings_font import FONT, CHAR_H, CHAR_GAP, text_width, stamp_text` (line 26) — after removing `wrap_text` and `stamp_menu`, nothing in `braillings.py` uses the font module anymore.

- [ ] **Step 2: Replace main() with diorama version**

Replace the entire `main()` function with:

```python
def main():
    """Run Braillings as a terminal diorama — watch lemmings navigate a level."""
    world, exits, traps, water, exit_center, entrances, pool, header, palette = prepare_level()
    world.pre_render_braille()

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    try:
        game_loop(world, exits, traps, water, exit_center, entrances, pool,
                  header, tty_fd, palette)
    finally:
        os.close(tty_fd)
```

No config loading, no menu stamping, no stdout output. Just load a level, render it, run the game loop.

- [ ] **Step 3: Verify the diorama imports are self-contained**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
python3 -c "from braillings import main, prepare_level, game_loop; print('All imports OK')"
```

- [ ] **Step 4: Commit**

```bash
git add braillings.py
git commit -m "refactor: replace launcher main() with diorama-only main()"
```

---

### Task 4: Create braillings-launcher.py

**Files:**
- Create: `braillings-launcher.py`

This file imports the game engine from braillings.py and adds the directory launcher layer.

- [ ] **Step 1: Create braillings-launcher.py with imports**

**IMPORTANT:** `STANDALONE_LABELS`, `load_config`, `wrap_text`, and `stamp_menu` were deleted from `braillings.py` in Task 3. They belong in THIS file. Do NOT import them from braillings.

```python
"""
Braillings Launcher — directory picker powered by the Braillings diorama.
Stamps menu text as solid platforms, select a destination to make lemmings explode.
Standalone mode: Pink Floyd songs as fun labels (no config needed).
Directory mode: real paths via ~/.config/braillings/config.
All rendering to /dev/tty; stdout reserved for the selected path only.
"""
import os, sys, struct, random, fcntl, termios

from braillings import prepare_level, game_loop, LEVEL_HEIGHT
from braillings_font import text_width, stamp_text, CHAR_H, CHAR_GAP
```

- [ ] **Step 2: Add STANDALONE_LABELS and load_config**

Paste the `STANDALONE_LABELS` constant and `load_config()` function (previously deleted from braillings.py) into braillings-launcher.py:

```python
STANDALONE_LABELS = [
    ("Several Species of Small Furry Animals Gathered Together in a Cave", None),
    ("Careful with That Axe, Eugene", None),
    ("Alan's Psychedelic Breakfast", None),
    ("Set the Controls for the Heart of the Sun", None),
    ("Is There Anybody Out There?", None),
    ("Come In Number 51, Your Time Is Up", None),
]


def load_config():
    """Read ~/.config/braillings/config. Returns list of (display_name, full_path).
    Falls back to Pink Floyd song labels in standalone mode (path=None)."""
    config_path = os.path.expanduser("~/.config/braillings/config")
    if not os.path.exists(config_path):
        return list(STANDALONE_LABELS)
    with open(config_path, "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    if not lines:
        return list(STANDALONE_LABELS)
    explicit = []
    auto_paths = []
    for line in lines:
        if "|" in line:
            name, path = line.split("|", 1)
            explicit.append((name.strip(), path.strip()))
        else:
            auto_paths.append(line)
    if auto_paths:
        expanded = [os.path.expanduser(p) for p in auto_paths]
        if len(expanded) == 1:
            auto_display = [os.path.basename(expanded[0].rstrip("/"))]
        else:
            prefix = os.path.commonpath(expanded)
            auto_display = [os.path.relpath(ep, prefix) for ep in expanded]
        auto_items = list(zip(auto_display, auto_paths))
    else:
        auto_items = []
    result = []
    auto_idx = 0
    for line in lines:
        if "|" in line:
            name, path = line.split("|", 1)
            result.append((name.strip(), path.strip()))
        else:
            result.append(auto_items[auto_idx])
            auto_idx += 1
    return result
```

- [ ] **Step 3: Add wrap_text and stamp_menu**

Paste the `wrap_text()` and `stamp_menu()` functions (previously deleted from braillings.py):

```python
def wrap_text(text, max_width, indent=0):
    """Wrap text at word boundaries to fit within max_width pixels.
    Returns list of (indent_px, line_text) tuples."""
    words = text.split(' ')
    lines = []
    current_line = ''
    for word in words:
        candidate = f"{current_line} {word}".strip()
        line_indent = indent if lines else 0
        if text_width(candidate) + line_indent > max_width and current_line:
            lines.append((indent if len(lines) > 0 else 0, current_line))
            current_line = word
        else:
            current_line = candidate
    if current_line:
        lines.append((indent if len(lines) > 0 else 0, current_line))
    return lines


def stamp_menu(world, config, entrance_x, walk_surface_y, water=None, term_cols=80):
    """Stamp menu text + halo into world. Returns (text_pixels_set, menu_rect_tuple)."""
    if not config:
        return set(), (0, 0, 0, 0)

    line_gap = 3
    padding = 4
    max_text_width = (term_cols * 2) - 40

    all_lines = []
    for i, (label, _path) in enumerate(config):
        prefix = f"{i + 1}. "
        prefix_width = text_width(prefix)
        first_line_text = prefix + label
        if text_width(first_line_text) <= max_text_width:
            all_lines.append((0, first_line_text))
        else:
            wrapped = wrap_text(label, max_text_width - prefix_width, indent=prefix_width)
            for j, (indent, line_text) in enumerate(wrapped):
                if j == 0:
                    all_lines.append((0, prefix + line_text))
                else:
                    all_lines.append((indent, line_text))

    menu_h = len(all_lines) * (CHAR_H + line_gap) - line_gap + padding * 2
    menu_x = entrance_x + 60
    menu_y = max(2, walk_surface_y - padding)
    menu_y = min(menu_y, LEVEL_HEIGHT - menu_h - 2)

    menu_w_estimate = max(text_width(t) + ind for ind, t in all_lines) + padding * 2
    if water:
        for _ in range(20):
            overlaps = False
            for wz in water:
                if (menu_x < wz["x"] + wz["w"] and menu_x + menu_w_estimate > wz["x"]
                        and menu_y < wz["y"] + wz["h"] + 6 and menu_y + menu_h > wz["y"]):
                    overlaps = True
                    menu_x = wz["x"] + wz["w"] + 10
                    break
            if not overlaps:
                break

    menu_w = menu_w_estimate
    text_color = (240, 240, 0)
    all_text_pixels = set()
    for i, (indent, label) in enumerate(all_lines):
        ty = menu_y + padding + i * (CHAR_H + line_gap)
        cx = menu_x + padding + indent
        pixels = stamp_text(world, cx, ty, label, text_color)
        all_text_pixels |= pixels

    for tx, ty in all_text_pixels:
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                px, py = tx + dx, ty + dy
                if (px, py) not in all_text_pixels:
                    world.clear_visual(px, py)

    return all_text_pixels, (menu_x, menu_y, menu_w, menu_h)
```

- [ ] **Step 4: Add the launcher main()**

```python
def main():
    config = load_config()
    if not config:
        try:
            with open("/dev/tty", "w") as t:
                t.write("braillings-launcher: config file is empty. "
                        "Add entries or delete it for standalone mode.\n")
        except OSError:
            pass
        return None

    world, exits, traps, water, exit_center, entrances, pool, header, palette = prepare_level()

    # Walk surface detection for menu placement
    spawn_x = entrances[0]["spawn_x"]
    spawn_y = entrances[0]["spawn_y"]
    walk_surface_y = spawn_y
    for y in range(spawn_y, LEVEL_HEIGHT):
        if world.canvas[y][spawn_x] is not None:
            walk_surface_y = y - 1
            break

    # Get terminal width for menu wrapping
    try:
        _tty_fd_tmp = os.open("/dev/tty", os.O_RDONLY)
        _buf = fcntl.ioctl(_tty_fd_tmp, termios.TIOCGWINSZ, b'\x00' * 8)
        _term_cols = struct.unpack('HHHH', _buf)[1]
        os.close(_tty_fd_tmp)
    except OSError:
        _term_cols = 80

    text_pixels, menu_rect = stamp_menu(
        world, config, entrances[0]["x"], walk_surface_y, water, _term_cols)
    text_pixel_coords = list(text_pixels)
    world.pre_render_braille()

    menu_x, _my, menu_w, _mh = menu_rect

    # Build handle_key callback
    standalone = any(path is None for _, path in config)
    valid_keys = ''.join(str(i + 1) for i in range(min(len(config), 9)))
    selected = [False]  # mutable flag in closure

    def handle_key(byte):
        ch = chr(byte)
        if not selected[0] and ch in valid_keys:
            selected[0] = True
            idx = byte - ord('1')
            label, path = config[idx]
            # Return label for standalone (truthy, triggers explosion) or path for directory mode
            return path if path is not None else label
        return None

    # Build after_frame callback (hint bar in standalone mode)
    if standalone:
        def make_after_frame():
            hint = "Run ./setup-launcher to use Braillings as a directory picker"
            # hint_ansi will be set on first call when we know terminal dimensions
            state = {"ansi": None}
            def after_frame(tty_out):
                if state["ansi"] is None:
                    buf = fcntl.ioctl(tty_out.fileno(), termios.TIOCGWINSZ, b'\x00' * 8)
                    rows, cols = struct.unpack('HHHH', buf)[:2]
                    hint_col = max(1, (cols - len(hint)) // 2)
                    state["ansi"] = f"\033[{rows};1H\033[2K\033[{rows};{hint_col}H\033[2m{hint}\033[0m"
                tty_out.write(state["ansi"])
                tty_out.flush()
            return after_frame
        _after_frame = make_after_frame()
    else:
        _after_frame = None

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    try:
        selected_path = game_loop(
            world, exits, traps, water, exit_center, entrances, pool,
            header, tty_fd, palette,
            focus_x=menu_x + menu_w // 2,
            text_pixel_coords=text_pixel_coords,
            exclude_rect=menu_rect,
            handle_key=handle_key,
            after_frame=_after_frame,
        )
    finally:
        os.close(tty_fd)

    # Only output to stdout in directory mode (not standalone/Pink Floyd mode)
    if selected_path and not standalone:
        print(os.path.expanduser(selected_path), end='', flush=True)

    return selected_path


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify launcher imports work**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
python3 -c "from importlib import import_module; m = import_module('braillings-launcher'); print('Import OK')"
```

Note: Python can't import filenames with hyphens directly. Test with:
```bash
python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('launcher', 'braillings-launcher.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('Import OK, has main:', hasattr(mod, 'main'))
"
```

- [ ] **Step 6: Commit**

```bash
git add braillings-launcher.py
git commit -m "feat: create braillings-launcher.py with directory picker functionality"
```

---

### Task 5: Rename setup → setup-launcher

**Files:**
- Delete: `setup`
- Create: `setup-launcher` (copy of setup with modifications)
- Modify: `setup-launcher` script reference and option c behavior

- [ ] **Step 1: Copy setup to setup-launcher**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
cp setup setup-launcher
chmod +x setup-launcher
```

- [ ] **Step 2: Update BRAILLINGS_PY variable**

In `setup-launcher`, change:
```bash
BRAILLINGS_PY="$SCRIPT_DIR/braillings.py"
```
to:
```bash
BRAILLINGS_PY="$SCRIPT_DIR/braillings-launcher.py"
```

- [ ] **Step 3: Update option c behavior**

In `setup-launcher`, in the `ask_launch_mode()` function, change option c description:
```bash
    echo "  c) Just the fun experience (Pink Floyd mode, no directory switching)"
```
to:
```bash
    echo "  c) Just watch the lemmings (screensaver mode)"
```

In `handle_standalone_mode()`, change the final message:
```bash
    echo -e "${GREEN}Standalone mode active.${RESET} Run: python3 $BRAILLINGS_PY"
```
to:
```bash
    echo -e "${GREEN}Standalone mode active.${RESET} Run: python3 $SCRIPT_DIR/braillings.py"
```

- [ ] **Step 4: Delete old setup**

```bash
git rm setup
```

- [ ] **Step 5: Verify syntax**

```bash
bash -n setup-launcher && echo "Syntax OK"
```

- [ ] **Step 6: Commit**

```bash
git add setup-launcher
git commit -m "refactor: rename setup to setup-launcher, update references"
```

---

### Task 6: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README**

```markdown
# Braillings

DOS Lemmings in your terminal, rendered in braille characters. Watch lemmings spawn, navigate levels autonomously, and interact with terrain. Pan with arrow keys, quit with Esc.

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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: restructure README — diorama first, launcher as extension"
```

---

### Task 7: End-to-end verification

**Files:** None (testing only)

- [ ] **Step 1: Test diorama mode**

```bash
cd /Users/peterblom/_CODE_/personal/braillings
python3 braillings.py
```

Verify: lemmings spawn, walk around, interact with terrain. Arrow keys pan. q/Esc quits. No menu text, no number keys, no hint bar, no stdout output.

- [ ] **Step 2: Test launcher standalone mode**

Ensure no config exists at `~/.config/braillings/config` (move it if present), then:

```bash
python3 braillings-launcher.py
```

Verify: Pink Floyd songs appear as menu platforms. Lemmings walk on them. Number key triggers explosions, then exits with no stdout output. Hint bar visible at bottom. q/Esc quits.

- [ ] **Step 3: Test launcher directory mode**

Create a test config:
```bash
mkdir -p ~/.config/braillings
echo "/tmp" > ~/.config/braillings/config
```

Run:
```bash
result=$(python3 braillings-launcher.py 2>/dev/null)
echo "Selected: $result"
```

Verify: pressing 1 triggers explosions, then `/tmp` is printed to stdout. Clean up test config after.

- [ ] **Step 4: Test setup-launcher syntax**

```bash
bash -n setup-launcher && echo "Syntax OK"
```

- [ ] **Step 5: Commit verification (no code changes)**

If any issues were found and fixed, commit them. Otherwise skip.
