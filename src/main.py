"""
ArduinoPong – MicroPython port
================================
Original C++ source: src/main.cpp  (TI-84 CE / graphx + keypadc)
Ported to:          MicroPython + SSD1306 OLED (128×64)

Graphics
--------
All drawing is done through the MicroPython ssd1306 library.
The display is assumed to be a 128×64 I²C OLED wired to I2C bus 0
(SCL = Pin 22, SDA = Pin 21 – adjust SCL_PIN / SDA_PIN below to match
your hardware).

Input / controls
----------------
Player movement is provided as a single JSON object delivered per frame
on sys.stdin (e.g. over a USB-serial / UART link).  One JSON line is
consumed per game-loop iteration; if no data is available the previous
movement state is kept.

Accepted JSON keys
  start   – "single" | "multi" | "quit"   (splash screen only)
  player1 – "up" | "down" | "none"         (left paddle)
  player2 – "up" | "down" | "none"         (right paddle)
  quit    – true                           (exit during play)

Example frame inputs
  {"player1": "up",   "player2": "down"}
  {"player1": "none", "player2": "up"}
  {"quit": true}
"""

import json
import math
import random
import sys
import time

import ssd1306
from machine import I2C, Pin

# ---------------------------------------------------------------------------
# Hardware / display constants  –  adjust to match your board
# ---------------------------------------------------------------------------
SCL_PIN = 22
SDA_PIN = 21
LCD_WIDTH = 128
LCD_HEIGHT = 64

i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN))
oled = ssd1306.SSD1306_I2C(LCD_WIDTH, LCD_HEIGHT, i2c)

# ---------------------------------------------------------------------------
# Paddle geometry constants  (scaled from 320×240 → 128×64)
# ---------------------------------------------------------------------------
PADDLE_WIDTH = 4
PADDLE_HEIGHT = 14
PADDLE_BORDER = PADDLE_WIDTH // 2 + 3   # x-offset from screen edge
PADDLE_SPEED = 80                        # pixels / second (manual)
PADDLE_AUTO_SPEED = 55                   # pixels / second (AI)

# ---------------------------------------------------------------------------
# Puck constants
# ---------------------------------------------------------------------------
PUCK_START_SPEED = 40    # pixels / second after reset
PUCK_PLAY_SPEED = 120    # pixels / second after paddle hit
PUCK_RADIUS = 2

# Extra vertical tolerance added to each side of the paddle when checking
# whether the puck is "between" a paddle (prevents the ball tunnelling
# through at shallow angles).
COLLISION_TOLERANCE = 3

# How long the mode-selection loop sleeps between stdin polls (ms).
INPUT_POLL_INTERVAL_MS = 50


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _sign(val):
    """Return +1, -1, or 0 for the sign of *val*."""
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0


def _fill_rect_centered(x, y, w, h, color=1):
    """Draw a filled rectangle centred on (x, y) with size (w, h)."""
    ox = int(x - w / 2)
    oy = int(y - h / 2)
    # Clamp to display bounds
    x0 = max(0, ox)
    y0 = max(0, oy)
    rw = min(int(w), LCD_WIDTH - x0)
    rh = min(int(h), LCD_HEIGHT - y0)
    if rw > 0 and rh > 0:
        oled.fill_rect(x0, y0, rw, rh, color)


def _fill_circle(cx, cy, r, color=1):
    """Draw a filled circle at integer (cx, cy) with radius *r*."""
    cx, cy, r = int(cx), int(cy), int(r)
    for dy in range(-r, r + 1):
        dx = int(math.sqrt(max(0, r * r - dy * dy)))
        ry = cy + dy
        if 0 <= ry < LCD_HEIGHT:
            rx = max(0, cx - dx)
            rw = min(LCD_WIDTH - rx, dx * 2 + 1)
            if rw > 0:
                oled.fill_rect(rx, ry, rw, 1, color)


def _random_puck_velocity():
    """
    Return a random (vx, vy) launch direction for the puck after a reset.

    *vy* is uniform in [-1, 1].  *vx* is scaled by a random factor in
    [1, 4] and given a random horizontal sign, ensuring the ball always
    launches at a noticeable angle.  The returned vector is subsequently
    normalised to PUCK_START_SPEED by the caller.
    """
    vy = random.uniform(-1.0, 1.0)
    vx = (random.random() * 3.0 + 1.0) * abs(vy) * _sign(random.uniform(-1.0, 1.0))
    return vx, vy


