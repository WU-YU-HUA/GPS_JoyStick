"""Shared keyboard, mouse-direction, and lock state for both renderers."""

KEY_DIRECTIONS = {
    "w": (0, 1),
    "a": (-1, 0),
    "s": (0, -1),
    "d": (1, 0),
    "up": (0, 1),
    "left": (-1, 0),
    "down": (0, -1),
    "right": (1, 0),
}


class MovementController:
    """Convert normalized input events into one east/north direction."""

    def __init__(self):
        self.pressed_keys = set()
        self.mouse_direction = None
        self.locked_direction = None

    def key_down(self, key):
        key = str(key).lower()
        if key not in KEY_DIRECTIONS:
            return False
        self.locked_direction = None
        self.mouse_direction = None
        self.pressed_keys.add(key)
        return True

    def key_up(self, key):
        self.pressed_keys.discard(str(key).lower())

    def begin_mouse_direction(self, direction):
        self.pressed_keys.clear()
        self.locked_direction = None
        self.mouse_direction = tuple(direction)

    def release_mouse_direction(self):
        self.mouse_direction = None

    def lock_direction(self, east, north):
        self.pressed_keys.clear()
        self.mouse_direction = None
        self.locked_direction = (east, north)

    def release_keys(self):
        """Release physical keys while preserving an intentional direction lock."""
        self.pressed_keys.clear()

    def stop(self):
        self.pressed_keys.clear()
        self.mouse_direction = None
        self.locked_direction = None

    def current_direction(self):
        east = int(any(KEY_DIRECTIONS[key][0] > 0 for key in self.pressed_keys)) - int(
            any(KEY_DIRECTIONS[key][0] < 0 for key in self.pressed_keys)
        )
        north = int(any(KEY_DIRECTIONS[key][1] > 0 for key in self.pressed_keys)) - int(
            any(KEY_DIRECTIONS[key][1] < 0 for key in self.pressed_keys)
        )
        if self.mouse_direction:
            east = max(-1, min(1, east + self.mouse_direction[0]))
            north = max(-1, min(1, north + self.mouse_direction[1]))
        if self.locked_direction is not None:
            return self.locked_direction
        return east, north
