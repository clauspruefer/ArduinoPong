/*
 * render_pong_frame.h
 * --------------------
 * Linux ASCII renderer for ArduinoPong.
 *
 * Provides two public functions:
 *
 *   render_pong_frame(puck_x, puck_y, p1_y, p2_y, p1_score, p2_score)
 *     Renders one game frame to stdout as ASCII art.  The six parameters
 *     correspond directly to the six comma-separated fields returned by
 *     render_frame(data, dt) in main.py while the game is in the PLAY state:
 *       puck_x, puck_y  – puck centre position (game coords 0-127 / 0-63)
 *       p1_y            – left  paddle centre y (game coords)
 *       p2_y            – right paddle centre y (game coords)
 *       p1_score        – left  player score
 *       p2_score        – right player score
 *
 *   pong_demo_run(frames, delay_ms)
 *     Drives a built-in game simulation that mirrors the physics in main.py.
 *     Calls render_pong_frame() exactly `frames` times and sleeps `delay_ms`
 *     milliseconds after each frame so the output animates smoothly.
 *
 * Standalone build (Linux):
 *   gcc -x c -o pong_demo src/render_pong_frame.h -DRENDER_PONG_MAIN -lm && ./pong_demo
 */

#ifndef RENDER_PONG_FRAME_H
#define RENDER_PONG_FRAME_H

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

/* ========================================================================== */
/* Display constants                                                           */
/* ========================================================================== */

/* Terminal columns / rows used for the play field (inner area, borders extra) */
#define _RPF_DISP_W  64
#define _RPF_DISP_H  32

/* ========================================================================== */
/* Game-field constants  (must match main.py)                                 */
/* ========================================================================== */

#define _RPF_LCD_W        128
#define _RPF_LCD_H         64
#define _RPF_PAD_W          4
#define _RPF_PAD_H         14
#define _RPF_PAD_BORDER     5   /* PADDLE_WIDTH / 2 + 3 */
#define _RPF_PUCK_R         2
#define _RPF_PAD_AUTO      55.0f   /* pixels / second – AI paddle speed  */
#define _RPF_PUCK_START    40.0f   /* pixels / second – speed after reset */
#define _RPF_PUCK_PLAY    120.0f   /* pixels / second – speed after hit   */
#define _RPF_MAX_DT         0.05f  /* maximum physics time-step (seconds) */
#define _RPF_COLL_TOL       3.0f   /* extra vertical collision tolerance  */
#define _RPF_VEL_COUNT     50      /* number of pre-calculated velocities */

/* ========================================================================== */
/* ASCII renderer                                                              */
/* ========================================================================== */

/* Map a game-x coordinate to a display column index. */
static int _rpf_col(float gx)
{
    int c = (int)(gx * _RPF_DISP_W / _RPF_LCD_W);
    if (c < 0)             c = 0;
    if (c >= _RPF_DISP_W)  c = _RPF_DISP_W - 1;
    return c;
}

/* Map a game-y coordinate to a display row index. */
static int _rpf_row(float gy)
{
    int r = (int)(gy * _RPF_DISP_H / _RPF_LCD_H);
    if (r < 0)             r = 0;
    if (r >= _RPF_DISP_H)  r = _RPF_DISP_H - 1;
    return r;
}

/*
 * render_pong_frame
 * -----------------
 * Renders one ArduinoPong game frame as ASCII art to stdout.
 *
 * The display is a _RPF_DISP_W × _RPF_DISP_H character grid surrounded by
 * a border, with the score line at the top.  ANSI cursor-home is emitted
 * before each frame so successive calls produce smooth in-place animation.
 *
 * ASCII legend:
 *   #  paddle cell
 *   O  puck
 *   :  centre court dashed line (even rows)
 */