def _read_json():
    """
    Try to read one JSON line from stdin without blocking.
    Returns a dict, or {} when no data is ready.
    """
    try:
        import select
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return {}
    except (ImportError, OSError):
        pass
    try:
        line = sys.stdin.readline()
        if line:
            return json.loads(line.strip())
    except (ValueError, OSError):
        pass
    return {}


# ---------------------------------------------------------------------------
# Vector  (mirrors the C++ struct)
# ---------------------------------------------------------------------------

class Vector:
    """2-D vector with magnitude / angle helpers."""

    __slots__ = ("x", "y", "magnitude", "angle")

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)
        self.magnitude = 0.0
        self.angle = 0.0
        self._recalc()

    # -- internal ----------------------------------------------------------

    def _recalc(self):
        self.magnitude = math.sqrt(self.x * self.x + self.y * self.y)
        self.angle = math.atan2(self.y, self.x) if self.magnitude else 0.0

    # -- mutators ----------------------------------------------------------

    def set(self, x, y):
        self.x, self.y = float(x), float(y)
        self._recalc()
        return self

    def set_magnitude(self, mag):
        """Scale the vector so its length equals *mag*."""
        if self.magnitude:
            scale = float(mag) / self.magnitude
            self.x *= scale
            self.y *= scale
        self.magnitude = float(mag)
        return self

    def set_angle(self, angle):
        """Rotate the vector to *angle* radians (keeping current magnitude)."""
        self.x = self.magnitude * math.cos(angle)
        self.y = self.magnitude * math.sin(angle)
        self.angle = float(angle)
        return self

    # -- operators ---------------------------------------------------------

    def __iadd__(self, other):
        self.x += other.x
        self.y += other.y
        self._recalc()
        return self

    def __mul__(self, scalar):
        return Vector(self.x * scalar, self.y * scalar)


# ---------------------------------------------------------------------------
# Paddle
# ---------------------------------------------------------------------------

class Paddle:
    """A player-controlled (or AI-controlled) paddle."""

    def __init__(self, x):
        self.position = Vector(x, LCD_HEIGHT / 2)
        self.speed = PADDLE_SPEED
        self.score = 0
        self.is_auto = False   # True → AI drives this paddle
        self._up = False
        self._down = False

    def set_input(self, up: bool, down: bool):
        """
        Apply JSON-sourced directional input for this frame.

        *up* and *down* are expected to be the result of boolean expressions
        (e.g. ``p1 == "up"``), not raw strings.  Both may be False to
        indicate no movement.
        """
        self._up = up
        self._down = down

    def update(self, dt, puck):
        if self.is_auto:
            self.speed = PADDLE_AUTO_SPEED
            # Track the puck only when it is heading toward this paddle.
            # When _sign() returns 0 (puck moving purely vertically) or the
            # signs differ (puck moving away), the paddle holds its position.
            if _sign(self.position.x - puck.position.x) == _sign(puck.velocity.x):
                diff = puck.position.y - self.position.y
                if diff < -self.speed * dt:
                    self.position.y -= self.speed * dt
                elif diff > self.speed * dt:
                    self.position.y += self.speed * dt
        else:
            direction = -1 if self._up else (1 if self._down else 0)
            self.position.y += self.speed * dt * direction

        # Clamp to vertical display bounds
        half_h = PADDLE_HEIGHT / 2
        self.position.y = max(half_h, min(LCD_HEIGHT - half_h, self.position.y))

    def show(self):
        _fill_rect_centered(self.position.x, self.position.y,
                            PADDLE_WIDTH, PADDLE_HEIGHT)


# ---------------------------------------------------------------------------
# Puck
# ---------------------------------------------------------------------------

