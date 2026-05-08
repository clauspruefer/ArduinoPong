import math
import random
import sys

OLED_OUTPUT = True

ASCII_DEBUG = False

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

PADDLE_WIDTH = 4
PADDLE_HEIGHT = 14
PADDLE_BORDER = PADDLE_WIDTH // 2 + 3
PADDLE_SPEED = 80
PADDLE_AUTO_SPEED = 55

PUCK_START_SPEED = 40
PUCK_PLAY_SPEED = 120
PUCK_RADIUS = 2

COLLISION_TOLERANCE = 3

def _sign(val):
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0

def _fill_rect_centered(x, y, w, h, color=1):
    ox = int(x - w / 2)
    oy = int(y - h / 2)
    x0 = max(0, ox)
    y0 = max(0, oy)
    rw = min(int(w), LCD_WIDTH - x0)
    rh = min(int(h), LCD_HEIGHT - y0)
    if rw > 0 and rh > 0:
        if OLED_OUTPUT:
            oled.fill_rect(x0, y0, rw, rh, color)

def _random_puck_velocity():
    vy = random.uniform(-1.0, 1.0)
    vx = (random.random() * 3.0 + 1.0) * abs(vy) * random.choice([-1, 1])
    return vx, vy

_ASCII_COLS = 64
_ASCII_ROWS = 16

def _debug_print_frame(left, right, puck):
    def _to_col(px):
        return min(_ASCII_COLS - 1, max(0, int(px * _ASCII_COLS / LCD_WIDTH)))

    def _to_row(py):
        return min(_ASCII_ROWS - 1, max(0, int(py * _ASCII_ROWS / LCD_HEIGHT)))

    grid = [[' '] * _ASCII_COLS for _ in range(_ASCII_ROWS)]

    cx = _ASCII_COLS // 2
    for r in range(_ASCII_ROWS):
        grid[r][cx] = ':' if r % 2 == 0 else ' '

    paddle_half = max(1, int(PADDLE_HEIGHT * _ASCII_ROWS / LCD_HEIGHT / 2))

    lx = _to_col(left.position.x)
    ly = _to_row(left.position.y)
    for r in range(max(0, ly - paddle_half), min(_ASCII_ROWS, ly + paddle_half + 1)):
        grid[r][lx] = '|'

    rx = _to_col(right.position.x)
    ry = _to_row(right.position.y)
    for r in range(max(0, ry - paddle_half), min(_ASCII_ROWS, ry + paddle_half + 1)):
        grid[r][rx] = '|'

    bx = _to_col(puck.position.x)
    by = _to_row(puck.position.y)
    grid[by][bx] = 'o'

    border = '+' + '-' * _ASCII_COLS + '+'
    _SCORE_INDENT = 4
    _SCORE_GAP = 7
    pad = _ASCII_COLS // 2 - _SCORE_INDENT
    score_line = (' ' * pad + str(left.score)
                  + ' ' * _SCORE_GAP
                  + str(right.score))
    rows = ['\x1b[H',
            score_line,
            border]
    for row in grid:
        rows.append('|' + ''.join(row) + '|')
    rows.append(border)

    sys.stdout.write('\n'.join(rows) + '\n')

class Vector:

    __slots__ = ("x", "y", "magnitude", "angle")

    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)
        self.magnitude = 0.0
        self.angle = 0.0
        self._recalc()

    def _recalc(self):
        self.magnitude = math.sqrt(self.x * self.x + self.y * self.y)
        self.angle = math.atan2(self.y, self.x) if self.magnitude else 0.0

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

    def __iadd__(self, other):
        self.x += other.x
        self.y += other.y
        self._recalc()
        return self

    def __mul__(self, scalar):
        return Vector(self.x * scalar, self.y * scalar)

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

    def set_input(self, up: bool, down: bool):
        self._up = up
        self._down = down

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
            direction = -1 if self._up else (1 if self._down else 0)
            self.position.y += self.speed * dt * direction

        half_h = PADDLE_HEIGHT / 2
        self.position.y = max(half_h, min(LCD_HEIGHT - half_h, self.position.y))

    def show(self):
        _fill_rect_centered(self.position.x, self.position.y,
                            PADDLE_WIDTH, PADDLE_HEIGHT)

