# Braillings Separation — Design Spec

Separate Braillings into two concerns: a terminal Lemmings diorama (the core product) and an optional directory launcher extension.

## Current State

`braillings.py` is a ~1280-line monolith that conflates the game engine, diorama viewer, menu system, config loading, and directory picker. The directory picker IS the product — there is no way to just watch lemmings.

## Goal

- `braillings.py` — a living terminal screensaver. Lemmings spawn, navigate levels autonomously. Arrow keys to pan, q/Esc to quit. No menus, no config, no directories.
- `braillings-launcher.py` — directory launcher that imports from braillings and layers on menu stamping, config loading, number key selection, explosion trigger, and stdout path output.
- `setup-launcher` — renamed from `setup`, configures shell integration pointing to `braillings-launcher.py`.

## Architecture

### Shared Level Preparation

Extract from current `main()` into a `prepare_level()` function:

```python
def prepare_level():
    """Load a random level and compose the world.
    Does NOT call pre_render_braille — caller does that after any menu stamping."""
    # Returns: world, exits, traps, water, exit_center, entrances, pool, header, palette, walk_surface_y
```

Both entry points call this. The launcher inserts `stamp_menu()` between `prepare_level()` and `pre_render_braille()`:

```
Diorama:  prepare_level() → pre_render_braille() → game_loop()
Launcher: prepare_level() → stamp_menu() → pre_render_braille() → game_loop()
```

### Refactored game_loop

```python
def game_loop(world, exits, traps, water, exit_center, entrances, pool,
              header, tty_fd, palette,
              focus_x=None,            # viewport center x (default: entrance area)
              text_pixel_coords=None,  # mischievous lemming targets (default: none)
              handle_key=None,         # input extension: byte → result or None
              after_frame=None):       # post-render hook (presence reserves bottom row)
    """Run the game loop. Returns result from handle_key, or None if quit."""
```

**Removed from game_loop:** `config`, `menu_rect` parameters. Number key handling, hint bar rendering, `selected`/`selected_path`/`valid_keys` state.

**Added:** 4 optional parameters, each with one purpose:
- `focus_x` — viewport centering. Launcher passes menu center x. Diorama defaults to entrance x.
- `text_pixel_coords` — targets for mischievous lemmings. Launcher passes menu text pixels. Diorama passes nothing (mischievous lemmings behave normally without targets).
- `handle_key(byte)` — called for each keypress that isn't arrow/quit. Returns a result value if selection made, `None` if key not relevant. When a result is returned, game_loop triggers the explosion sequence (all lemmings → "ohno" → wait for all to finish) then returns the result.
- `after_frame(tty_out)` — called after each frame render. Launcher uses this for hint bar. When provided, game_loop reserves the bottom terminal row (reduces viewport height by 1).

### What Lives Where

**Stays in `braillings.py`:**
- All imports, constants, bitflags (SOLID, STEEL, etc.)
- World class
- Level compositing (`composite_level`, `build_exit_triggers`, `build_ability_pool`)
- Rendering (`compute_cell`, `pre_render_braille`, braille/ANSI conversion)
- Lemming class + all AI logic
- `prepare_level()` — new shared helper
- `game_loop()` — refactored with optional callbacks
- `main()` — diorama mode: `prepare_level()` → `pre_render_braille()` → `game_loop()` with no callbacks

**Moves to `braillings-launcher.py`:**
- `STANDALONE_LABELS` (Pink Floyd songs)
- `load_config()`
- `wrap_text()`
- `stamp_menu()`
- `handle_key` callback (closure capturing config and selection state)
- `after_frame` callback (hint bar)
- `main()` — launcher mode: `load_config()` → `prepare_level()` → `stamp_menu()` → `pre_render_braille()` → `game_loop()` with callbacks → stdout output

**Unchanged:**
- `braillings_font.py` — shared by both
- `gamedata/gamedata.pkl` — shared by both

### setup-launcher

Renamed from `setup`. Only change: shell snippet references `braillings-launcher.py` instead of `braillings.py`.

```bash
BRAILLINGS_PY="$SCRIPT_DIR/braillings-launcher.py"
```

### README

Restructured to lead with the diorama:

```
# Braillings

DOS Lemmings in your terminal, rendered in braille characters.
Watch lemmings navigate levels autonomously. Pan with arrow keys.

## Quick Start
git clone ... && python3 braillings.py

## Directory Launcher (optional)
Braillings can also work as a directory picker...
python3 braillings-launcher.py
./setup-launcher
```

## Implementation Summary

1. Extract `prepare_level()` from current `main()`
2. Refactor `game_loop()` — remove launcher-specific code, add optional callbacks
3. Write new diorama `main()` in `braillings.py`
4. Create `braillings-launcher.py` with extracted launcher code + its own `main()`
5. Rename `setup` → `setup-launcher`, update script reference
6. Update `README.md`
