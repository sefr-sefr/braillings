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

STANDALONE_LABELS = [
    ("Several Species of Small Furry Animals Gathered Together in a Cave", None),
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
            hint = "Demo mode — run ./setup-launcher to configure directories"
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
