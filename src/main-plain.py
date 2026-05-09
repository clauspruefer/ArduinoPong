import math
try:
    import ujson as json
except ImportError:
    import json

LCD_WIDTH = 128
LCD_HEIGHT = 64

PADDLE_WIDTH = 4
PADDLE_HEIGHT = 14
PADDLE_BORDER = PADDLE_WIDTH // 2 + 3
PADDLE_SPEED = 80
PADDLE_AUTO_SPEED = 55

PUCK_START_SPEED = 40
PUCK_PLAY_SPEED = 120
PUCK_RADIUS = 2

MAX_DT = 0.05

COLLISION_TOLERANCE = 3

def _sign(val):
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0

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

class Vector:

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)
        self.magnitude = 0.0
        self.angle = 0.0
        self._recalc()

    def _recalc(self):
        self.magnitude = math.sqrt(self.x * self.x + self.y * self.y)
        if self.magnitude:
            self.angle = math.atan2(self.y, self.x)
        else:
            self.angle = 0.0

    def set(self, x, y):
        self.x, self.y = float(x), float(y)
        self._recalc()
        return self

    def set_magnitude(self, mag):
        if self.magnitude:
            scale = float(mag) / self.magnitude
            self.x *= scale
            self.y *= scale
        self.magnitude = float(mag)
        return self

    def set_angle(self, angle):
        self.x = self.magnitude * math.cos(angle)
        self.y = self.magnitude * math.sin(angle)
        self.angle = float(angle)
        return self

    def flip_y(self):
        self.y *= -1
        self._recalc()
        return self

    def flip_x(self):
        self.x *= -1
        self._recalc()
        return self

class Paddle:

    def __init__(self, x):
        self.position = Vector(x, LCD_HEIGHT / 2)
        self.speed = PADDLE_SPEED
        self.score = 0
        self.is_auto = False
        self._up = False
        self._down = False

    def set_input(self, direction):
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
            if _sign(self.position.x - puck.position.x) == _sign(puck.velocity.x):
                diff = puck.position.y - self.position.y
                if diff < -self.speed * dt:
                    self.position.y -= self.speed * dt
                elif diff > self.speed * dt:
                    self.position.y += self.speed * dt
        else:
            direction = 0
            if self._up:
                direction = -1
            elif self._down:
                direction = 1
            self.position.y += self.speed * dt * direction

        half_h = PADDLE_HEIGHT / 2
        self.position.y = max(half_h, min(LCD_HEIGHT - half_h, self.position.y))

class Puck:

    def __init__(self, left, right):
        self.position = Vector()
        self.velocity = Vector()
        self.left = left
        self.right = right
        self._vel_idx = 0
        self.reset(0)

    def _next_velocity(self):
        vx, vy = _PUCK_VELOCITIES[self._vel_idx]
        self._vel_idx = self._vel_idx + 1
        if self._vel_idx >= 50:
            self._vel_idx = 0
        return vx, vy

    def reset(self, state):
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

    def _score(self):
        if self.position.x > LCD_WIDTH + PUCK_RADIUS:
            self.reset(-1)
        elif self.position.x < -PUCK_RADIUS:
            self.reset(1)

    def _bounce(self):
        if self.position.y < PUCK_RADIUS:
            self.velocity.flip_y()
        elif self.position.y > LCD_HEIGHT - PUCK_RADIUS:
            self.velocity.flip_y()

    def _collide(self):
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
            self.velocity.flip_x()
            self.velocity.set_magnitude(PUCK_PLAY_SPEED)

    def _between_paddle(self, paddle_pos):
        half_h = PADDLE_HEIGHT / 2
        y_top = paddle_pos.y - half_h
        y_bot = paddle_pos.y + half_h
        if self.position.y + PUCK_RADIUS + COLLISION_TOLERANCE <= y_top:
            return False
        if self.position.y - PUCK_RADIUS - COLLISION_TOLERANCE >= y_bot:
            return False
        return True

_STATE_SPLASH = 0
_STATE_PLAY   = 1
_STATE_QUIT   = 2

class Game:

    def __init__(self):
        self.left  = Paddle(PADDLE_BORDER)
        self.right = Paddle(LCD_WIDTH - PADDLE_BORDER)
        self.puck  = Puck(self.left, self.right)
        self._state = _STATE_SPLASH

    def step(self, data, dt):
        if isinstance(data, str):
            data = json.loads(data)
        if self._state == _STATE_SPLASH:
            return self._step_splash(data)
        if self._state == _STATE_PLAY:
            return self._step_play(data, dt)
        return ""

    def _step_splash(self, data):
        if data.get("quit"):
            self._do_quit()
            return ""

        start = data.get("start", "")
        if start == "single":
            self.left.is_auto = True
            self._begin_play()
        elif start == "multi":
            self._begin_play()
        return ""

    def _step_play(self, data, dt):
        dt = min(float(dt), MAX_DT)

        if data.get("quit"):
            self._do_quit()
            return ""

        self.left.set_input(data.get("player1", "none"))

        self.right.set_input(data.get("player2", "none"))

        self.left.update(dt, self.puck)
        self.right.update(dt, self.puck)
        self.puck.update(dt)

        return "%d,%d,%d,%d,%d,%d" % (
            int(self.puck.position.x),
            int(self.puck.position.y),
            int(self.left.position.y),
            int(self.right.position.y),
            self.left.score,
            self.right.score)

    def _begin_play(self):
        self._state = _STATE_PLAY

    def _do_quit(self):
        self._state = _STATE_QUIT

_game = Game()

def render_frame(data, dt):
    return _game.step(data, dt)

