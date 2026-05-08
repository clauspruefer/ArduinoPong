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

The ball is drawn as a filled square (side = PUCK_RADIUS * 2) rather
than a circle for simplicity and speed on constrained hardware.

API – single-frame function
----------------------------
This module exposes one public function, ``render_frame(data)``, that
renders exactly one frame of the game.  The caller (a timer callback,
a coroutine, or any other MicroPython scheduler) is responsible for
calling it periodically – there is no loop inside this module.

    import pong          # name your copy of this module as you like

    # Each call advances the game by one frame:
    pong.render_frame({"start": "multi"})     # transition splash → play
    pong.render_frame({"player1": "up"})      # move left paddle up
    pong.render_frame({"player2": "down"})    # move right paddle down
    pong.render_frame({"quit": True})         # end the game

Accepted dict keys
  "start"   – "single" | "multi" | "quit"   (while splash is shown)
  "player1" – "up" | "down" | "none"         (left paddle, during play)
  "player2" – "up" | "down" | "none"         (right paddle, during play)
  "quit"    – any truthy value               (end the game at any time)

``render_frame(data, dt)`` returns True while the game is running and
False once it has ended; the caller may stop further invocations at that
point.  *dt* is the elapsed time in seconds since the previous call
(e.g. 0.05 for a 20 Hz driver loop) – the module performs no time
measurement of its own.

Output mode flags (set at the top of this file)
-------------------------------------------------
Two independent boolean flags control where the game renders:

``OLED_OUTPUT`` (default ``True``)
    Render each frame to the physical SSD1306 OLED.  Set to ``False`` when
    running on a host PC / in an emulator / without hardware attached.  When
    disabled the ``ssd1306`` and ``machine`` imports are skipped entirely.

``ASCII_DEBUG`` (default ``False``)
    Print a scaled ASCII representation of each frame to stdout.  Set to
    ``True`` to debug over a serial / REPL connection.

The two flags are fully independent; any combination is valid:

    OLED_OUTPUT = True,  ASCII_DEBUG = False  →  OLED only   (default)
    OLED_OUTPUT = False, ASCII_DEBUG = True   →  ASCII only
    OLED_OUTPUT = True,  ASCII_DEBUG = True   →  OLED + ASCII
    OLED_OUTPUT = False, ASCII_DEBUG = False  →  headless / no output