static void render_pong_frame(int puck_x, int puck_y,
                              int p1_y,   int p2_y,
                              int p1_score, int p2_score)
{
    char grid[_RPF_DISP_H][_RPF_DISP_W + 1];
    char score_row[_RPF_DISP_W + 1];
    char lbuf[16];
    char rbuf[16];
    int  ll, rl;
    int  r, c;
    int  col_lo, col_hi, row_lo, row_hi, half_h_r;
    int  px_col, px_row;

    /* ---- initialise grid with spaces ------------------------------------ */
    for (r = 0; r < _RPF_DISP_H; r++) {
        memset(grid[r], ' ', _RPF_DISP_W);
        grid[r][_RPF_DISP_W] = '\0';
    }

    /* ---- centre dashed line (every other row) --------------------------- */
    for (r = 0; r < _RPF_DISP_H; r++)
        grid[r][_RPF_DISP_W / 2] = (r % 2 == 0) ? ':' : ' ';

    /* ---- left paddle (p1) ---------------------------------------------- */
    col_lo   = _rpf_col(_RPF_PAD_BORDER - _RPF_PAD_W / 2.0f);
    col_hi   = _rpf_col(_RPF_PAD_BORDER + _RPF_PAD_W / 2.0f - 1.0f);
    half_h_r = _rpf_row(_RPF_PAD_H / 2.0f);
    row_lo   = _rpf_row((float)p1_y) - half_h_r;
    row_hi   = _rpf_row((float)p1_y) + half_h_r;
    for (r = row_lo; r <= row_hi; r++) {
        if (r < 0 || r >= _RPF_DISP_H) continue;
        for (c = col_lo; c <= col_hi; c++) {
            if (c >= 0 && c < _RPF_DISP_W)
                grid[r][c] = '#';
        }
    }

    /* ---- right paddle (p2) --------------------------------------------- */
    col_lo   = _rpf_col(_RPF_LCD_W - _RPF_PAD_BORDER - _RPF_PAD_W / 2.0f);
    col_hi   = _rpf_col(_RPF_LCD_W - _RPF_PAD_BORDER + _RPF_PAD_W / 2.0f - 1.0f);
    half_h_r = _rpf_row(_RPF_PAD_H / 2.0f);
    row_lo   = _rpf_row((float)p2_y) - half_h_r;
    row_hi   = _rpf_row((float)p2_y) + half_h_r;
    for (r = row_lo; r <= row_hi; r++) {
        if (r < 0 || r >= _RPF_DISP_H) continue;
        for (c = col_lo; c <= col_hi; c++) {
            if (c >= 0 && c < _RPF_DISP_W)
                grid[r][c] = '#';
        }
    }

    /* ---- puck ----------------------------------------------------------- */
    px_col = _rpf_col((float)puck_x);
    px_row = _rpf_row((float)puck_y);
    if (px_row >= 0 && px_row < _RPF_DISP_H &&
        px_col >= 0 && px_col < _RPF_DISP_W)
        grid[px_row][px_col] = 'O';

    /* ---- score row: "P1:X" left-aligned, "P2:X" right-aligned ---------- */
    memset(score_row, ' ', _RPF_DISP_W);
    score_row[_RPF_DISP_W] = '\0';
    snprintf(lbuf, sizeof(lbuf), "P1:%d", p1_score);
    snprintf(rbuf, sizeof(rbuf), "P2:%d", p2_score);
    ll = (int)strlen(lbuf);
    rl = (int)strlen(rbuf);
    memcpy(score_row, lbuf, (size_t)ll);
    memcpy(score_row + _RPF_DISP_W - rl, rbuf, (size_t)rl);

    /* ---- output frame --------------------------------------------------- */
    /* Move cursor to top-left for in-place animation (no screen clear). */
    fputs("\033[H", stdout);

    /* top border */
    putchar('+');
    for (c = 0; c < _RPF_DISP_W; c++) putchar('-');
    puts("+");

    /* score row */
    printf("|%s|\n", score_row);

    /* separator */
    putchar('+');
    for (c = 0; c < _RPF_DISP_W; c++) putchar('-');
    puts("+");

    /* play-field rows */
    for (r = 0; r < _RPF_DISP_H; r++)
        printf("|%s|\n", grid[r]);

    /* bottom border */
    putchar('+');
    for (c = 0; c < _RPF_DISP_W; c++) putchar('-');
    puts("+");

    fflush(stdout);
}

