"""
Braillings — a terminal directory picker rendered as a DOS Lemmings diorama.
Renders levels in braille characters with ANSI truecolor. Menu items become
solid platforms that lemmings walk on. Press a number key to select.
Standalone mode: Pink Floyd songs as fun labels (no config needed).
Directory mode: real paths via ~/.config/braillings/config.
All rendering to /dev/tty; stdout reserved for the selected path only.
"""
import os, sys, time, struct, tty, termios, select, random, fcntl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import pickle
_pkl_path = os.path.join(BASE_DIR, "gamedata", "gamedata.pkl")
try:
    with open(_pkl_path, "rb") as f:
        _data = pickle.load(f)
except FileNotFoundError:
    raise SystemExit("gamedata.pkl not found. Run: python bake_gamedata.py")
SPRITES = _data["sprites"]
PARTICLE_TABLE = _data["particles"]
PARTICLE_COLORS = _data["particle_colors"]
_LEVELS = _data["levels"]
_ASSETS = _data["assets"]
del _data
from braillings_font import FONT, CHAR_H, CHAR_GAP, text_width, stamp_text

STANDALONE_LABELS = [
    ("Several Species of Small Furry Animals Gathered Together in a Cave", None),
    ("Careful with That Axe, Eugene", None),
    ("Alan's Psychedelic Breakfast", None),
    ("Set the Controls for the Heart of the Sun", None),
    ("Is There Anybody Out There?", None),
    ("Come In Number 51, Your Time Is Up", None),
]

LEVEL_WIDTH = 1584
LEVEL_HEIGHT = 160

# Terrain bitflags
SOLID = 1
STEEL = 2
NO_DIG_LEFT = 4    # can't bash/mine rightward through this pixel
NO_DIG_RIGHT = 8   # can't bash/mine leftward through this pixel

LEM_PALETTE = {
    0: (0, 0, 0), 1: (64, 64, 224), 2: (0, 176, 0), 3: (240, 208, 208),
    4: (240, 240, 0), 5: (240, 32, 32), 6: (128, 128, 128), 7: (224, 128, 32),
}
SPRITE_OFFSETS = {
    'walk_r': (-8, -10), 'walk_l': (-8, -10), 'fall_r': (-8, -10), 'fall_l': (-8, -10),
    'exit': (-8, -13), 'ohno': (-8, -10), 'splat': (-8, -10), 'explosion': (-8, -10),
    'bash_r': (-8, -10), 'bash_l': (-8, -10),
    'build_r': (-8, -13), 'build_l': (-8, -13),
    'mine_r': (-8, -12), 'mine_l': (-8, -12),
    'climb_r': (-8, -12), 'climb_l': (-8, -12),
    'postclimb_r': (-8, -12), 'postclimb_l': (-8, -12),
    'dig': (-8, -12),
    'shrug_r': (-8, -10), 'shrug_l': (-8, -10),
    'umbrella_r': (-8, -16), 'umbrella_l': (-8, -16),
    'drown': (-8, -10), 'fried': (-8, -10),
}
PARTICLE_FULL_PAL = {
    **LEM_PALETTE,
    8: (208, 128, 32), 9: (192, 80, 16), 10: (144, 32, 16), 11: (96, 0, 16),
    12: (64, 64, 80), 13: (96, 96, 112), 14: (112, 144, 0), 15: (32, 96, 32),
}
DOT_MAP = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]
SKILL_TO_ABILITY = {
    'basher': 'bash', 'builder': 'build', 'climber': 'climb',
    'digger': 'dig', 'miner': 'mine', 'floater': 'float', 'blocker': 'block',
}


# ── World class ──────────────────────────────────────────────────────────────