class Puck:
    """The ball – handles movement, bouncing, collision, and scoring."""

    def __init__(self, left: Paddle, right: Paddle):
        self.position = Vector()
        self.velocity = Vector()
        self.left = left
        self.right = right
        self.reset(0)

    # -- public API --------------------------------------------------------

    def reset(self, state: int):
        """
        Award a point then re-centre the puck.
        state > 0 → right paddle scores; state < 0 → left paddle scores.
        """
        if state > 0:
            self.right.score += 1
        elif state < 0:
            self.left.score += 1

        self.position.set(LCD_WIDTH / 2, LCD_HEIGHT / 2)
        self.velocity.set(*_random_puck_velocity())
        self.velocity.set_magnitude(PUCK_START_SPEED)

    def update(self, dt: float):
        self.position += self.velocity * dt
        self._collide()
        self._bounce()
        self._score()

    def show(self):
        _fill_circle(self.position.x, self.position.y, PUCK_RADIUS)

    # -- private -----------------------------------------------------------

    def _score(self):
        """Detect when the puck leaves the play area and award a point."""
        if self.position.x > LCD_WIDTH + PUCK_RADIUS:
            self.reset(-1)   # left paddle scores
        elif self.position.x < -PUCK_RADIUS:
            self.reset(1)    # right paddle scores

    def _bounce(self):
        """Reflect off the top / bottom walls."""
        if (self.position.y < PUCK_RADIUS or
                self.position.y > LCD_HEIGHT - PUCK_RADIUS):
            self.velocity.y *= -1
            self.velocity._recalc()

    def _collide(self):
        """Deflect off either paddle using an angle-based reflection."""
        half_w = PADDLE_WIDTH / 2
        half_h = PADDLE_HEIGHT / 2

        on_left = self.position.x - PUCK_RADIUS < self.left.position.x + half_w
        on_right = self.position.x + PUCK_RADIUS > self.right.position.x - half_w

        if on_left and self._between_paddle(self.left.position):
            angle = ((self.position.y - (self.left.position.y - half_h))
                     / PADDLE_HEIGHT * math.pi / 2 - math.pi / 4)
            self.velocity.set_angle(angle)
            self.velocity.set_magnitude(PUCK_PLAY_SPEED)

        if on_right and self._between_paddle(self.right.position):
            angle = ((self.position.y - (self.right.position.y - half_h))
                     / PADDLE_HEIGHT * math.pi / 2 - math.pi / 4)
            self.velocity.set_angle(angle)
            self.velocity.x *= -1           # flip to move left
            self.velocity.set_magnitude(PUCK_PLAY_SPEED)

    def _between_paddle(self, paddle_pos) -> bool:
        """Return True when the puck's y-range overlaps *paddle_pos*."""
        half_h = PADDLE_HEIGHT / 2
        return (self.position.y + PUCK_RADIUS + COLLISION_TOLERANCE > paddle_pos.y - half_h and
                self.position.y - PUCK_RADIUS - COLLISION_TOLERANCE < paddle_pos.y + half_h)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_center_line():
    """Dashed vertical centre line."""
    y = 3
    while y < LCD_HEIGHT - 2:
        _fill_rect_centered(LCD_WIDTH / 2, y, 2, 2)
        y += 4


def _show_splash():
    """Title / mode-selection screen."""
    oled.fill(0)
    oled.text("ArduinoPong", 18, 2, 1)
    oled.text("L:Single  R:Multi", 0, 16, 1)
    oled.text("Up/Down = Move", 0, 28, 1)
    oled.text("q = Quit", 0, 40, 1)
    oled.text("By Warren James", 0, 54, 1)
    oled.show()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    _show_splash()

    left = Paddle(PADDLE_BORDER)
    right = Paddle(LCD_WIDTH - PADDLE_BORDER)
    puck = Puck(left, right)

    # ---- Mode selection ------------------------------------------------
    # Block until a valid start command arrives as JSON on stdin.
    # Example: {"start": "single"}  or  {"start": "multi"}
    while True:
        data = _read_json()
        start = data.get("start", "")
        if start == "single":
            left.is_auto = True
            break
        elif start == "multi":
            break
        elif start == "quit" or data.get("quit"):
            oled.fill(0)
            oled.show()
            return
        time.sleep_ms(INPUT_POLL_INTERVAL_MS)

    # ---- Game loop -----------------------------------------------------
    last_ms = time.ticks_ms()

    while True:
        now_ms = time.ticks_ms()
        dt = time.ticks_diff(now_ms, last_ms) / 1000.0
        last_ms = now_ms

        # Input – one JSON object per frame, e.g.:
        #   {"player1": "up", "player2": "down"}
        data = _read_json()

        if data.get("quit"):
            break

        p1 = data.get("player1", "none")
        left.set_input(p1 == "up", p1 == "down")

        p2 = data.get("player2", "none")
        right.set_input(p2 == "up", p2 == "down")

        # Update game state
        left.update(dt, puck)
        right.update(dt, puck)
        puck.update(dt)

        # Render
        oled.fill(0)
        _draw_center_line()
        left.show()
        right.show()
        puck.show()

        # Scores – left score left of centre, right score right of centre
        oled.text(str(left.score), LCD_WIDTH // 2 - 12, 2, 1)
        oled.text(str(right.score), LCD_WIDTH // 2 + 6, 2, 1)

        oled.show()

    oled.fill(0)
    oled.show()


main()
