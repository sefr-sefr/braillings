# Fix Plan

## Blocker: no ground-loss check
**File:** braillings.py, `_block` state (line ~386)
**Behavior:** If terrain under a blocker is destroyed (dig, mine, bash, explosion), the blocker keeps blocking while visually floating. In the OG game, `HandleBlocking` detects no solid pixel at the foot position and transitions the blocker to walking, which also removes the force field.
**Expected:** Blocker should check `is_solid(self.x, self.y)` each tick. If ground is gone, transition to fall state.
**Impact:** Visual — blocker floats. Force field still works (position-based), so gameplay is unaffected. Low priority.
