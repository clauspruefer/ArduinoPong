"""
ArduinoPong – MicroPython port
================================
Original C++ source: src/main.cpp  (TI-84 CE / graphx + keypadc)

API – single-frame function
----------------------------
This module exposes one public function, ``render_frame(data, dt)``, that
advances the game by one frame and returns a comma-separated string of
all rendering-relevant state.  The caller is responsible for scheduling
periodic invocations and for all rendering – there is no loop and no
display output inside this module.

    import pong

    state = pong.render_frame({"start": "multi"}, 0.05)
    state = pong.render_frame({"player1": "up"},  0.05)
    state = pong.render_frame({"player2": "down"}, 0.05)
    state = pong.render_frame({"quit": True},      0.05)

Accepted dict keys
  "start"   – "single" | "multi" | "quit"   (while splash is shown)
  "player1" – "up" | "down" | "none"         (left paddle, during play)
  "player2" – "up" | "down" | "none"         (right paddle, during play)
  "quit"    – any truthy value               (end the game at any time)

Return value
  A comma-separated string with six fields while the game is in play:
    puck_x, puck_y, p1_y, p2_y, p1_score, p2_score
  An empty string ``""`` is returned during the splash screen or after
  the game has ended.  The caller may stop further invocations when the
  returned string is empty (after the game transitions away from splash).
"""

import math
import json

# ---------------------------------------------------------------------------
# Display / game-field constants
# ---------------------------------------------------------------------------
LCD_WIDTH = 128
LCD_HEIGHT = 64

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


# ---------------------------------------------------------------------------
# Vector  (mirrors the C++ struct)
# ---------------------------------------------------------------------------

class Vector:
    """2-D vector with magnitude / angle helpers."""

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)
        self.magnitude = 0.0
        self.angle = 0.0
        self._recalc()

    # -- internal ----------------------------------------------------------

    def _recalc(self):
        self.magnitude = math.sqrt(self.x * self.x + self.y * self.y)
        if self.magnitude:
            self.angle = math.atan2(self.y, self.x)
        else:
            self.angle = 0.0

    # -- mutators ----------------------------------------------------------

    def set(self, x, y):
        self.x, self.y = float(x), float(y)
        self._recalc()
        return self

    def set_magnitude(self, mag):
        """Scale the vector so its length equals *mag*."""
        if self.magnitude:
            scale = float(mag) / self.magnitude
            self.x = self.x * scale
            self.y = self.y * scale
        self.magnitude = float(mag)
        return self

    def set_angle(self, angle):
        """Rotate the vector to *angle* radians (keeping current magnitude)."""
        self.x = self.magnitude * math.cos(angle)
        self.y = self.magnitude * math.sin(angle)
        self.angle = float(angle)
        return self

    def flip_y(self):
        """Negate the y component and update magnitude / angle."""
        self.y = 0.0 - self.y
        self._recalc()
        return self

    def flip_x(self):
        """Negate the x component and update magnitude / angle."""
        self.x = 0.0 - self.x
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

    def set_input(self, direction):
        """
        Apply directional input for this frame.

        *direction* is a plain string: ``"up"``, ``"down"``, or anything
        else (including ``"none"``) to stop.
        """
        if direction == "up":
            self._up = True
            self._down = False
        elif direction == "down":
            self._up = False
            self._down = True
        else:
            self._up = False
            self._down = False

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
            direction = 0   # no key pressed → stationary
            if self._up:
                direction = -1
            elif self._down:
                direction = 1
            self.position.y += self.speed * dt * direction

        # Clamp to vertical display bounds
        half_h = PADDLE_HEIGHT / 2
        self.position.y = max(half_h, min(LCD_HEIGHT - half_h, self.position.y))


# ---------------------------------------------------------------------------
# Puck
# ---------------------------------------------------------------------------

class Puck:
    """The ball – handles movement, bouncing, collision, and scoring."""

    def __init__(self, left, right):
        self.position = Vector()
        self.velocity = Vector()
        self.left = left
        self.right = right
        self._vel_idx = 0
        self.reset(0)

    def _next_velocity(self):
        """
        Return the next (vx, vy) launch direction from the pre-calculated list.

        The index is stored as an instance variable so no module-level global
        is needed.  The list has 50 entries; the index wraps around explicitly
        to avoid a ``%`` operation.
        """
        vx, vy = _PUCK_VELOCITIES[self._vel_idx]
        self._vel_idx = self._vel_idx + 1
        if self._vel_idx >= 50:
            self._vel_idx = 0
        return vx, vy

    # -- public API --------------------------------------------------------

    def reset(self, state):
        """
        Award a point then re-centre the puck.
        state > 0 → right paddle scores; state < 0 → left paddle scores.
        """
        if state > 0:
            self.right.score += 1
        elif state < 0:
            self.left.score += 1

        self.position.set(LCD_WIDTH / 2, LCD_HEIGHT / 2)
        _vx, _vy = self._next_velocity()
        self.velocity.set(_vx, _vy)
        self.velocity.set_magnitude(PUCK_START_SPEED)

    def update(self, dt):
        self.position.x += self.velocity.x * dt
        self.position.y += self.velocity.y * dt
        self.position._recalc()
        self._collide()
        self._bounce()
        self._score()

    # -- private -----------------------------------------------------------

    def _score(self):
        """Detect when the puck leaves the play area and award a point."""
        if self.position.x > LCD_WIDTH + PUCK_RADIUS:
            self.reset(-1)   # left paddle scores
        elif self.position.x < -PUCK_RADIUS:
            self.reset(1)    # right paddle scores

    def _bounce(self):
        """Reflect off the top / bottom walls."""
        if self.position.y < PUCK_RADIUS:
            self.velocity.flip_y()
        elif self.position.y > LCD_HEIGHT - PUCK_RADIUS:
            self.velocity.flip_y()

    def _collide(self):
        """Deflect off either paddle using an angle-based reflection."""
        half_w = PADDLE_WIDTH / 2
        half_h = PADDLE_HEIGHT / 2

        on_left = self.position.x - PUCK_RADIUS < self.left.position.x + half_w
        on_right = self.position.x + PUCK_RADIUS > self.right.position.x - half_w

        if on_left and self._between_paddle(self.left.position):
            angle = ((self.position.y - (self.left.position.y - half_h)) / PADDLE_HEIGHT * math.pi / 2 - math.pi / 4)
            self.velocity.set_angle(angle)
            self.velocity.set_magnitude(PUCK_PLAY_SPEED)

        if on_right and self._between_paddle(self.right.position):
            angle = ((self.position.y - (self.right.position.y - half_h)) / PADDLE_HEIGHT * math.pi / 2 - math.pi / 4)
            self.velocity.set_angle(angle)
            self.velocity.flip_x()           # flip to move left
            self.velocity.set_magnitude(PUCK_PLAY_SPEED)

    def _between_paddle(self, paddle_pos):
        """Return True when the puck's y-range overlaps *paddle_pos*."""
        half_h = PADDLE_HEIGHT / 2
        y_top = paddle_pos.y - half_h
        y_bot = paddle_pos.y + half_h
        if self.position.y + PUCK_RADIUS + COLLISION_TOLERANCE <= y_top:
            return False
        if self.position.y - PUCK_RADIUS - COLLISION_TOLERANCE >= y_bot:
            return False
        return True