/* ========================================================================== */
/* Built-in game simulation (mirrors main.py physics)                         */
/* ========================================================================== */

typedef struct { float x; float y; } _rpf_v2;

/*
 * Pre-calculated launch velocities – 50 entries, identical to the
 * _PUCK_VELOCITIES list in main.py.  Each pair is (vx, vy); the caller
 * normalises the speed afterwards via _rpf_v2_set_mag().
 */
static const float _RPF_VELS[_RPF_VEL_COUNT][2] = {
    { 0.299777f,  0.278854f}, {-0.723800f, -0.510216f},
    {-1.299285f,  0.353399f}, {-0.198242f,  0.180985f},
    {-1.415851f, -0.562724f}, { 0.385606f,  0.122490f},
    {-1.547527f, -0.559119f}, { 0.765541f,  0.517615f},
    { 0.468526f, -0.319499f}, { 1.702367f, -0.795579f},
    {-1.953737f,  0.694989f}, { 1.198595f,  0.459464f},
    { 1.583319f, -0.842400f}, {-0.481705f,  0.154704f},
    {-1.070532f,  0.322527f}, { 2.557897f,  0.710635f},
    { 1.290885f, -0.444053f}, { 1.393786f, -0.674692f},
    {-1.231363f,  0.403641f}, {-0.330321f,  0.218262f},
    {-1.439538f, -0.673195f}, {-1.302843f,  0.369229f},
    { 0.594090f, -0.541904f}, { 0.236921f, -0.197670f},
    { 1.435542f, -0.574747f}, { 1.013453f, -0.714257f},
    { 1.129002f,  0.494028f}, {-1.101814f, -0.276007f},
    {-0.024249f,  0.019053f}, {-1.053354f,  0.722206f},
    {-1.323984f,  0.584159f}, { 0.642460f, -0.230465f},
    {-0.227863f,  0.058229f}, { 0.484477f,  0.360567f},
    { 1.085422f,  0.537197f}, { 0.308061f, -0.130469f},
    {-3.101142f,  0.943776f}, {-1.404513f,  0.741037f},
    {-2.282604f, -0.694321f}, {-0.487959f,  0.197889f},
    { 3.120547f,  0.858197f}, {-0.897647f, -0.521095f},
    {-2.036904f, -0.828693f}, {-2.483721f,  0.955969f},
    {-1.802931f, -0.743217f}, { 1.699721f, -0.469887f},
    {-3.516844f,  0.928726f}, { 0.935688f,  0.425898f},
    {-0.316027f, -0.123800f}, {-0.601032f, -0.504189f},
};

typedef struct {
    _rpf_v2 pos;   /* centre position */
    int      score;
} _rpf_paddle_t;

typedef struct {
    _rpf_v2 pos;
    _rpf_v2 vel;
    int      vel_idx;
} _rpf_puck_t;

typedef struct {
    _rpf_paddle_t p1;   /* left  */
    _rpf_paddle_t p2;   /* right */
    _rpf_puck_t   puck;
} _rpf_game_t;

/* Return +1, -1, or 0 for the sign of v (mirrors _sign() in main.py). */
static float _rpf_sign(float v)
{
    if (v > 0.0f) return  1.0f;
    if (v < 0.0f) return -1.0f;
    return 0.0f;
}

/* Scale vector (vx, vy) so its length equals mag. */
static void _rpf_v2_set_mag(_rpf_v2 *v, float mag)
{
    float cur = sqrtf(v->x * v->x + v->y * v->y);
    if (cur > 0.0f) {
        float s = mag / cur;
        v->x = v->x * s;
        v->y = v->y * s;
    }
}

/*
 * Return 1 if the puck y-range overlaps the paddle at pad_cy.
 * Mirrors _between_paddle() in main.py.
 */
