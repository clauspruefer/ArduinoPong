/*
 * render_pong_frame.h
 * --------------------
 * Linux ASCII renderer for ArduinoPong.
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
 *   render_pong_frame_str(s)
 *     Convenience wrapper: parses the comma-separated string returned by
 *     MicroPython's render_frame() — e.g. "68,36,44,32,0,0" — and calls
 *     render_pong_frame() with the resulting six integer values.
 *     Returns 1 on success, 0 if the string is malformed.
 *
 * Example loop (1000 frames, 50 ms delay):
 *   #include "render_pong_frame.h"
 *   ...
 *   for (int i = 0; i < 1000; i++) {
 *       // obtain puck_x/y, p1_y, p2_y, p1_score, p2_score from your game source
 *       render_pong_frame(puck_x, puck_y, p1_y, p2_y, p1_score, p2_score);
 *       rpf_sleep_ms(50);
 *   }
 */

#ifndef RENDER_PONG_FRAME_H
#define RENDER_PONG_FRAME_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ========================================================================== */
/* Display dimensions                                                          */
/* ========================================================================== */

/* Terminal columns / rows used for the play field (inner area, borders extra) */
#define RPF_DISP_W  64
#define RPF_DISP_H  32

/* Game-field dimensions (must match main.py LCD_WIDTH / LCD_HEIGHT)          */
#define RPF_LCD_W   128
#define RPF_LCD_H    64

/* Paddle geometry (must match main.py PADDLE_WIDTH / PADDLE_HEIGHT /         */
/* PADDLE_BORDER)                                                              */
#define RPF_PAD_W      4
#define RPF_PAD_H     14
#define RPF_PAD_BORDER 5   /* PADDLE_WIDTH / 2 + 3 */

/* ========================================================================== */
/* ASCII renderer                                                              */
/* ========================================================================== */

/* Map a game-x coordinate to a display column index. */
static int _rpf_col(float gx)
{
    int c = (int)(gx * RPF_DISP_W / RPF_LCD_W);
    if (c < 0)            c = 0;
    if (c >= RPF_DISP_W)  c = RPF_DISP_W - 1;
    return c;
}

/* Map a game-y coordinate to a display row index. */
static int _rpf_row(float gy)
{
    int r = (int)(gy * RPF_DISP_H / RPF_LCD_H);
    if (r < 0)            r = 0;
    if (r >= RPF_DISP_H)  r = RPF_DISP_H - 1;
    return r;
}