class Puck:

    def __init__(self, left: Paddle, right: Paddle):
        self.position = Vector()
        self.velocity = Vector()
        self.left = left
        self.right = right
        self.reset(0)

    def reset(self, state: int):
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
        size = PUCK_RADIUS * 2
        _fill_rect_centered(self.position.x, self.position.y, size, size)

    def _score(self):
        if self.position.x > LCD_WIDTH + PUCK_RADIUS:
            self.reset(-1)
        elif self.position.x < -PUCK_RADIUS:
            self.reset(1)

    def _bounce(self):
        if (self.position.y < PUCK_RADIUS or
                self.position.y > LCD_HEIGHT - PUCK_RADIUS):
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

    def _between_paddle(self, paddle_pos) -> bool:
        half_h = PADDLE_HEIGHT / 2
        return (self.position.y + PUCK_RADIUS + COLLISION_TOLERANCE > paddle_pos.y - half_h and
                self.position.y - PUCK_RADIUS - COLLISION_TOLERANCE < paddle_pos.y + half_h)

def _draw_center_line():
    y = 3
    while y < LCD_HEIGHT - 2:
        _fill_rect_centered(LCD_WIDTH / 2, y, 2, 2)
        y += 4

def _show_splash():
    if OLED_OUTPUT:
        oled.fill(0)
        oled.text("ArduinoPong", 18, 2, 1)
        oled.text("L:Single  R:Multi", 0, 16, 1)
        oled.text("Up/Down = Move", 0, 28, 1)
        oled.text("q = Quit", 0, 40, 1)
        oled.text("By Warren James", 0, 54, 1)
        oled.show()

class Game:

    _SPLASH = 0
    _PLAY   = 1
    _QUIT   = 2

    def __init__(self):
        self.left  = Paddle(PADDLE_BORDER)
        self.right = Paddle(LCD_WIDTH - PADDLE_BORDER)
        self.puck  = Puck(self.left, self.right)
        self._state = self._SPLASH

    def show_splash(self):
        _show_splash()

    def step(self, data: dict, dt: float) -> bool:
        if self._state == self._SPLASH:
            return self._step_splash(data)
        if self._state == self._PLAY:
            return self._step_play(data, dt)
        return False

    def _step_splash(self, data: dict) -> bool:
        if data.get("quit"):
            self._do_quit()
            return False

        start = data.get("start", "")
        if start == "single":
            self.left.is_auto = True
            self._begin_play()
        elif start == "multi":
            self._begin_play()
        return True

    def _step_play(self, data: dict, dt: float) -> bool:
        if data.get("quit"):
            self._do_quit()
            return False

        p1 = data.get("player1", "none")
        self.left.set_input(p1 == "up", p1 == "down")

        p2 = data.get("player2", "none")
        self.right.set_input(p2 == "up", p2 == "down")

        self.left.update(dt, self.puck)
        self.right.update(dt, self.puck)
        self.puck.update(dt)

        if OLED_OUTPUT:
            oled.fill(0)
            _draw_center_line()
            self.left.show()
            self.right.show()
            self.puck.show()
            oled.text(str(self.left.score),  LCD_WIDTH // 2 - 12, 2, 1)
            oled.text(str(self.right.score), LCD_WIDTH // 2 + 6,  2, 1)
            oled.show()
        else:
            if ASCII_DEBUG:
                _draw_center_line()
                self.left.show()
                self.right.show()
                self.puck.show()

        if ASCII_DEBUG:
            _debug_print_frame(self.left, self.right, self.puck)

        return True

    def _begin_play(self):
        self._state = self._PLAY

    def _do_quit(self):
        if OLED_OUTPUT:
            oled.fill(0)
            oled.show()
        self._state = self._QUIT

_game = Game()

def render_frame(data, dt):
    return _game.step(data, dt)

