# Braillings Separation — Design Spec

Separate Braillings into two concerns: a terminal Lemmings diorama (the core product) and an optional directory launcher extension.

## Current State

`braillings.py` is a ~1280-line monolith that conflates the game engine, diorama viewer, menu system, config loading, and directory picker. The directory picker IS the product — there is no way to just watch lemmings.

## Goal

- `braillings.py` — a living terminal screensaver. Lemmings spawn, navigate levels autonomously. Arrow keys to pan, q/Esc to quit. No menus, no config, no directories, no hint bar.
- `braillings-launcher.py` — directory launcher that imports from braillings and layers on menu stamping, config loading, number key selection, explosion trigger, and stdout path output.
- `setup-launcher` — renamed from `setup`, configures shell integration pointing to `braillings-launcher.py`.

## Architecture

### Shared Level Preparation

Extract from current `main()` into a `prepare_level()` function:

```python
def prepare_level():
    """Load a random level and compose the world.
    Does NOT call pre_render_braille — caller does that after any menu stamping.
    Returns: world, exits, traps, water, exit_center, entrances, pool, header, palette
    """
```

`walk_surface_y` calculation stays in the launcher's `main()` since only the launcher needs it (for `stamp_menu` positioning). The diorama ignores it.

Both entry points call `prepare_level()`. The launcher inserts `stamp_menu()` between preparation and rendering:

```
Diorama:  prepare_level() → world.pre_render_braille() → game_loop()
Launcher: prepare_level() → stamp_menu(world, ...) → world.pre_render_braille() → game_loop()
```

### Refactored game_loop

```python
def game_loop(world, exits, traps, water, exit_center, entrances, pool,
              header, tty_fd, palette,
              focus_x=None,            # viewport center x (default: entrance area)
              text_pixel_coords=None,  # mischievous lemming targets (list, default: [])
              exclude_rect=None,       # rect to exclude from animated object rendering
              handle_key=None,         # input extension: byte → result or None
              after_frame=None):       # post-render hook (presence reserves bottom row)
    """Run the game loop. Returns result from handle_key, or None if quit."""
```

**Removed from game_loop:** `config`, `menu_rect` parameters. Number key handling, hint bar rendering, `selected`/`selected_path`/`valid_keys` state.

**Parameters:**

- `focus_x` — world-pixel x coordinate that the viewport centers on. Replaces `menu_x + menu_w // 2` in the viewport formula `vx = max(0, min(focus_x - view_pw // 2 + cam_offset, LEVEL_WIDTH - view_pw))`. Diorama default: `entrances[0]["spawn_x"]`. Launcher passes: `menu_x + menu_w // 2`.

- `text_pixel_coords` — list of (x, y) tuples for mischievous lemming targeting. Launcher passes `list(stamp_menu_result)` (converting the set to a list since `random.choice` requires a sequence). Diorama passes nothing — mischievous lemmings with no targets behave as normal lemmings.

- `exclude_rect` — `(x, y, w, h)` tuple passed to `stamp_objects()` to prevent animated objects from rendering over this area. Launcher passes the menu rect. Diorama passes `None` (no exclusion needed). This replaces the current `menu_rect` parameter's role in `stamp_objects`.

- `handle_key(byte)` — called for each keypress that isn't arrow/quit. Returns a result value (e.g. a path string) if a selection was made, `None` if the key isn't relevant. **When a non-None result is returned, game_loop:**
  1. Stops spawning new lemmings
  2. Sets all non-dead, non-exited lemmings to "ohno" state (bomb_timer=0)
  3. Continues the game loop until all lemmings are dead/exited (`alive_count == 0`)
  4. Returns the result

  The diorama passes `None` — non-navigation keys are ignored. game_loop always returns `None` when quit.

- `after_frame(tty_out)` — called after each frame render. When provided, game_loop reserves the bottom terminal row (`th = rows - 2` instead of `rows - 1`). The launcher uses this for the hint bar ("Run ./setup-launcher to use Braillings as a directory picker"). The diorama passes `None` — no hint bar, full viewport height.

### What Lives Where

**Stays in `braillings.py`:**
- All imports, constants, bitflags (SOLID, STEEL, etc.)
- World class
- Level compositing (`composite_level`, `build_exit_triggers`, `build_ability_pool`)
- Rendering (`compute_cell`, `pre_render_braille`, `stamp_objects`, braille/ANSI conversion)
- Lemming class + all AI logic
- `prepare_level()` — new shared helper
- `game_loop()` — refactored with optional callbacks
- `main()` — diorama mode: `prepare_level()` → `world.pre_render_braille()` → `game_loop()` with no callbacks. Returns `None` always.

**Moves to `braillings-launcher.py`:**
- `STANDALONE_LABELS` (Pink Floyd songs)
- `load_config()`
- `wrap_text()`
- `stamp_menu()`
- `handle_key` callback (closure capturing config and selection state)
- `after_frame` callback (hint bar with "Run ./setup-launcher..." text)
- `main()` — launcher mode: `load_config()` → `prepare_level()` → compute `walk_surface_y` → `stamp_menu()` → `world.pre_render_braille()` → `game_loop()` with callbacks → if result is not None, `print(os.path.expanduser(result))` to stdout

**Unchanged:**
- `braillings_font.py` — shared by both
- `gamedata/gamedata.pkl` — shared by both

### setup-launcher

Renamed from `setup`. Changes:
- `BRAILLINGS_PY` variable points to `braillings-launcher.py`
- Option c ("Just the fun experience") updated: instead of "Pink Floyd mode," it says "Just watch the lemmings" and points to `python3 braillings.py` (the diorama). It still offers to remove existing config and shell integration. The Pink Floyd standalone labels are a launcher feature (launcher with no config), not a setup option.
- Standalone mode message: `"Run: python3 $SCRIPT_DIR/braillings.py"` (points to the diorama, not the launcher)

### README

Restructured to lead with the diorama:

```
# Braillings

DOS Lemmings in your terminal, rendered in braille characters.
Watch lemmings navigate levels autonomously. Pan with arrow keys.

## Quick Start
git clone ... && python3 braillings.py

## Directory Launcher (optional)
Braillings can also work as a directory picker — menu items become
platforms lemmings walk on, pick a destination, watch them explode.

python3 braillings-launcher.py     # standalone with fun labels
./setup-launcher                   # configure real directories + shell integration
```

## Implementation Summary

1. Extract `prepare_level()` from current `main()`
2. Refactor `game_loop()` — remove launcher-specific code, add optional callbacks, add `exclude_rect` for `stamp_objects`
3. Write new diorama `main()` in `braillings.py`
4. Create `braillings-launcher.py` with extracted launcher code + its own `main()`
5. Rename `setup` → `setup-launcher`, update script reference and option c behavior
6. Update `README.md`