static int _rpf_between_paddle(float puck_y, float pad_cy)
{
    float half_h = _RPF_PAD_H / 2.0f;
    if (puck_y + _RPF_PUCK_R + _RPF_COLL_TOL <= pad_cy - half_h) return 0;
    if (puck_y - _RPF_PUCK_R - _RPF_COLL_TOL >= pad_cy + half_h) return 0;
    return 1;
}

/* Award a point, re-centre the puck, and pick the next launch velocity. */
static void _rpf_puck_reset(_rpf_game_t *g, int state)
{
    if (state > 0) g->p2.score = g->p2.score + 1;
    if (state < 0) g->p1.score = g->p1.score + 1;

    g->puck.pos.x  = _RPF_LCD_W / 2.0f;
    g->puck.pos.y  = _RPF_LCD_H / 2.0f;
    g->puck.vel.x  = _RPF_VELS[g->puck.vel_idx][0];
    g->puck.vel.y  = _RPF_VELS[g->puck.vel_idx][1];
    g->puck.vel_idx = (g->puck.vel_idx + 1) % _RPF_VEL_COUNT;
    _rpf_v2_set_mag(&g->puck.vel, _RPF_PUCK_START);
}

/* Initialise all game state. */
static void _rpf_game_init(_rpf_game_t *g)
{
    g->p1.pos.x = (float)_RPF_PAD_BORDER;
    g->p1.pos.y = _RPF_LCD_H / 2.0f;
    g->p1.score = 0;
    g->p2.pos.x = _RPF_LCD_W - (float)_RPF_PAD_BORDER;
    g->p2.pos.y = _RPF_LCD_H / 2.0f;
    g->p2.score = 0;
    g->puck.vel_idx = 0;
    _rpf_puck_reset(g, 0);
}

/*
 * Advance the game by one time-step dt (seconds).
 * Both paddles use AI (mirrors the "single player" AI logic in main.py)
 * so the demo runs without user input.
 */
static void _rpf_step(_rpf_game_t *g, float dt)
{
    float half_h;
    float diff;
    float spd;
    float half_w;
    float angle;
    float mag;
    int   on_left;
    int   on_right;

    if (dt > _RPF_MAX_DT) dt = _RPF_MAX_DT;

    /* -- AI: move p1 toward puck when puck is heading this way ------------ */
    spd = _RPF_PAD_AUTO;
    if (_rpf_sign(g->p1.pos.x - g->puck.pos.x) ==
        _rpf_sign(g->puck.vel.x)) {
        diff = g->puck.pos.y - g->p1.pos.y;
        if      (diff < -spd * dt) g->p1.pos.y = g->p1.pos.y - spd * dt;
        else if (diff >  spd * dt) g->p1.pos.y = g->p1.pos.y + spd * dt;
    }

    /* -- AI: move p2 toward puck when puck is heading this way ------------ */
    if (_rpf_sign(g->p2.pos.x - g->puck.pos.x) ==
        _rpf_sign(g->puck.vel.x)) {
        diff = g->puck.pos.y - g->p2.pos.y;
        if      (diff < -spd * dt) g->p2.pos.y = g->p2.pos.y - spd * dt;
        else if (diff >  spd * dt) g->p2.pos.y = g->p2.pos.y + spd * dt;
    }

    /* -- clamp paddles to vertical display bounds ------------------------- */
    half_h = _RPF_PAD_H / 2.0f;
    if (g->p1.pos.y < half_h)               g->p1.pos.y = half_h;
    if (g->p1.pos.y > _RPF_LCD_H - half_h)  g->p1.pos.y = _RPF_LCD_H - half_h;
    if (g->p2.pos.y < half_h)               g->p2.pos.y = half_h;
    if (g->p2.pos.y > _RPF_LCD_H - half_h)  g->p2.pos.y = _RPF_LCD_H - half_h;

    /* -- advance puck position -------------------------------------------- */
    g->puck.pos.x = g->puck.pos.x + g->puck.vel.x * dt;
    g->puck.pos.y = g->puck.pos.y + g->puck.vel.y * dt;

    /* -- paddle collision ------------------------------------------------- */
    half_w   = _RPF_PAD_W / 2.0f;
    on_left  = (g->puck.pos.x - _RPF_PUCK_R < g->p1.pos.x + half_w);
    on_right = (g->puck.pos.x + _RPF_PUCK_R > g->p2.pos.x - half_w);

    if (on_left && _rpf_between_paddle(g->puck.pos.y, g->p1.pos.y)) {
        /* Deflect off left paddle: angle maps hit position to [-π/4, π/4]. */
        angle = (g->puck.pos.y - (g->p1.pos.y - _RPF_PAD_H / 2.0f))
                / _RPF_PAD_H * (float)M_PI / 2.0f - (float)M_PI / 4.0f;
        mag = _RPF_PUCK_PLAY;
        g->puck.vel.x =  mag * cosf(angle);
        g->puck.vel.y =  mag * sinf(angle);
    }

    if (on_right && _rpf_between_paddle(g->puck.pos.y, g->p2.pos.y)) {
        /* Deflect off right paddle: same angle mapping, then flip x. */
        angle = (g->puck.pos.y - (g->p2.pos.y - _RPF_PAD_H / 2.0f))
                / _RPF_PAD_H * (float)M_PI / 2.0f - (float)M_PI / 4.0f;
        mag = _RPF_PUCK_PLAY;
        g->puck.vel.x = -mag * cosf(angle);   /* flip x → move left */
        g->puck.vel.y =  mag * sinf(angle);
    }

    /* -- bounce off top / bottom walls ------------------------------------ */
    if (g->puck.pos.y < _RPF_PUCK_R ||
        g->puck.pos.y > _RPF_LCD_H - _RPF_PUCK_R)
        g->puck.vel.y = -g->puck.vel.y;

    /* -- scoring: puck left or right play area ---------------------------- */
    if (g->puck.pos.x > _RPF_LCD_W + _RPF_PUCK_R)
        _rpf_puck_reset(g, -1);   /* left paddle scores  */
    else if (g->puck.pos.x < -(float)_RPF_PUCK_R)
        _rpf_puck_reset(g,  1);   /* right paddle scores */
}