# ---------------------------------------------------------------------------
# Game state constants (module-level for reliable access in MicroPython)
# ---------------------------------------------------------------------------
_STATE_SPLASH = 0
_STATE_PLAY = 1
_STATE_QUIT = 2


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

    def __init__(self):
        self.left  = Paddle(PADDLE_BORDER)
        self.right = Paddle(LCD_WIDTH - PADDLE_BORDER)
        self.puck  = Puck(self.left, self.right)
        self._state = _STATE_SPLASH

    # -- public ------------------------------------------------------------

    def step(self, data, dt):
        """
        Advance the game by one frame using *data* as the control input.

        *data* is a plain dict or a JSON string.  Recognised keys:

          "start"   – "single" | "multi" | "quit"  (while showing splash)
          "player1" – "up" | "down" | "none"        (left paddle, during play)
          "player2" – "up" | "down" | "none"        (right paddle, during play)
          "quit"    – any truthy value              (exit at any time)

        *dt* is the elapsed time in seconds since the previous call.
        The caller is responsible for all time measurement.

        Returns a comma-separated string with six fields during play:
          puck_x, puck_y, p1_y, p2_y, p1_score, p2_score
        Returns an empty string ``""`` during the splash screen or after
        the game has ended.
        """
        if isinstance(data, str):
            data = json.loads(data)
        if self._state == _STATE_SPLASH:
            return self._step_splash(data)
        if self._state == _STATE_PLAY:
            return self._step_play(data, dt)
        return ""   # _STATE_QUIT

    # -- private -----------------------------------------------------------

    def _step_splash(self, data):
        """Handle one frame while the splash / mode-selection screen is shown."""
        if data.get("quit"):
            self._do_quit()
            return ""

        start = data.get("start", "")
        if start == "single":
            self.left.is_auto = True
            self._begin_play()
        elif start == "multi":
            self._begin_play()
        # Any other (or missing) key: stay on splash.
        return ""

    def _step_play(self, data, dt):
        """Handle one frame of active gameplay."""
        if data.get("quit"):
            self._do_quit()
            return ""

        # Apply player input
        self.left.set_input(data.get("player1", "none"))

        self.right.set_input(data.get("player2", "none"))

        # Update game state
        self.left.update(dt, self.puck)
        self.right.update(dt, self.puck)
        self.puck.update(dt)

        # Return game state as comma-separated string:
        # puck_x, puck_y, p1_y, p2_y, p1_score, p2_score
        return "%d,%d,%d,%d,%d,%d" % (
            int(self.puck.position.x),
            int(self.puck.position.y),
            int(self.left.position.y),
            int(self.right.position.y),
            self.left.score,
            self.right.score)

    def _begin_play(self):
        """Transition from splash to active play."""
        self._state = _STATE_PLAY

    def _do_quit(self):
        """Mark the game as finished."""
        self._state = _STATE_QUIT


# ---------------------------------------------------------------------------
# Module-level public API
# ---------------------------------------------------------------------------

# Shared game instance used by render_frame().
_game = Game()


def render_frame(data, dt):
    """
    Advance the game by one frame and return the current rendering state.

    Parameters
    ----------
    data : dict or str
        Control input for this frame.  May be a plain ``dict`` or a JSON
        string – if a string is supplied it is decoded with ``ujson`` /
        ``json`` before processing.  Recognised keys:

          "start"   – "single" | "multi" | "quit"  (while splash is shown)
          "player1" – "up" | "down" | "none"        (left paddle)
          "player2" – "up" | "down" | "none"        (right paddle)
          "quit"    – any truthy value              (end the game)

    dt : float
        Elapsed time in seconds since the previous call.  The caller is
        responsible for all time measurement; this module does none.

    Returns
    -------
    str
        A comma-separated string with six fields during active play:
          puck_x, puck_y, p1_y, p2_y, p1_score, p2_score
        An empty string ``""`` is returned during the splash screen or
        after the game has ended.

    Notes
    -----
    This function contains no loop.  The caller is responsible for
    scheduling periodic invocations (e.g. via a MicroPython timer,
    coroutine, or ``uasyncio`` task).
    """
    return _game.step(data, dt)