class World:
    def __init__(self, width, height):
        assert width % 2 == 0 and height % 4 == 0
        self.w, self.h = width, height
        self.terrain = [[0] * width for _ in range(height)]
        self.canvas = [[None] * width for _ in range(height)]
        self.braille = [[None] * (width // 2) for _ in range(height // 4)]
        self._bulk = False  # skip braille recompute during bulk loading

    def is_solid(self, x, y):
        if x < 0 or x >= self.w:
            return True
        if y < 0:
            return False
        if y >= self.h:
            return False  # bottom of level is open — lemmings fall off and die
        return bool(self.terrain[y][x] & SOLID)

    def clear(self, x, y):
        """Clear terrain: solid, visual, and recompute braille. Refuses steel. Returns bool."""
        if 0 <= x < self.w and 0 <= y < self.h:
            if self.terrain[y][x] & STEEL:
                return False
            self.terrain[y][x] = 0
            self.canvas[y][x] = None
            self._recompute_braille(x // 2, y // 4)
            return True
        return False

    def try_clear(self, x, y, direction):
        """Clear pixel if allowed for bash/mine in given direction. Returns True if cleared."""
        if 0 <= x < self.w and 0 <= y < self.h:
            flags = self.terrain[y][x]
            if flags & STEEL:
                return False
            if direction == 1 and (flags & NO_DIG_LEFT):   # moving right, blocked by no-dig-left
                return False
            if direction == -1 and (flags & NO_DIG_RIGHT):  # moving left, blocked by no-dig-right
                return False
            self.terrain[y][x] = 0
            self.canvas[y][x] = None
            self._recompute_braille(x // 2, y // 4)
            return True
        return False

    def flags(self, x, y):
        """Return terrain flags for pixel, or 0 if out of bounds."""
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.terrain[y][x]
        return 0

    def clear_visual(self, x, y):
        """Clear visual only (for text halo). Collision intact."""
        if 0 <= x < self.w and 0 <= y < self.h:
            self.canvas[y][x] = None
            self._recompute_braille(x // 2, y // 4)

    def set(self, x, y, color, make_solid=True):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.canvas[y][x] = color
            if make_solid:
                self.terrain[y][x] |= SOLID
            if not self._bulk:
                self._recompute_braille(x // 2, y // 4)

    def _recompute_braille(self, tx, ty):
        """Recompute one braille cell from canvas data."""
        braille = 0
        rs, gs, bs, cnt = 0, 0, 0, 0
        for dy in range(4):
            for dx in range(2):
                c = self.canvas[ty * 4 + dy][tx * 2 + dx]
                if c:
                    braille |= DOT_MAP[dy][dx]
                    rs += c[0]; gs += c[1]; bs += c[2]; cnt += 1
        if cnt > 0 and braille > 0:
            self.braille[ty][tx] = (
                f"\033[38;2;{rs // cnt};{gs // cnt};{bs // cnt}m"
                f"{chr(0x2800 + braille)}")
        else:
            self.braille[ty][tx] = None

    def pre_render_braille(self):
        """Startup-only. Post-destruction: None = empty cell, never re-rendered."""
        for ty in range(self.h // 4):
            for tx in range(self.w // 2):
                braille = 0
                rs, gs, bs, cnt = 0, 0, 0, 0
                for dy in range(4):
                    for dx in range(2):
                        c = self.canvas[ty * 4 + dy][tx * 2 + dx]
                        if c:
                            braille |= DOT_MAP[dy][dx]
                            rs += c[0]; gs += c[1]; bs += c[2]; cnt += 1
                if cnt > 0 and braille > 0:
                    self.braille[ty][tx] = (
                        f"\033[38;2;{rs // cnt};{gs // cnt};{bs // cnt}m"
                        f"{chr(0x2800 + braille)}")


# ── Level compositing ────────────────────────────────────────────────────────

def composite_level(world, header, objects, terrain_pieces, steel,
                    tiles, obj_sprites, palette, obj_info=None):
    """Stamp terrain tiles and objects into World."""
    for tp in terrain_pieces:
        tile = tiles.get(tp["terrain_id"])
        if not tile:
            continue
        for py in range(tile["h"]):
            src_y = (tile["h"] - 1 - py) if tp["upside_down"] else py
            for px in range(tile["w"]):
                idx = tile["pixels"][src_y][px]
                if idx == 0:
                    continue
                wx, wy = tp["x"] + px, tp["y"] + py
                color = palette.get(idx)
                if not color:
                    continue
                if tp["erase"]:
                    world.clear(wx, wy)
                elif tp["do_not_overwrite"]:
                    if 0 <= wx < world.w and 0 <= wy < world.h and world.canvas[wy][wx] is None:
                        world.set(wx, wy, color)
                else:
                    world.set(wx, wy, color)

    # Steel: indestructible solid, but invisible (visual comes from terrain tiles underneath)
    for s in steel:
        for sy in range(s["h"]):
            for sx in range(s["w"]):
                px, py = s["x"] + sx, s["y"] + sy
                if 0 <= px < world.w and 0 <= py < world.h:
                    world.terrain[py][px] |= SOLID | STEEL

    # Objects are rendered dynamically each tick (animated), not stamped here.
    # Store object data on the world for the renderer.
    world.anim_objects = []
    for obj in objects:
        spr = obj_sprites.get(obj["obj_id"])
        if not spr or not spr["frames"]:
            continue
        world.anim_objects.append({
            "x": obj["x"], "y": obj["y"],
            "obj_id": obj["obj_id"],
            "sprites": spr["frames"],
            "w": spr["w"], "h": spr["h"],
            "loops": spr.get("loops", True),
            "start_frame": spr.get("start_frame", 0),
        })

    # One-way walls: stamp directional flags onto existing terrain pixels
    if obj_info:
        for obj in objects:
            oid = obj["obj_id"]
            effect = obj_info[oid]["effect"]
            if effect == 7:  # one-way left
                flag = NO_DIG_LEFT
            elif effect == 8:  # one-way right
                flag = NO_DIG_RIGHT
            else:
                continue
            spr = obj_sprites.get(oid)
            if not spr or not spr["frames"]:
                continue
            mask = spr["frames"][0]
            for py in range(spr["h"]):
                for px in range(spr["w"]):
                    if mask[py][px] != 0:
                        wx, wy = obj["x"] + px, obj["y"] + py
                        if 0 <= wx < world.w and 0 <= wy < world.h:
                            if world.terrain[wy][wx] & SOLID:
                                world.terrain[wy][wx] |= flag


# ── Helper functions ─────────────────────────────────────────────────────────

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
    # Parse lines: "name|path" or just "path"
    explicit = []
    auto_paths = []
    for line in lines:
        if "|" in line:
            name, path = line.split("|", 1)
            explicit.append((name.strip(), path.strip()))
        else:
            auto_paths.append(line)
    # Derive display names for paths without explicit names
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
    # Preserve original order
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


def build_exit_triggers(objects, obj_info):
    """Returns (exits, traps, water) — each list[dict] with x, y, w, h."""
    exits = []
    traps = []
    water = []
    for obj in objects:
        info = obj_info[obj["obj_id"]]
        effect = info["effect"]
        if effect not in (1, 4, 5, 6):
            continue
        zone = {"x": obj["x"] + info["trigger_left"],
                "y": obj["y"] + info["trigger_top"],
                "w": info["trigger_w"], "h": info["trigger_h"]}
        if effect == 1:
            zone["y"] += 4  # compensate for baked -4 offset in trigger_top
            exits.append(zone)
        elif effect in (4, 6):
            traps.append(zone)
        elif effect == 5:
            water.append(zone)
    return exits, traps, water


def build_ability_pool(skills):
    pool = []
    for skill, count in skills.items():
        ab = SKILL_TO_ABILITY.get(skill)
        if ab:
            pool.extend([ab] * count)
    random.shuffle(pool)
    return pool


def wrap_text(text, max_width, indent=0):
    """Wrap text at word boundaries to fit within max_width pixels.
    Returns list of (indent_px, line_text) tuples.
    First line has indent=0, continuation lines have the given indent."""
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
    """Stamp menu text + halo into world. Returns set of text pixel coords."""
    if not config:
        return set(), (0, 0, 0, 0)

    line_gap = 3
    padding = 4
    max_text_width = (term_cols * 2) - 40  # viewport pixel width minus margin

    # Build wrapped lines: list of (indent_px, text)
    all_lines = []
    for i, (label, _path) in enumerate(config):
        prefix = f"{i + 1}. "
        prefix_width = text_width(prefix)
        first_line_text = prefix + label
        if text_width(first_line_text) <= max_text_width:
            all_lines.append((0, first_line_text))
        else:
            # Wrap: first line has the prefix, continuations are indented
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

    # Avoid water zones — shift menu right if overlapping
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

    # Visual halo — clear visual only (not solid) around text
    for tx, ty in all_text_pixels:
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                px, py = tx + dx, ty + dy
                if (px, py) not in all_text_pixels:
                    world.clear_visual(px, py)

    return all_text_pixels, (menu_x, menu_y, menu_w, menu_h)


# ── Lemming class ────────────────────────────────────────────────────────────

class Lemming:
    def __init__(self, x, y, world, abilities=None,
                 mischievous=False, target_xy=None, exit_xy=(0, 0),
                 auto_bomb_tick=None):
        self.x, self.y, self.dir = x, y, 1
        self.world = world
        self.state, self.fall_dist = "fall", 0
        self.frame, self.tick = 0, 0
        self.bomb_timer, self.bomb_tick = -1, 0
        self.dead, self.exited = False, False
        # AI fields
        self.abilities = list(abilities) if abilities else []
        self.ability = self.abilities[0] if self.abilities else None
        self.mischievous = mischievous
        self.target_xy = target_xy
        self.exit_xy = exit_xy
        self.revealed = False
        self.can_float = 'float' in self.abilities
        self.palette = dict(LEM_PALETTE)
        self.auto_bomb_tick = auto_bomb_tick  # tick at which to self-destruct
        # Ability state tracking
        self._bash_hit = False
        self._mine_hit = False
        self.build_count = 0
        self._flip_count = 0

    # --- AI helpers ---
    def _get_target(self):
        return self.target_xy if self.mischievous and self.target_xy else self.exit_xy

    def _can_act(self):
        if self.mischievous:
            return True
        return self.ability is not None

    def _facing_target(self):
        tx, _ = self._get_target()
        return ((self.dir == 1 and tx > self.x)
                or (self.dir == -1 and tx < self.x)
                or abs(self.x - tx) < 5)

    def use_ability(self, which=None):
        ability = which or self.ability
        if ability == 'block':
            # Invisible solid wall — only set collision, no visual
            for dy in range(-10, 1):
                for dx in range(-2, 3):
                    px, py = self.x + dx, self.y + dy
                    if 0 <= px < self.world.w and 0 <= py < self.world.h:
                        self.world.terrain[py][px] |= SOLID
                        # Don't touch canvas or braille — wall is invisible
            self.state = 'block'
            self.frame = 0
            self.tick = 0
            if ability in self.abilities:
                self.abilities.remove(ability)
            self.ability = self.abilities[0] if self.abilities else None
            return
        self.state = ability
        self.frame = 0
        self.tick = 0
        self.build_count = 0
        if self.mischievous:
            self.revealed = True
            self.palette[2] = (240, 32, 32)
        else:
            if ability in self.abilities:
                self.abilities.remove(ability)
            self.ability = self.abilities[0] if self.abilities else None

    # --- Update ---
    def update(self, exits, traps=None, water=None):
        if self.dead or self.exited:
            return
        self.tick += 1

        # Auto-bomb after random lifetime (any state except already dying)
        if (self.auto_bomb_tick and self.tick >= self.auto_bomb_tick
                and self.bomb_timer < 0
                and self.state not in ("ohno", "explosion", "splat", "drown", "fried", "exit")):
            self.bomb_timer = 5
            self.bomb_tick = 0

        if self.bomb_timer > 0:
            self.bomb_tick += 1
            if self.bomb_tick >= 22:
                self.bomb_tick = 0
                self.bomb_timer -= 1
            if self.bomb_timer == 0:
                self.state = "ohno"
                self.frame = 0
                self.tick = 0

        if self.state == "walk":
            self._walk(exits, traps, water)
        elif self.state == "fall":
            self._fall()
        elif self.state == "bash":
            self._bash()
        elif self.state == "build":
            self._build()
        elif self.state == "climb":
            self._climb()
        elif self.state == "postclimb":
            self._postclimb()
        elif self.state == "dig":
            self._dig()
        elif self.state == "mine":
            self._mine()
        elif self.state == "shrug":
            self._shrug()
        elif self.state == "block":
            if self.tick % 4 == 0:
                self.frame = (self.frame + 1) % 16
        elif self.state == "ohno":
            self._ohno()
        elif self.state == "explosion":
            self._explosion()
        elif self.state == "exit":
            self._exit_anim()
        elif self.state == "splat":
            self._splat()
        elif self.state == "drown":
            self._drown()
        elif self.state == "fried":
            self._fried()

    # --- State methods ---
    def _ohno(self):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 16
        if self.tick >= 32:
            R = 14
            for dy in range(-R, R + 1):
                for dx in range(-R, R + 1):
                    if dx * dx + dy * dy <= R * R:
                        self.world.clear(self.x + dx, self.y + dy)
            self.state = "explosion"
            self.frame = 0
            self.tick = 0

    def _explosion(self):
        self.frame += 1
        if self.frame >= 51:
            self.dead = True

    def _exit_anim(self):
        self.frame = (self.frame + 1) % 8
        if self.tick >= 8:
            self.exited = True

    def _splat(self):
        self.frame = (self.frame + 1) % 16
        if self.frame >= 16 or self.tick >= 16:
            self.dead = True

    def _drown(self):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 16
        if self.tick >= 32:
            self.dead = True

    def _fried(self):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 14
        if self.tick >= 28:
            self.dead = True

    # --- Walk with AI triggers ---
    def _walk(self, exits, traps=None, water=None):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 8

        # Exit check
        for ex in exits:
            if (ex["x"] <= self.x <= ex["x"] + ex["w"]
                    and ex["y"] <= self.y <= ex["y"] + ex["h"] + 6):
                self.state = "exit"
                self.frame = 0
                self.tick = 0
                return

        # Trap check — block before dying if possible
        if traps:
            for tr in traps:
                if (tr["x"] <= self.x <= tr["x"] + tr["w"]
                        and tr["y"] <= self.y <= tr["y"] + tr["h"] + 6):
                    if self._can_act() and 'block' in self.abilities:
                        self.x -= self.dir  # step back out of trap
                        self.use_ability('block')
                        return
                    self.state = "fried"
                    self.frame = 0
                    self.tick = 0
                    return

        # Water check — block before drowning if possible
        if water:
            for wz in water:
                if (wz["x"] <= self.x <= wz["x"] + wz["w"]
                        and wz["y"] <= self.y <= wz["y"] + wz["h"] + 6):
                    if self._can_act() and 'block' in self.abilities:
                        self.x -= self.dir  # step back out of water
                        self.use_ability('block')
                        return
                    self.state = "drown"
                    self.y = wz["y"]  # drown at water surface, not bottom
                    self.frame = 0
                    self.tick = 0
                    return

        # Position trigger: dig/mine when target is below
        if self._can_act():
            tx, ty = self._get_target()
            if ty > self.y + 10 and abs(self.x - tx) < 30:
                if self.mischievous:
                    self.use_ability('dig')
                    return
                else:
                    # Check all remaining abilities for dig/mine
                    for ab in self.abilities:
                        if ab in ('dig', 'mine'):
                            self.use_ability(ab)
                            return

        nx = self.x + self.dir
        if self.world.is_solid(nx, self.y):
            wh = 0
            for dy in range(7):
                if self.world.is_solid(nx, self.y - dy):
                    wh = dy + 1
                else:
                    break  # TODO: removing this break may fix thin-wall sticking (see flip failsafe below)
            if wh <= 6 and not self.world.is_solid(nx, self.y - wh):
                self.x, self.y = nx, self.y - wh
                self._flip_count = 0
            else:
                # Wall too tall — check all remaining abilities
                if self._can_act() and self._facing_target():
                    if self.mischievous:
                        self.use_ability('bash')
                        return
                    for ab in self.abilities:
                        if ab in ('bash', 'build', 'mine'):
                            self.use_ability(ab)
                            return
                        if ab == 'climb':
                            self.use_ability('climb')
                            return
                self.dir = -self.dir
                self._flip_count += 1
                if self._flip_count >= 6:
                    self.state = "ohno"
                    self.frame = 0
                    self.tick = 0
            return

        # Look ahead: will moving to nx cause a fall?
        has_ground_at_nx = self.world.is_solid(nx, self.y + 1)
        if not has_ground_at_nx:
            has_ground_at_nx = any(self.world.is_solid(nx, self.y + 1 + dy) for dy in range(1, 4))

        # Block BEFORE stepping to the edge — stay 2px back
        if not has_ground_at_nx and self._can_act() and 'block' in self.abilities and not self._facing_target():
            self.x -= self.dir  # step back from edge
            self.use_ability('block')
            return

        self.x = nx
        self._flip_count = 0
        if self.world.is_solid(self.x, self.y + 1):
            return
        for dy in range(1, 4):
            if self.world.is_solid(self.x, self.y + 1 + dy):
                self.y += dy
                return

        # Gap — try build or fall
        if self._can_act() and 'build' in self.abilities and self._facing_target():
            self.use_ability('build')
        else:
            self.state = "fall"
            self.fall_dist = 0

    # --- Fall with float ---
    def _fall(self):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 4
        speed = min(self.fall_dist // 8 + 1, 3)
        if self.can_float and self.fall_dist > 4:
            speed = 1
            self.ability_used = True
        for _ in range(speed):
            self.y += 1
            self.fall_dist += 1
            if self.world.is_solid(self.x, self.y + 1):
                if self.fall_dist >= 60 and not self.can_float:
                    self.state = "splat"
                    self.frame = 0
                    self.tick = 0
                    return
                else:
                    self.state = "walk"
                    self.frame = 0
                return
            if self.world.is_solid(self.x, self.y):
                self.y -= 1
                self.state = "walk"
                self.frame = 0
                return
            if self.y >= LEVEL_HEIGHT + 20:
                self.dead = True
                return

    # --- Ability states ---
    def _bash(self):
        self.frame = (self.frame + 1) % 32
        if 2 <= self.frame <= 5:
            stripe = self.frame - 1
            for dy in range(-9, 1):
                px, py = self.x + self.dir * stripe, self.y + dy
                if self.world.is_solid(px, py):
                    if self.world.try_clear(px, py, self.dir):
                        self._bash_hit = True
                    else:
                        # Hit steel or one-way — stop bashing
                        self.state = "walk"; self.frame = 0; return
                if self.frame == 5:
                    px2 = self.x + self.dir * 5
                    if self.world.is_solid(px2, py):
                        if self.world.try_clear(px2, py, self.dir):
                            self._bash_hit = True
                        else:
                            self.state = "walk"; self.frame = 0; return
        if self.frame == 5:
            if not self._bash_hit:
                self.state = "walk"
                self.frame = 0
                return
            self._bash_hit = False
        if 11 <= self.frame <= 15:
            self.x += self.dir
            if not self.world.is_solid(self.x, self.y + 1):
                for dy in range(1, 4):
                    if self.world.is_solid(self.x, self.y + 1 + dy):
                        self.y += dy
                        return
                self.state = "fall"
                self.fall_dist = 0

    def _build(self):
        pf = self.frame
        self.frame = (self.frame + 1) % 16
        if self.frame == 0 and pf == 15:
            self.build_count += 1
            if self.build_count >= 12:
                self.state = "shrug"
                self.frame = 0
                self.tick = 0
                return
            self.y -= 1
            self.x += self.dir
            if self.world.is_solid(self.x, self.y - 8):
                self.state = "walk"
                self.frame = 0
                self.dir = -self.dir
                return
        if self.frame == 9:
            bx = self.x + (0 if self.dir > 0 else -4)
            for i in range(6):
                px, py = bx + i, self.y - 1
                self.world.set(px, py, (224, 128, 32))
        if self.frame == 10:
            self.x += self.dir

    def _climb(self):
        if self.tick % 3 == 0:
            self.frame = (self.frame + 1) % 8
        self.y -= 1
        if (self.world.is_solid(self.x, self.y - 1)
                and self.world.is_solid(self.x + self.dir, self.y)):
            self.dir = -self.dir
            self.state = "fall"
            self.fall_dist = 0
            return
        if not self.world.is_solid(self.x + self.dir, self.y):
            self.state = "postclimb"
            self.frame = 0
            self.tick = 0

    def _postclimb(self):
        if self.tick % 2 == 0:
            self.frame = (self.frame + 1) % 8
        if self.tick >= 8:
            self.x += self.dir
            if not self.world.is_solid(self.x, self.y + 1):
                for dy in range(1, 5):
                    if self.world.is_solid(self.x, self.y + 1 + dy):
                        self.y += dy
                        break
            self.state = "walk"
            self.frame = 0

    def _dig(self):
        self.frame = (self.frame + 1) % 16
        if self.frame != 0 and self.frame != 8:
            return
        if self.y + 1 >= LEVEL_HEIGHT:
            self.dead = True
            return
        any_solid = False
        any_cleared = False
        for dx in range(-4, 5):
            px, py = self.x + dx, self.y + 1
            if self.world.is_solid(px, py):
                any_solid = True
                if self.world.clear(px, py):
                    any_cleared = True
        if any_cleared:
            self.y += 1
        elif any_solid:
            # All solid pixels are steel — stop digging
            self.state = "walk"
            self.frame = 0
        else:
            self.state = "fall"
            self.fall_dist = 0

    def _mine(self):
        self.frame = (self.frame + 1) % 24
        if self.y + 1 >= LEVEL_HEIGHT:
            self.dead = True
            return
        if self.frame == 0:
            self._mine_hit = False
        if self.frame in (1, 2):
            for dy in range(-1, 5):
                for dx in range(-1, 3):
                    px = self.x + self.dir * (dx + self.frame)
                    py = self.y + dy
                    if self.world.is_solid(px, py):
                        if self.world.try_clear(px, py, self.dir):
                            self._mine_hit = True
                        else:
                            # Hit steel or one-way — stop mining
                            self.state = "walk"; self.frame = 0; return
        if self.frame == 2 and not self._mine_hit:
            if not self.world.is_solid(self.x, self.y + 1):
                self.state = "fall"
                self.fall_dist = 0
            else:
                self.state = "walk"
                self.frame = 0
            return
        if self.frame == 3:
            self.y += 1
        if self.frame == 15:
            self.x += self.dir

    def _shrug(self):
        if self.tick % 3 == 0:
            self.frame += 1
        key = self.sprite_key()
        frames = SPRITES.get(key, [])
        if frames and self.frame >= len(frames):
            self.state = "walk"
            self.frame = 0
            self.dir = -self.dir

    def sprite_key(self):
        d = "_r" if self.dir == 1 else "_l"
        if self.state == "exit":
            return "exit"
        if self.state == "ohno":
            return "ohno"
        if self.state == "explosion":
            return "explosion"
        if self.state == "splat":
            return "splat"
        if self.state == "drown":
            return "drown"
        if self.state == "fried":
            return "fried"
        if self.state == "fall":
            return ("umbrella" + d) if self.can_float and self.fall_dist > 4 else ("fall" + d)
        if self.state == "bash":
            return "bash" + d
        if self.state == "build":
            return "build" + d
        if self.state == "mine":
            return "mine" + d
        if self.state == "climb":
            return "climb" + d
        if self.state == "postclimb":
            return "postclimb" + d
        if self.state == "dig":
            return "dig"
        if self.state == "shrug":
            return "shrug" + d
        if self.state == "block":
            return "block"
        return "walk" + d


# ── Rendering helpers ────────────────────────────────────────────────────────

def stamp_objects(world, game_tick, palette, menu_rect=None):
    """Stamp animated object sprites into an overlay dict {(x,y): (r,g,b)}.
    Objects are rendered BEFORE lemmings so lemmings draw on top.
    Skips objects that overlap menu_rect (mx, my, mw, mh) to avoid hiding text."""
    overlay = {}
    if not hasattr(world, 'anim_objects'):
        return overlay
    for obj in world.anim_objects:
        # Skip objects that overlap menu area
        if menu_rect:
            mx, my, mw, mh = menu_rect
            if (obj["x"] < mx + mw and obj["x"] + obj["w"] > mx
                    and obj["y"] < my + mh and obj["y"] + obj["h"] > my):
                continue
        frames = obj["sprites"]
        if not frames:
            continue
        if obj.get("play_once"):
            # Frame 0 = idle/closed. Frames 1+ = opening animation.
            # Show frame 0 during delay, then play 1→last, hold last.
            start = obj.get("start_frame", 1)
            elapsed = game_tick - obj.get("started_tick", 0)
            delay = 30
            if elapsed < delay:
                fi = start  # idle state
            else:
                fi = min(start + (elapsed - delay) // 3, len(frames) - 1)
        elif obj["loops"]:
            fi = (game_tick // 2) % len(frames)
        else:
            fi = 0
        frame = frames[fi]
        ox, oy = obj["x"], obj["y"]
        if obj["obj_id"] == 0:
            oy += 4  # exit sprite sits 4px above terrain in raw DOS data
        for py in range(obj["h"]):
            for px in range(obj["w"]):
                idx = frame[py][px]
                if idx != 0:
                    color = palette.get(idx)
                    if color:
                        overlay[(ox + px, oy + py)] = color
    return overlay


# 3x5 pixel digits for bomb countdown
_DIGITS = {
    1: ["X.","X.","X.","X.","X."],
    2: ["XX","X.","XX",".X","XX"],
    3: ["XX",".X","XX",".X","XX"],
    4: ["X.",".X","XX",".X",".X"],
    5: ["XX",".X","XX","X.","XX"],
}

def stamp_lemmings(lemmings):
    """Stamp all lemming sprites/particles into an overlay dict {(x,y): (r,g,b)}."""
    overlay = {}
    for lem in lemmings:
        if lem.dead or lem.exited:
            continue
        if lem.state == "explosion" and lem.frame < len(PARTICLE_TABLE):
            for pi, (pdx, pdy) in enumerate(PARTICLE_TABLE[lem.frame]):
                if pdx == -128:
                    continue
                ci = PARTICLE_COLORS[pi % 16]
                overlay[(lem.x + pdx, lem.y + pdy)] = PARTICLE_FULL_PAL.get(ci, (255, 0, 255))
            continue
        key = lem.sprite_key()
        frames = SPRITES.get(key, [])
        offset = SPRITE_OFFSETS.get(key, (-8, -10))
        if not frames:
            continue
        frame = frames[lem.frame % len(frames)]
        sx, sy = lem.x + offset[0], lem.y + offset[1]
        for fy, row in enumerate(frame):
            for fx, idx in enumerate(row):
                if idx != 0:
                    overlay[(sx + fx, sy + fy)] = lem.palette.get(idx, (255, 0, 255))
        # Bomb countdown digit above head
        if lem.bomb_timer > 0:
            digit = _DIGITS.get(lem.bomb_timer)
            if digit:
                dx_base = lem.x - 1
                dy_base = sy - 6  # above the sprite
                for dy, row in enumerate(digit):
                    for dx, ch in enumerate(row):
                        if ch == 'X':
                            overlay[(dx_base + dx, dy_base + dy)] = (255, 255, 255)
    return overlay


def braille_cell_fast(canvas, overlay, wpx, wpy):
    """Render one 2x4 block using pre-stamped overlay."""
    braille = 0
    rs, gs, bs, cnt = 0, 0, 0, 0
    for dy in range(4):
        for dx in range(2):
            x, y = wpx + dx, wpy + dy
            c = overlay.get((x, y))
            if c is None and 0 <= x < LEVEL_WIDTH and 0 <= y < LEVEL_HEIGHT:
                c = canvas[y][x]
            if c is not None:
                braille |= DOT_MAP[dy][dx]
                rs += c[0]; gs += c[1]; bs += c[2]; cnt += 1
    if cnt > 0 and braille > 0:
        r, g, b = rs // cnt, gs // cnt, bs // cnt
        return f"\033[38;2;{r};{g};{b}m{chr(0x2800 + braille)}"
    return " "


# ── Game loop ────────────────────────────────────────────────────────────────

def game_loop(world, exits, traps, water, exit_center, entrances, pool,
              text_pixel_coords, config, header, tty_fd, palette, menu_rect=None):
    """Run the game loop. Returns selected path or None."""
    tty_out = os.fdopen(os.dup(tty_fd), "w")

    # Get terminal size from /dev/tty, not stdout (which may be a pipe)
    buf = fcntl.ioctl(tty_fd, termios.TIOCGWINSZ, b'\x00' * 8)
    rows, cols = struct.unpack('HHHH', buf)[:2]
    tw = cols
    standalone = any(path is None for _, path in config)
    if standalone:
        th = rows - 2  # reserve last row for hint bar
    else:
        th = rows - 1
    view_ph = min(th * 4, LEVEL_HEIGHT)
    th = view_ph // 4
    tw = min(tw, LEVEL_WIDTH // 2)
    view_pw = tw * 2

    level_tw = LEVEL_WIDTH // 2
    level_th = LEVEL_HEIGHT // 4

    # Use menu rect from stamp_menu for viewport centering
    menu_x, _menu_y, menu_w, _menu_h = menu_rect

    MAX_LEMMINGS = header["num_lemmings"]
    SPAWN_INTERVAL = max(10, 100 - header["release_rate"])
    lemmings = []
    world.lemmings = lemmings  # shared reference for blocker collision
    tps = 22
    prev_dirty = []
    selected = None
    selected_path = None
    game_tick = 0
    spawned = 0
    cam_offset = 0
    last_vx = -999
    quit_no_selection = False

    valid_keys = ''.join(str(i + 1) for i in range(min(len(config), 9)))

    # Alt screen + hidden cursor
    tty_out.write("\033[?25l\033[?1049h")
    tty_out.flush()

    if standalone:
        hint = "Run ./setup to use Braillings as a directory picker"
        hint_col = max(1, (cols - len(hint)) // 2)
        hint_ansi = f"\033[{rows};1H\033[2K\033[{rows};{hint_col}H\033[2m{hint}\033[0m"
        tty_out.write(hint_ansi)
        tty_out.flush()

    old_settings = termios.tcgetattr(tty_fd)
    try:
        tty.setraw(tty_fd)

        while True:
            t0 = time.monotonic()
            game_tick += 1

            # Spawn lemmings — round-robin across entrances (after entrance opens)
            ENTRANCE_OPEN_TICK = 60  # delay + animation time
            if (selected is None and spawned < MAX_LEMMINGS
                    and game_tick > ENTRANCE_OPEN_TICK
                    and game_tick % SPAWN_INTERVAL == 0):
                ent = entrances[spawned % len(entrances)]
                misch = random.random() < 0.25
                auto_bomb = random.randint(20 * 22, 120 * 22)
                if misch:
                    abs_list = None
                    tgt = random.choice(text_pixel_coords) if text_pixel_coords else None
                else:
                    abs_list = []
                    for _ in range(2):
                        if pool:
                            abs_list.append(pool.pop())
                    tgt = None
                lemmings.append(Lemming(
                    ent["spawn_x"], ent["spawn_y"], world,
                    abilities=abs_list, mischievous=misch,
                    target_xy=tgt, exit_xy=exit_center,
                    auto_bomb_tick=auto_bomb,
                ))
                spawned += 1

            # Non-blocking input from /dev/tty
            flags = fcntl.fcntl(tty_fd, fcntl.F_GETFL)
            fcntl.fcntl(tty_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                buf = os.read(tty_fd, 32)
            except OSError:
                buf = b''
            fcntl.fcntl(tty_fd, fcntl.F_SETFL, flags)
            if buf:
                i = 0
                while i < len(buf):
                    if buf[i:i + 3] == b'\x1b[D':
                        cam_offset -= 40; i += 3
                    elif buf[i:i + 3] == b'\x1b[C':
                        cam_offset += 40; i += 3
                    elif buf[i:i + 1] == b'\x1b' and i + 1 == len(buf):
                        quit_no_selection = True; break
                    elif buf[i:i + 1] in (b'\x03', b'q'):
                        quit_no_selection = True; break
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

            if quit_no_selection:
                break

            # Update all lemmings
            for lem in lemmings:
                lem.update(exits, traps, water)

            # Viewport
            vx = max(0, min(menu_x + menu_w // 2 - view_pw // 2 + cam_offset,
                            LEVEL_WIDTH - view_pw))
            vy = 0
            vx_cell = vx // 2
            vy_cell = vy // 4

            out = []

            # Full redraw on scroll or first frame
            if vx != last_vx:
                for ty_b in range(th):
                    out.append(f"\033[{ty_b + 1};1H")
                    for tx_b in range(tw):
                        stx = vx_cell + tx_b
                        sty = vy_cell + ty_b
                        if 0 <= stx < level_tw and 0 <= sty < level_th:
                            c = world.braille[sty][stx]
                            out.append(c if c else " ")
                        else:
                            out.append(" ")
                last_vx = vx
                prev_dirty = []
            else:
                for cx, cy, ansi in prev_dirty:
                    out.append(f"\033[{cy + 1};{cx + 1}H{ansi}")

            # Stamp animated objects then lemmings
            new_dirty = []
            obj_overlay = stamp_objects(world, game_tick, palette, menu_rect)
            visible_lems = [l for l in lemmings if not l.dead and not l.exited]
            lem_overlay = stamp_lemmings(visible_lems) if visible_lems else {}
            # Merge: lemmings draw on top of objects
            overlay = obj_overlay
            overlay.update(lem_overlay)

            if overlay:
                dirty_cells = set()
                for (px, py) in overlay:
                    cx = (px - vx) // 2
                    cy = (py - vy) // 4
                    if 0 <= cx < tw and 0 <= cy < th:
                        dirty_cells.add((cx, cy))

                for cx, cy in dirty_cells:
                    wpx = vx + cx * 2
                    wpy = vy + cy * 4
                    stx = vx_cell + cx
                    sty = vy_cell + cy
                    terrain_ansi = (world.braille[sty][stx]
                                    if 0 <= stx < level_tw and 0 <= sty < level_th
                                    else " ")
                    terrain_ansi = terrain_ansi or " "

                    composited = braille_cell_fast(world.canvas, overlay, wpx, wpy)
                    out.append(f"\033[{cy + 1};{cx + 1}H{composited}")
                    new_dirty.append((cx, cy, terrain_ansi))

            prev_dirty = new_dirty

            alive_count = len([l for l in lemmings if not l.dead and not l.exited])

            tty_out.write("".join(out))
            tty_out.flush()

            # Redraw hint bar every frame (dirty-cell updates may overwrite it)
            if standalone:
                tty_out.write(hint_ansi)
                tty_out.flush()

            # Exit after all lemmings are done exploding
            if selected is not None and alive_count == 0:
                time.sleep(0.5)
                break

            elapsed = time.monotonic() - t0
            time.sleep(max(0, 1.0 / tps - elapsed))

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_settings)
        tty_out.write("\033[?1049l\033[?25h\033[0m")
        tty_out.flush()
        tty_out.close()

    return selected_path


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    config = load_config()
    if not config:
        try:
            with open("/dev/tty", "w") as t:
                t.write("braillings: config file is empty. Add entries or delete it for standalone mode.\n")
        except OSError:
            pass
        return None

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
            ao["play_once"] = True  # play opening anim then hold last frame
            ao["started_tick"] = 0

    # Use first entrance for menu placement and walk surface
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

    text_pixels, menu_rect = stamp_menu(world, config, entrances[0]["x"], walk_surface_y, water, _term_cols)
    text_pixel_coords = list(text_pixels)
    world.pre_render_braille()

    pool = build_ability_pool(header["skills"])

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    try:
        selected_path = game_loop(
            world, exits, traps, water, exit_center, entrances,
            pool, text_pixel_coords, config, header, tty_fd, palette, menu_rect)
    finally:
        os.close(tty_fd)

    if selected_path:
        print(os.path.expanduser(selected_path), end='', flush=True)

    return selected_path


if __name__ == "__main__":
    main()