/* Sleep for the given number of milliseconds (POSIX). */
static void _rpf_sleep_ms(int ms)
{
    struct timespec ts;
    ts.tv_sec  = ms / 1000;
    ts.tv_nsec = ((long)ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}

/*
 * pong_demo_run
 * -------------
 * Run the built-in ArduinoPong simulation and render each frame as ASCII art.
 *
 * @frames    Number of frames to render.  Pass 1000 for the standard demo.
 * @delay_ms  Milliseconds to sleep after each frame.  50 ms gives ~20 FPS,
 *            matching the MAX_DT = 0.05 s used in main.py.
 */
static void pong_demo_run(int frames, int delay_ms)
{
    _rpf_game_t game;
    float       dt = (float)delay_ms / 1000.0f;
    int         i;

    _rpf_game_init(&game);

    /* Hide cursor and clear screen once before the animation loop. */
    fputs("\033[?25l\033[2J", stdout);

    for (i = 0; i < frames; i++) {
        _rpf_step(&game, dt);

        render_pong_frame(
            (int)game.puck.pos.x, (int)game.puck.pos.y,
            (int)game.p1.pos.y,   (int)game.p2.pos.y,
            game.p1.score,        game.p2.score
        );

        _rpf_sleep_ms(delay_ms);
    }

    /* Restore cursor. */
    fputs("\033[?25h", stdout);
}

/* ========================================================================== */
/* Optional standalone entry point                                            */
/* ========================================================================== */

#ifdef RENDER_PONG_MAIN
/*
 * Compile and run as a standalone program:
 *   gcc -x c -o pong_demo src/render_pong_frame.h -DRENDER_PONG_MAIN -lm
 *   ./pong_demo
 */
int main(void)
{
    pong_demo_run(1000, 50);
    return 0;
}
#endif /* RENDER_PONG_MAIN */

#endif /* RENDER_PONG_FRAME_H */