/*
 * render_pong_frame
 * -----------------
 * Renders one ArduinoPong game frame as ASCII art to stdout.
 *
 * The display is a RPF_DISP_W × RPF_DISP_H character grid surrounded by
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
    char grid[RPF_DISP_H][RPF_DISP_W + 1];
    char score_row[RPF_DISP_W + 1];
    char lbuf[16];
    char rbuf[16];
    int  ll, rl;
    int  r, c;
    int  col_lo, col_hi, row_lo, row_hi, half_h_r;
    int  px_col, px_row;

    /* ---- initialise grid with spaces ------------------------------------ */
    for (r = 0; r < RPF_DISP_H; r++) {
        memset(grid[r], ' ', RPF_DISP_W);
        grid[r][RPF_DISP_W] = '\0';
    }

    /* ---- centre dashed line (every other row) --------------------------- */
    for (r = 0; r < RPF_DISP_H; r++)
        grid[r][RPF_DISP_W / 2] = (r % 2 == 0) ? ':' : ' ';

    /* ---- left paddle (p1) ---------------------------------------------- */
    col_lo   = _rpf_col(RPF_PAD_BORDER - RPF_PAD_W / 2.0f);
    col_hi   = _rpf_col(RPF_PAD_BORDER + RPF_PAD_W / 2.0f - 1.0f);
    half_h_r = _rpf_row(RPF_PAD_H / 2.0f);
    row_lo   = _rpf_row((float)p1_y) - half_h_r;
    row_hi   = _rpf_row((float)p1_y) + half_h_r;
    for (r = row_lo; r <= row_hi; r++) {
        if (r < 0 || r >= RPF_DISP_H) continue;
        for (c = col_lo; c <= col_hi; c++) {
            if (c >= 0 && c < RPF_DISP_W)
                grid[r][c] = '#';
        }
    }

    /* ---- right paddle (p2) --------------------------------------------- */
    col_lo   = _rpf_col(RPF_LCD_W - RPF_PAD_BORDER - RPF_PAD_W / 2.0f);
    col_hi   = _rpf_col(RPF_LCD_W - RPF_PAD_BORDER + RPF_PAD_W / 2.0f - 1.0f);
    half_h_r = _rpf_row(RPF_PAD_H / 2.0f);
    row_lo   = _rpf_row((float)p2_y) - half_h_r;
    row_hi   = _rpf_row((float)p2_y) + half_h_r;
    for (r = row_lo; r <= row_hi; r++) {
        if (r < 0 || r >= RPF_DISP_H) continue;
        for (c = col_lo; c <= col_hi; c++) {
            if (c >= 0 && c < RPF_DISP_W)
                grid[r][c] = '#';
        }
    }

    /* ---- puck ----------------------------------------------------------- */
    px_col = _rpf_col((float)puck_x);
    px_row = _rpf_row((float)puck_y);
    if (px_row >= 0 && px_row < RPF_DISP_H &&
        px_col >= 0 && px_col < RPF_DISP_W)
        grid[px_row][px_col] = 'O';

    /* ---- score row: "P1:X" left-aligned, "P2:X" right-aligned ---------- */
    memset(score_row, ' ', RPF_DISP_W);
    score_row[RPF_DISP_W] = '\0';
    snprintf(lbuf, sizeof(lbuf), "P1:%d", p1_score);
    snprintf(rbuf, sizeof(rbuf), "P2:%d", p2_score);
    ll = (int)strlen(lbuf);
    rl = (int)strlen(rbuf);
    memcpy(score_row, lbuf, (size_t)ll);
    memcpy(score_row + RPF_DISP_W - rl, rbuf, (size_t)rl);

    /* ---- output frame --------------------------------------------------- */
    /* Move cursor to top-left for in-place animation (no screen clear). */
    fputs("\033[H", stdout);

    /* top border */
    putchar('+');
    for (c = 0; c < RPF_DISP_W; c++) putchar('-');
    puts("+");

    /* score row */
    printf("|%s|\n", score_row);

    /* separator */
    putchar('+');
    for (c = 0; c < RPF_DISP_W; c++) putchar('-');
    puts("+");

    /* play-field rows */
    for (r = 0; r < RPF_DISP_H; r++)
        printf("|%s|\n", grid[r]);

    /* bottom border */
    putchar('+');
    for (c = 0; c < RPF_DISP_W; c++) putchar('-');
    puts("+");

    fflush(stdout);
}

/*
 * render_pong_frame_str
 * ---------------------
 * Parse a comma-separated frame string as returned by MicroPython's
 * render_frame() and render one game frame.
 *
 * Expected format: "puck_x,puck_y,p1_y,p2_y,p1_score,p2_score"
 * Example:         "68,36,44,32,0,0"
 *
 * Returns 1 on success, 0 if the string does not contain exactly six
 * comma-separated integer fields.
 */
static int render_pong_frame_str(const char *s)
{
    int   vals[6];
    int   n;
    char *end;

    if (s == NULL) return 0;

    for (n = 0; n < 6; n++) {
        if (*s == '\0') return 0;
        vals[n] = (int)strtol(s, &end, 10);
        if (end == s) return 0;      /* no digits found at this position */
        s = end;
        if (n < 5) {
            if (*s != ',') return 0; /* expected comma delimiter */
            s++;                     /* skip ',' */
        }
    }

    if (*s != '\0') return 0;        /* trailing garbage */

    render_pong_frame(vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]);
    return 1;
}

/*
 * rpf_sleep_ms
 * ------------
 * Sleep for the given number of milliseconds (POSIX).
 * Use this between render_pong_frame() calls to control animation speed.
 * 50 ms gives ~20 FPS, matching the MAX_DT = 0.05 s used in main.py.
 */
static void rpf_sleep_ms(int ms)
{
    struct timespec ts;
    ts.tv_sec  = ms / 1000;
    ts.tv_nsec = ((long)ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}

#endif /* RENDER_PONG_FRAME_H */