"""

import math
import sys

# ---------------------------------------------------------------------------
# Output mode flags  –  adjust these before deploying
# ---------------------------------------------------------------------------
# Render to the physical SSD1306 OLED (requires ssd1306 + machine).
OLED_OUTPUT = True

# Print an ASCII frame to stdout each tick (useful without hardware).
ASCII_DEBUG = False

# ---------------------------------------------------------------------------
# Hardware / display constants  –  adjust to match your board
# ---------------------------------------------------------------------------

if OLED_OUTPUT:
    import ssd1306
    from machine import I2C, Pin
    SCL_PIN = 22
    SDA_PIN = 21
LCD_WIDTH = 128
LCD_HEIGHT = 64

if OLED_OUTPUT:
    i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN))
    oled = ssd1306.SSD1306_I2C(LCD_WIDTH, LCD_HEIGHT, i2c)
else:
    oled = None

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

# Maximum physics time-step accepted by _step_play().  Any dt larger than
# this is silently clamped so the puck cannot jump across the whole display
# in one frame.  At PUCK_PLAY_SPEED = 120 px/s the puck travels at most
# 120 × 0.05 = 6 px per step, which keeps collision detection reliable.
MAX_DT = 0.05            # seconds (~20 FPS floor)

# Extra vertical tolerance added to each side of the paddle when checking
# whether the puck is "between" a paddle (prevents the ball tunnelling
# through at shallow angles).
COLLISION_TOLERANCE = 3


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
        if OLED_OUTPUT:
            oled.fill_rect(x0, y0, rw, rh, color)


def _random_puck_velocity():
    """
    Return the next (vx, vy) launch direction for the puck after a reset.

    Instead of runtime random calls, the function cycles through a fixed
    list of 50 pre-calculated velocity pairs.  This removes the dependency
    on the ``random`` module entirely, which saves RAM and avoids the cost
    of seeding an RNG on resource-constrained embedded targets.

    The values were generated offline with the same formula that was used
    previously (vy ∈ [-1, 1], vx scaled by a factor in [1, 4] with an
    alternating sign) so the launch directions are well-distributed.
    """
    global _PUCK_VEL_IDX
    vx, vy = _PUCK_VELOCITIES[_PUCK_VEL_IDX % len(_PUCK_VELOCITIES)]
    _PUCK_VEL_IDX += 1
    return vx, vy


# Pre-calculated launch velocities – 50 entries, generated offline.
# Each tuple is (vx, vy); the caller normalises the speed afterwards.
_PUCK_VELOCITIES = [
    ( 0.299777,  0.278854),
    (-0.723800, -0.510216),
    (-1.299285,  0.353399),
    (-0.198242,  0.180985),
    (-1.415851, -0.562724),
    ( 0.385606,  0.122490),
    (-1.547527, -0.559119),
    ( 0.765541,  0.517615),
    ( 0.468526, -0.319499),
    ( 1.702367, -0.795579),
    (-1.953737,  0.694989),
    ( 1.198595,  0.459464),
    ( 1.583319, -0.842400),
    (-0.481705,  0.154704),
    (-1.070532,  0.322527),
    ( 2.557897,  0.710635),
    ( 1.290885, -0.444053),
    ( 1.393786, -0.674692),
    (-1.231363,  0.403641),
    (-0.330321,  0.218262),
    (-1.439538, -0.673195),
    (-1.302843,  0.369229),
    ( 0.594090, -0.541904),
    ( 0.236921, -0.197670),
    ( 1.435542, -0.574747),
    ( 1.013453, -0.714257),
    ( 1.129002,  0.494028),
    (-1.101814, -0.276007),
    (-0.024249,  0.019053),
    (-1.053354,  0.722206),
    (-1.323984,  0.584159),
    ( 0.642460, -0.230465),
    (-0.227863,  0.058229),
    ( 0.484477,  0.360567),
    ( 1.085422,  0.537197),
    ( 0.308061, -0.130469),
    (-3.101142,  0.943776),
    (-1.404513,  0.741037),
    (-2.282604, -0.694321),
    (-0.487959,  0.197889),
    ( 3.120547,  0.858197),
    (-0.897647, -0.521095),
    (-2.036904, -0.828693),
    (-2.483721,  0.955969),
    (-1.802931, -0.743217),
    ( 1.699721, -0.469887),
    (-3.516844,  0.928726),
    ( 0.935688,  0.425898),
    (-0.316027, -0.123800),
    (-0.601032, -0.504189),
]
_PUCK_VEL_IDX = 0


# ---------------------------------------------------------------------------
# ASCII debug renderer
# ---------------------------------------------------------------------------

# Dimensions of the ASCII frame in characters.
_ASCII_COLS = 64
_ASCII_ROWS = 16


def _debug_print_frame(left, right, puck):
    """
    Print a scaled-down ASCII art representation of the current game frame
    to stdout.

    Each character cell covers (LCD_WIDTH / _ASCII_COLS) × (LCD_HEIGHT /
    _ASCII_ROWS) pixels.  The output is prefixed with ANSI cursor-home so
    successive frames overwrite each other in a capable terminal emulator;
    on plain serial monitors each frame is simply appended.

    Symbols used
      |   paddle (left or right)
      o   ball
      :   centre-line dash (alternating rows)
      -   top / bottom border
      +   corner
    """
    def _to_col(px):
        return min(_ASCII_COLS - 1, max(0, int(px * _ASCII_COLS / LCD_WIDTH)))

    def _to_row(py):
        return min(_ASCII_ROWS - 1, max(0, int(py * _ASCII_ROWS / LCD_HEIGHT)))

    # Build blank grid
    grid = [[' '] * _ASCII_COLS for _ in range(_ASCII_ROWS)]

    # Centre dashed line
    cx = _ASCII_COLS // 2
    for r in range(_ASCII_ROWS):
        grid[r][cx] = ':' if r % 2 == 0 else ' '

    # Paddle height in ASCII rows (proportional)
    paddle_half = max(1, int(PADDLE_HEIGHT * _ASCII_ROWS / LCD_HEIGHT / 2))

    # Left paddle
    lx = _to_col(left.position.x)
    ly = _to_row(left.position.y)
    for r in range(max(0, ly - paddle_half), min(_ASCII_ROWS, ly + paddle_half + 1)):
        grid[r][lx] = '|'

    # Right paddle
    rx = _to_col(right.position.x)
    ry = _to_row(right.position.y)
    for r in range(max(0, ry - paddle_half), min(_ASCII_ROWS, ry + paddle_half + 1)):
        grid[r][rx] = '|'

    # Ball
    bx = _to_col(puck.position.x)
    by = _to_row(puck.position.y)
    grid[by][bx] = 'o'

    # Compose lines
    border = '+' + '-' * _ASCII_COLS + '+'
    # Left score is placed slightly left of centre; right score to the right.
    # _SCORE_INDENT shifts both numbers away from the midpoint so they sit
    # roughly above their respective halves of the field.
    _SCORE_INDENT = 4
    _SCORE_GAP = 7   # spaces between the two score numbers
    pad = _ASCII_COLS // 2 - _SCORE_INDENT
    score_line = (' ' * pad + str(left.score)
                  + ' ' * _SCORE_GAP
                  + str(right.score))
    rows = ['\x1b[H',  # ANSI cursor-home (ignored on plain serial)
            score_line,
            border]
    for row in grid:
        rows.append('|' + ''.join(row) + '|')
    rows.append(border)

    sys.stdout.write('\n'.join(rows) + '\n')


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

    def flip_y(self):
        """Negate the y component and update magnitude / angle."""
        self.y *= -1
        self._recalc()
        return self

    def flip_x(self):
        """Negate the x component and update magnitude / angle."""
        self.x *= -1
        self._recalc()
        return self


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
        """Draw the ball as a filled square (side = PUCK_RADIUS * 2)."""
        size = PUCK_RADIUS * 2
        _fill_rect_centered(self.position.x, self.position.y, size, size)

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
            self.velocity.flip_y()

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
            self.velocity.flip_x()           # flip to move left
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
    if OLED_OUTPUT:
        oled.fill(0)
        oled.text("ArduinoPong", 18, 2, 1)
        oled.text("L:Single  R:Multi", 0, 16, 1)
        oled.text("Up/Down = Move", 0, 28, 1)
        oled.text("q = Quit", 0, 40, 1)
        oled.text("By Warren James", 0, 54, 1)
        oled.show()


# ---------------------------------------------------------------------------
# Game – public API
# ---------------------------------------------------------------------------

class Game:
    """
    Holds all ArduinoPong game state (paddles, puck, scores).

    External code should normally use the module-level ``render_frame()``
    function rather than instantiating this class directly.  Direct
    instantiation is available for advanced use-cases such as running
    multiple independent game instances.
    """

    # Internal state constants
    _SPLASH = 0
    _PLAY   = 1
    _QUIT   = 2

    def __init__(self):
        self.left  = Paddle(PADDLE_BORDER)
        self.right = Paddle(LCD_WIDTH - PADDLE_BORDER)
        self.puck  = Puck(self.left, self.right)
        self._state = self._SPLASH

    # -- public ------------------------------------------------------------

    def show_splash(self):
        """Display the title / mode-selection screen on the OLED."""
        _show_splash()

    def step(self, data: dict, dt: float) -> bool:
        """
        Advance the game by one frame using *data* as the control input.

        *data* is a plain dict.  Recognised keys:

          "start"   – "single" | "multi" | "quit"  (while showing splash)
          "player1" – "up" | "down" | "none"        (left paddle, during play)
          "player2" – "up" | "down" | "none"        (right paddle, during play)
          "quit"    – any truthy value              (exit at any time)

        *dt* is the elapsed time in seconds since the previous call.
        The caller is responsible for all time measurement.

        Returns True while the game should keep running, False once it has
        ended (caller should stop issuing further ``step()`` calls).
        """
        if self._state == self._SPLASH:
            return self._step_splash(data)
        if self._state == self._PLAY:
            return self._step_play(data, dt)
        return False   # _QUIT

    # -- private -----------------------------------------------------------

    def _step_splash(self, data: dict) -> bool:
        """Handle one frame while the splash / mode-selection screen is shown."""
        if data.get("quit"):
            self._do_quit()
            return False

        start = data.get("start", "")
        if start == "single":
            self.left.is_auto = True
            self._begin_play()
        elif start == "multi":
            self._begin_play()
        # Any other (or missing) key: stay on splash, nothing to render.
        return True

    def _step_play(self, data: dict, dt: float) -> bool:
        """Handle one frame of active gameplay."""
        # Clamp dt so the puck cannot skip across the display in one step.
        dt = min(float(dt), MAX_DT)

        if data.get("quit"):
            self._do_quit()
            return False

        # Apply player input
        p1 = data.get("player1", "none")
        self.left.set_input(p1 == "up", p1 == "down")

        p2 = data.get("player2", "none")
        self.right.set_input(p2 == "up", p2 == "down")

        # Update game state
        self.left.update(dt, self.puck)
        self.right.update(dt, self.puck)
        self.puck.update(dt)

        # Render to OLED
        if OLED_OUTPUT:
            oled.fill(0)
            _draw_center_line()
            self.left.show()
            self.right.show()
            self.puck.show()
            # Scores: left score left of centre, right score right of centre
            oled.text(str(self.left.score),  LCD_WIDTH // 2 - 12, 2, 1)
            oled.text(str(self.right.score), LCD_WIDTH // 2 + 6,  2, 1)
            oled.show()

        # ASCII debug reads game-state directly; no show() calls needed here.
        if ASCII_DEBUG:
            _debug_print_frame(self.left, self.right, self.puck)

        return True

    def _begin_play(self):
        """Transition from splash to active play."""
        self._state = self._PLAY

    def _do_quit(self):
        """Clear the display and mark the game as finished."""
        if OLED_OUTPUT:
            oled.fill(0)
            oled.show()
        self._state = self._QUIT


# ---------------------------------------------------------------------------
# Module-level public API
# ---------------------------------------------------------------------------

# Shared game instance used by render_frame().
_game = Game()


def render_frame(data, dt):
    """
    Render exactly one frame of the game.

    Parameters
    ----------
    data : dict
        Control input for this frame.  Construct it from hardware button
        states, BLE packets, or any other source.  Recognised keys:

          "start"   – "single" | "multi" | "quit"  (while splash is shown)
          "player1" – "up" | "down" | "none"        (left paddle)
          "player2" – "up" | "down" | "none"        (right paddle)
          "quit"    – any truthy value              (end the game)

    dt : float
        Elapsed time in seconds since the previous call.  The caller is
        responsible for all time measurement; this module does none.

    Returns
    -------
    bool
        True while the game is running; False once the game has ended.
        The caller may stop issuing further calls when False is returned.

    Notes
    -----
    This function contains no loop.  The caller is responsible for
    scheduling periodic invocations (e.g. via a MicroPython timer,
    coroutine, or ``uasyncio`` task).
    """
    return _game.step(data, dt)
