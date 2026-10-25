/*
 * CyberArena 3D - Hardware-Accelerated OpenGL + SDL2 Test Game for Cloud Gaming Phase 1
 *
 * Features:
 * - Real-time 60 FPS 3D first-person arena rendered on the GPU (OpenGL)
 * - Displays active GPU renderer string, score, and live input telemetry on HUD
 * - Full Keyboard (WASD/Arrows/Space/ESC), Mouse (Look + Left/Right Click),
 *   and SDL2 Gamepad/Controller support
 * - Real-time synthesized stereo audio (48kHz) for laser shots, jumps, and target hits
 */

#include <SDL2/SDL.h>
#include <GL/gl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define MAX_TARGETS 12
#define MAX_LASERS 16

typedef struct {
    float x, y, z;
    float rot;
    float color[3];
    bool active;
    float respawn_timer;
} Target;

typedef struct {
    float x, y, z;
    float vx, vy, vz;
    float life;
    bool active;
} Laser;

/* Synth Audio State */
typedef struct {
    float phase_ambient;
    float laser_freq;
    float laser_env;
    float jump_freq;
    float jump_env;
    float hit_freq;
    float hit_env;
} SynthState;

static SynthState g_synth = {0};

static void audio_callback(void *userdata, Uint8 *stream, int len) {
    (void)userdata;
    float *out = (float *)stream;
    int frames = len / (sizeof(float) * 2);
    const float sr = 48000.0f;

    for (int i = 0; i < frames; i++) {
        /* Subtle ambient drone so audio stream can be verified continuously */
        g_synth.phase_ambient += 110.0f / sr;
        if (g_synth.phase_ambient >= 1.0f) g_synth.phase_ambient -= 1.0f;
        float sample = sinf(g_synth.phase_ambient * 2.0f * (float)M_PI) * 0.015f;

        /* Laser sound (descending synth chirp) */
        if (g_synth.laser_env > 0.001f) {
            sample += sinf(g_synth.laser_freq) * g_synth.laser_env * 0.25f;
            g_synth.laser_freq += (350.0f + g_synth.laser_env * 900.0f) * 2.0f * (float)M_PI / sr;
            g_synth.laser_env *= 0.9992f;
        }

        /* Jump sound (ascending whoosh) */
        if (g_synth.jump_env > 0.001f) {
            sample += sinf(g_synth.jump_freq) * g_synth.jump_env * 0.20f;
            g_synth.jump_freq += (200.0f + (1.0f - g_synth.jump_env) * 400.0f) * 2.0f * (float)M_PI / sr;
            g_synth.jump_env *= 0.9994f;
        }

        /* Target hit chime (high harmonic) */
        if (g_synth.hit_env > 0.001f) {
            sample += (sinf(g_synth.hit_freq) + 0.5f * sinf(g_synth.hit_freq * 1.5f)) * g_synth.hit_env * 0.28f;
            g_synth.hit_freq += 880.0f * 2.0f * (float)M_PI / sr;
            g_synth.hit_env *= 0.9993f;
        }

        if (sample > 0.8f) sample = 0.8f;
        if (sample < -0.8f) sample = -0.8f;
        out[i * 2 + 0] = sample;
        out[i * 2 + 1] = sample;
    }
}

static void trigger_laser_sound(void) {
    SDL_LockAudio();
    g_synth.laser_freq = 0.0f;
    g_synth.laser_env = 1.0f;
    SDL_UnlockAudio();
}

static void trigger_jump_sound(void) {
    SDL_LockAudio();
    g_synth.jump_freq = 0.0f;
    g_synth.jump_env = 1.0f;
    SDL_UnlockAudio();
}

static void trigger_hit_sound(void) {
    SDL_LockAudio();
    g_synth.hit_freq = 0.0f;
    g_synth.hit_env = 1.0f;
    SDL_UnlockAudio();
}

/* Simple 5x7 bitmap font for crisp OpenGL HUD text rendering without external font assets */
static void draw_char(char c, float x, float y, float scale) {
    static const unsigned char font[96][7] = {
        [' ' - 32] = {0x00,0x00,0x00,0x00,0x00,0x00,0x00},
        ['!' - 32] = {0x04,0x04,0x04,0x04,0x04,0x00,0x04},
        ['-' - 32] = {0x00,0x00,0x00,0x1F,0x00,0x00,0x00},
        ['.' - 32] = {0x00,0x00,0x00,0x00,0x00,0x00,0x04},
        ['/' - 32] = {0x01,0x02,0x02,0x04,0x08,0x08,0x10},
        [':' - 32] = {0x00,0x04,0x00,0x00,0x04,0x00,0x00},
        ['[' - 32] = {0x0E,0x08,0x08,0x08,0x08,0x08,0x0E},
        [']' - 32] = {0x0E,0x02,0x02,0x02,0x02,0x02,0x0E},
        ['(' - 32] = {0x02,0x04,0x08,0x08,0x08,0x04,0x02},
        [')' - 32] = {0x08,0x04,0x02,0x02,0x02,0x04,0x08},
        ['+' - 32] = {0x00,0x04,0x04,0x1F,0x04,0x04,0x00},
        ['0' - 32] = {0x0E,0x11,0x13,0x15,0x19,0x11,0x0E},
        ['1' - 32] = {0x04,0x0C,0x04,0x04,0x04,0x04,0x0E},
        ['2' - 32] = {0x0E,0x11,0x01,0x06,0x08,0x10,0x1F},
        ['3' - 32] = {0x1F,0x02,0x04,0x02,0x01,0x11,0x0E},
        ['4' - 32] = {0x02,0x06,0x0A,0x12,0x1F,0x02,0x02},
        ['5' - 32] = {0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E},
        ['6' - 32] = {0x06,0x08,0x10,0x1E,0x11,0x11,0x0E},
        ['7' - 32] = {0x1F,0x01,0x02,0x04,0x08,0x08,0x08},
        ['8' - 32] = {0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E},
        ['9' - 32] = {0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C},
        ['A' - 32] = {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11},
        ['B' - 32] = {0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E},
        ['C' - 32] = {0x0E,0x11,0x10,0x10,0x10,0x11,0x0E},
        ['D' - 32] = {0x1C,0x12,0x11,0x11,0x11,0x12,0x1C},
        ['E' - 32] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F},
        ['F' - 32] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x10},
        ['G' - 32] = {0x0E,0x11,0x10,0x17,0x11,0x11,0x0F},
        ['H' - 32] = {0x11,0x11,0x11,0x1F,0x11,0x11,0x11},
        ['I' - 32] = {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E},
        ['J' - 32] = {0x07,0x02,0x02,0x02,0x02,0x12,0x0C},
        ['K' - 32] = {0x11,0x12,0x14,0x18,0x14,0x12,0x11},
        ['L' - 32] = {0x10,0x10,0x10,0x10,0x10,0x10,0x1F},
        ['M' - 32] = {0x11,0x1B,0x15,0x15,0x11,0x11,0x11},
        ['N' - 32] = {0x11,0x11,0x19,0x15,0x13,0x11,0x11},
        ['O' - 32] = {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E},
        ['P' - 32] = {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10},
        ['Q' - 32] = {0x0E,0x11,0x11,0x11,0x15,0x12,0x0D},
        ['R' - 32] = {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11},
        ['S' - 32] = {0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E},
        ['T' - 32] = {0x1F,0x04,0x04,0x04,0x04,0x04,0x04},
        ['U' - 32] = {0x11,0x11,0x11,0x11,0x11,0x11,0x0E},
        ['V' - 32] = {0x11,0x11,0x11,0x11,0x11,0x0A,0x04},
        ['W' - 32] = {0x11,0x11,0x11,0x15,0x15,0x15,0x0A},
        ['X' - 32] = {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11},
        ['Y' - 32] = {0x11,0x11,0x11,0x0A,0x04,0x04,0x04},
        ['Z' - 32] = {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F},
    };
    if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
    if (c < 32 || c >= 127) return;
    const unsigned char *glyph = font[(int)c - 32];
    glBegin(GL_QUADS);
    for (int row = 0; row < 7; row++) {
        unsigned char bits = glyph[row];
        for (int col = 0; col < 5; col++) {
            if (bits & (1 << (4 - col))) {
                float px = x + col * scale;
                float py = y + row * scale;
                glVertex2f(px, py);
                glVertex2f(px + scale, py);
                glVertex2f(px + scale, py + scale);
                glVertex2f(px, py + scale);
            }
        }
    }
    glEnd();
}

static void draw_text(const char *str, float x, float y, float scale) {
    float cx = x;
    while (*str) {
        draw_char(*str, cx, y, scale);
        cx += 6.0f * scale;
        str++;
    }
}

static void set_perspective(float fov_deg, float aspect, float znear, float zfar) {
    float f = 1.0f / tanf((fov_deg * (float)M_PI / 180.0f) * 0.5f);
    float m[16] = {0};
    m[0] = f / aspect;
    m[5] = f;
    m[10] = (zfar + znear) / (znear - zfar);
    m[11] = -1.0f;
    m[14] = (2.0f * zfar * znear) / (znear - zfar);
    glMultMatrixf(m);
}

static void draw_cube(float size, const float color[3]) {
    float s = size * 0.5f;
    glBegin(GL_QUADS);
    /* Front */
    glColor3f(color[0], color[1], color[2]);
    glVertex3f(-s, -s,  s); glVertex3f( s, -s,  s); glVertex3f( s,  s,  s); glVertex3f(-s,  s,  s);
    /* Back */
    glColor3f(color[0]*0.8f, color[1]*0.8f, color[2]*0.8f);
    glVertex3f( s, -s, -s); glVertex3f(-s, -s, -s); glVertex3f(-s,  s, -s); glVertex3f( s,  s, -s);
    /* Top */
    glColor3f(fminf(1.0f, color[0]*1.2f), fminf(1.0f, color[1]*1.2f), fminf(1.0f, color[2]*1.2f));
    glVertex3f(-s,  s,  s); glVertex3f( s,  s,  s); glVertex3f( s,  s, -s); glVertex3f(-s,  s, -s);
    /* Bottom */
    glColor3f(color[0]*0.5f, color[1]*0.5f, color[2]*0.5f);
    glVertex3f(-s, -s, -s); glVertex3f( s, -s, -s); glVertex3f( s, -s,  s); glVertex3f(-s, -s,  s);
    /* Right */
    glColor3f(color[0]*0.9f, color[1]*0.9f, color[2]*0.9f);
    glVertex3f( s, -s,  s); glVertex3f( s, -s, -s); glVertex3f( s,  s, -s); glVertex3f( s,  s,  s);
    /* Left */
    glColor3f(color[0]*0.7f, color[1]*0.7f, color[2]*0.7f);
    glVertex3f(-s, -s, -s); glVertex3f(-s, -s,  s); glVertex3f(-s,  s,  s); glVertex3f(-s,  s, -s);
    glEnd();

    /* Neon wireframe outline */
    glColor3f(1.0f, 1.0f, 1.0f);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    glBegin(GL_QUADS);
    glVertex3f(-s, -s,  s); glVertex3f( s, -s,  s); glVertex3f( s,  s,  s); glVertex3f(-s,  s,  s);
    glVertex3f( s, -s, -s); glVertex3f(-s, -s, -s); glVertex3f(-s,  s, -s); glVertex3f( s,  s, -s);
    glEnd();
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
}

int main(int argc, char *argv[]) {
    int max_frames = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc) {
            max_frames = atoi(argv[++i]);
        }
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMECONTROLLER | SDL_INIT_JOYSTICK) != 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }

    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);

    int win_w = 1280;
    int win_h = 720;
    const char *env_w = getenv("STREAM_WIDTH");
    const char *env_h = getenv("STREAM_HEIGHT");
    if (env_w && atoi(env_w) > 0) win_w = atoi(env_w);
    if (env_h && atoi(env_h) > 0) win_h = atoi(env_h);

    SDL_Window *window = SDL_CreateWindow(
        "CyberArena 3D - Isolated Cloud Gaming Session",
        0, 0,
        win_w, win_h,
        SDL_WINDOW_OPENGL | SDL_WINDOW_BORDERLESS | SDL_WINDOW_RESIZABLE | SDL_WINDOW_INPUT_FOCUS
    );
    if (!window) {
        fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }

    SDL_GLContext glctx = SDL_GL_CreateContext(window);
    if (!glctx) {
        fprintf(stderr, "SDL_GL_CreateContext failed: %s\n", SDL_GetError());
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }
    SDL_GL_SetSwapInterval(1);

    /* Initialize SDL Audio */
    SDL_AudioSpec want = {0}, have = {0};
    want.freq = 48000;
    want.format = AUDIO_F32SYS;
    want.channels = 2;
    want.samples = 512;
    want.callback = audio_callback;
    if (SDL_OpenAudio(&want, &have) == 0) {
        SDL_PauseAudio(0);
    }

    /* Open first available GameController / Joystick */
    SDL_GameController *controller = NULL;
    SDL_Joystick *joystick = NULL;
    for (int i = 0; i < SDL_NumJoysticks(); i++) {
        if (SDL_IsGameController(i)) {
            controller = SDL_GameControllerOpen(i);
            if (controller) break;
        } else {
            joystick = SDL_JoystickOpen(i);
            if (joystick) break;
        }
    }

    const char *gpu_renderer = (const char *)glGetString(GL_RENDERER);
    if (!gpu_renderer) gpu_renderer = "UNKNOWN GPU";
    printf("[CyberArena3D] Running on GPU: %s\n", gpu_renderer);
    fflush(stdout);

    /* Player state */
    float px = 0.0f, py = 1.7f, pz = 12.0f;
    float vy = 0.0f;
    float yaw = 0.0f, pitch = -5.0f;
    bool on_ground = true;
    int score = 0;
    char last_input[64] = "READY - USE WASD / MOUSE / GAMEPAD";

    Target targets[MAX_TARGETS];
    for (int i = 0; i < MAX_TARGETS; i++) {
        float angle = (float)i * (2.0f * (float)M_PI / MAX_TARGETS);
        float radius = 10.0f + (i % 3) * 4.0f;
        targets[i].x = cosf(angle) * radius;
        targets[i].y = 1.6f + (float)(i % 3) * 0.8f;
        targets[i].z = sinf(angle) * radius;
        targets[i].rot = (float)(i * 30);
        targets[i].color[0] = (i % 3 == 0) ? 0.1f : ((i % 3 == 1) ? 0.95f : 0.2f);
        targets[i].color[1] = (i % 3 == 0) ? 0.9f : ((i % 3 == 1) ? 0.2f : 0.95f);
        targets[i].color[2] = (i % 3 == 0) ? 0.95f : ((i % 3 == 1) ? 0.8f : 0.4f);
        targets[i].active = true;
        targets[i].respawn_timer = 0.0f;
    }

    Laser lasers[MAX_LASERS];
    memset(lasers, 0, sizeof(lasers));

    Uint32 last_ticks = SDL_GetTicks();
    int frame_count = 0;
    float time_sec = 0.0f;
    bool running = true;

    while (running) {
        Uint32 now = SDL_GetTicks();
        float dt = (now - last_ticks) / 1000.0f;
        if (dt > 0.1f) dt = 0.1f;
        last_ticks = now;
        time_sec += dt;

        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_QUIT) {
                running = false;
            } else if (ev.type == SDL_JOYDEVICEADDED) {
                if (!controller && SDL_IsGameController(ev.jdevice.which)) {
                    controller = SDL_GameControllerOpen(ev.jdevice.which);
                    snprintf(last_input, sizeof(last_input), "CONTROLLER CONNECTED");
                } else if (!joystick) {
                    joystick = SDL_JoystickOpen(ev.jdevice.which);
                    snprintf(last_input, sizeof(last_input), "JOYSTICK CONNECTED");
                }
            } else if (ev.type == SDL_KEYDOWN) {
                SDL_Keycode key = ev.key.keysym.sym;
                if (key == SDLK_ESCAPE) {
                    running = false;
                } else if (key == SDLK_SPACE && on_ground) {
                    vy = 7.5f;
                    on_ground = false;
                    trigger_jump_sound();
                    snprintf(last_input, sizeof(last_input), "KEY: SPACE (JUMP)");
                } else if (key == SDLK_f || key == SDLK_RETURN) {
                    for (int i = 0; i < MAX_LASERS; i++) {
                        if (!lasers[i].active) {
                            float rad_yaw = yaw * (float)M_PI / 180.0f;
                            float rad_pitch = pitch * (float)M_PI / 180.0f;
                            lasers[i].x = px;
                            lasers[i].y = py - 0.2f;
                            lasers[i].z = pz;
                            lasers[i].vx = sinf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].vy = sinf(rad_pitch) * 38.0f;
                            lasers[i].vz = -cosf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].life = 1.8f;
                            lasers[i].active = true;
                            trigger_laser_sound();
                            snprintf(last_input, sizeof(last_input), "KEY: FIRE LASER");
                            break;
                        }
                    }
                } else {
                    snprintf(last_input, sizeof(last_input), "KEY: %s", SDL_GetKeyName(key));
                }
            } else if (ev.type == SDL_MOUSEMOTION) {
                yaw += (float)ev.motion.xrel * 0.22f;
                pitch -= (float)ev.motion.yrel * 0.18f;
                if (pitch > 75.0f) pitch = 75.0f;
                if (pitch < -75.0f) pitch = -75.0f;
                snprintf(last_input, sizeof(last_input), "MOUSE LOOK (%+d, %+d)", ev.motion.xrel, ev.motion.yrel);
            } else if (ev.type == SDL_MOUSEBUTTONDOWN) {
                if (ev.button.button == SDL_BUTTON_LEFT) {
                    for (int i = 0; i < MAX_LASERS; i++) {
                        if (!lasers[i].active) {
                            float rad_yaw = yaw * (float)M_PI / 180.0f;
                            float rad_pitch = pitch * (float)M_PI / 180.0f;
                            lasers[i].x = px;
                            lasers[i].y = py - 0.2f;
                            lasers[i].z = pz;
                            lasers[i].vx = sinf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].vy = sinf(rad_pitch) * 38.0f;
                            lasers[i].vz = -cosf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].life = 1.8f;
                            lasers[i].active = true;
                            trigger_laser_sound();
                            snprintf(last_input, sizeof(last_input), "MOUSE: LEFT CLICK (FIRE)");
                            break;
                        }
                    }
                } else if (ev.button.button == SDL_BUTTON_RIGHT && on_ground) {
                    vy = 7.5f;
                    on_ground = false;
                    trigger_jump_sound();
                    snprintf(last_input, sizeof(last_input), "MOUSE: RIGHT CLICK (JUMP)");
                }
            } else if (ev.type == SDL_CONTROLLERBUTTONDOWN) {
                if (ev.cbutton.button == SDL_CONTROLLER_BUTTON_A && on_ground) {
                    vy = 7.5f;
                    on_ground = false;
                    trigger_jump_sound();
                    snprintf(last_input, sizeof(last_input), "PAD: A (JUMP)");
                } else if (ev.cbutton.button == SDL_CONTROLLER_BUTTON_X ||
                           ev.cbutton.button == SDL_CONTROLLER_BUTTON_B ||
                           ev.cbutton.button == SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) {
                    for (int i = 0; i < MAX_LASERS; i++) {
                        if (!lasers[i].active) {
                            float rad_yaw = yaw * (float)M_PI / 180.0f;
                            float rad_pitch = pitch * (float)M_PI / 180.0f;
                            lasers[i].x = px;
                            lasers[i].y = py - 0.2f;
                            lasers[i].z = pz;
                            lasers[i].vx = sinf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].vy = sinf(rad_pitch) * 38.0f;
                            lasers[i].vz = -cosf(rad_yaw) * cosf(rad_pitch) * 38.0f;
                            lasers[i].life = 1.8f;
                            lasers[i].active = true;
                            trigger_laser_sound();
                            snprintf(last_input, sizeof(last_input), "PAD: FIRE LASER");
                            break;
                        }
                    }
                }
            }
        }

        const Uint8 *keys = SDL_GetKeyboardState(NULL);
        float move_fwd = 0.0f, move_str = 0.0f;
        if (keys[SDL_SCANCODE_W] || keys[SDL_SCANCODE_UP]) move_fwd += 1.0f;
        if (keys[SDL_SCANCODE_S] || keys[SDL_SCANCODE_DOWN]) move_fwd -= 1.0f;
        if (keys[SDL_SCANCODE_D]) move_str += 1.0f;
        if (keys[SDL_SCANCODE_A]) move_str -= 1.0f;
        if (keys[SDL_SCANCODE_LEFT]) yaw -= 95.0f * dt;
        if (keys[SDL_SCANCODE_RIGHT]) yaw += 95.0f * dt;
        if (keys[SDL_SCANCODE_Q]) yaw -= 95.0f * dt;
        if (keys[SDL_SCANCODE_E]) yaw += 95.0f * dt;

        if (controller) {
            Sint16 lx = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTX);
            Sint16 ly = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTY);
            Sint16 rx = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTX);
            Sint16 ry = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTY);
            if (abs(lx) > 4000) move_str += (float)lx / 32767.0f;
            if (abs(ly) > 4000) move_fwd -= (float)ly / 32767.0f;
            if (abs(rx) > 4000) yaw += ((float)rx / 32767.0f) * 120.0f * dt;
            if (abs(ry) > 4000) pitch -= ((float)ry / 32767.0f) * 85.0f * dt;
        } else if (joystick) {
            Sint16 lx = SDL_JoystickGetAxis(joystick, 0);
            Sint16 ly = SDL_JoystickGetAxis(joystick, 1);
            Sint16 rx = SDL_JoystickGetAxis(joystick, 3);
            Sint16 ry = SDL_JoystickGetAxis(joystick, 4);
            if (abs(lx) > 4000) move_str += (float)lx / 32767.0f;
            if (abs(ly) > 4000) move_fwd -= (float)ly / 32767.0f;
            if (abs(rx) > 4000) yaw += ((float)rx / 32767.0f) * 120.0f * dt;
            if (abs(ry) > 4000) pitch -= ((float)ry / 32767.0f) * 85.0f * dt;
        }

        /* Subtle auto-orbit when idle so user immediately sees 60fps 3D motion on connect */
        if (move_fwd == 0.0f && move_str == 0.0f && strcmp(last_input, "READY - USE WASD / MOUSE / GAMEPAD") == 0) {
            yaw += 12.0f * dt;
        }

        float rad = yaw * (float)M_PI / 180.0f;
        float speed = 9.0f;
        px += (sinf(rad) * move_fwd + cosf(rad) * move_str) * speed * dt;
        pz += (-cosf(rad) * move_fwd + sinf(rad) * move_str) * speed * dt;

        /* Keep inside arena bounds */
        if (px > 26.0f) px = 26.0f;
        if (px < -26.0f) px = -26.0f;
        if (pz > 26.0f) pz = 26.0f;
        if (pz < -26.0f) pz = -26.0f;

        /* Gravity & Jump physics */
        vy -= 18.0f * dt;
        py += vy * dt;
        if (py <= 1.7f) {
            py = 1.7f;
            vy = 0.0f;
            on_ground = true;
        }

        /* Update targets & collisions */
        for (int i = 0; i < MAX_TARGETS; i++) {
            targets[i].rot += 75.0f * dt;
            if (!targets[i].active) {
                targets[i].respawn_timer -= dt;
                if (targets[i].respawn_timer <= 0.0f) {
                    targets[i].active = true;
                }
                continue;
            }
            /* Player touch pickup */
            float dx = px - targets[i].x;
            float dz = pz - targets[i].z;
            if (dx * dx + dz * dz < 2.2f) {
                targets[i].active = false;
                targets[i].respawn_timer = 3.0f;
                score += 100;
                trigger_hit_sound();
                snprintf(last_input, sizeof(last_input), "CRYSTAL CAPTURED! +100");
            }
        }

        /* Update lasers */
        for (int i = 0; i < MAX_LASERS; i++) {
            if (!lasers[i].active) continue;
            lasers[i].x += lasers[i].vx * dt;
            lasers[i].y += lasers[i].vy * dt;
            lasers[i].z += lasers[i].vz * dt;
            lasers[i].life -= dt;
            if (lasers[i].life <= 0.0f) {
                lasers[i].active = false;
                continue;
            }
            for (int t = 0; t < MAX_TARGETS; t++) {
                if (!targets[t].active) continue;
                float dx = lasers[i].x - targets[t].x;
                float dy = lasers[i].y - targets[t].y;
                float dz = lasers[i].z - targets[t].z;
                if (dx * dx + dy * dy + dz * dz < 1.8f) {
                    targets[t].active = false;
                    targets[t].respawn_timer = 2.5f;
                    lasers[i].active = false;
                    score += 250;
                    trigger_hit_sound();
                    snprintf(last_input, sizeof(last_input), "TARGET DESTROYED! +250");
                    break;
                }
            }
        }

        /* Render 3D Scene */
        SDL_GL_GetDrawableSize(window, &win_w, &win_h);
        if (win_h == 0) win_h = 1;
        glViewport(0, 0, win_w, win_h);
        glClearColor(0.04f, 0.05f, 0.12f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glEnable(GL_DEPTH_TEST);

        glMatrixMode(GL_PROJECTION);
        glLoadIdentity();
        set_perspective(70.0f, (float)win_w / (float)win_h, 0.1f, 120.0f);

        glMatrixMode(GL_MODELVIEW);
        glLoadIdentity();
        glRotatef(-pitch, 1.0f, 0.0f, 0.0f);
        glRotatef(yaw, 0.0f, 1.0f, 0.0f);
        glTranslatef(-px, -py, -pz);

        /* Draw Cyber Neon Floor Grid */
        glLineWidth(1.5f);
        glBegin(GL_LINES);
        for (int g = -28; g <= 28; g += 2) {
            float glow = (g % 8 == 0) ? 0.55f : 0.22f;
            glColor3f(0.08f, glow * 0.8f, glow);
            glVertex3f((float)g, 0.0f, -28.0f);
            glVertex3f((float)g, 0.0f,  28.0f);
            glVertex3f(-28.0f, 0.0f, (float)g);
            glVertex3f( 28.0f, 0.0f, (float)g);
        }
        glEnd();

        /* Draw Arena Boundary Pillars */
        for (int p = -24; p <= 24; p += 12) {
            float pillar_col[3] = {0.15f, 0.35f, 0.85f};
            glPushMatrix();
            glTranslatef((float)p, 2.0f, -28.0f);
            glScalef(0.6f, 4.0f, 0.6f);
            draw_cube(1.0f, pillar_col);
            glPopMatrix();

            glPushMatrix();
            glTranslatef((float)p, 2.0f, 28.0f);
            glScalef(0.6f, 4.0f, 0.6f);
            draw_cube(1.0f, pillar_col);
            glPopMatrix();
        }

        /* Draw Rotating Energy Targets */
        for (int i = 0; i < MAX_TARGETS; i++) {
            if (!targets[i].active) continue;
            glPushMatrix();
            float bob = sinf(time_sec * 3.0f + (float)i) * 0.25f;
            glTranslatef(targets[i].x, targets[i].y + bob, targets[i].z);
            glRotatef(targets[i].rot, 0.4f, 1.0f, 0.3f);
            draw_cube(1.25f, targets[i].color);
            glPopMatrix();
        }

        /* Draw Active Lasers */
        float laser_col[3] = {1.0f, 0.95f, 0.2f};
        for (int i = 0; i < MAX_LASERS; i++) {
            if (!lasers[i].active) continue;
            glPushMatrix();
            glTranslatef(lasers[i].x, lasers[i].y, lasers[i].z);
            draw_cube(0.32f, laser_col);
            glPopMatrix();
        }

        /* Render 2D HUD Overlay */
        glDisable(GL_DEPTH_TEST);
        glMatrixMode(GL_PROJECTION);
        glLoadIdentity();
        glOrtho(0, win_w, win_h, 0, -1, 1);
        glMatrixMode(GL_MODELVIEW);
        glLoadIdentity();

        /* Top HUD bar background */
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glColor4f(0.02f, 0.04f, 0.09f, 0.78f);
        glBegin(GL_QUADS);
        glVertex2f(16.0f, 14.0f);
        glVertex2f((float)win_w - 16.0f, 14.0f);
        glVertex2f((float)win_w - 16.0f, 88.0f);
        glVertex2f(16.0f, 88.0f);
        glEnd();
        glDisable(GL_BLEND);

        char buf[160];
        glColor3f(0.25f, 0.95f, 1.0f);
        snprintf(buf, sizeof(buf), "CYBERARENA 3D  -  SCORE: %d", score);
        draw_text(buf, 28.0f, 24.0f, 2.5f);

        glColor3f(0.65f, 0.85f, 0.95f);
        snprintf(buf, sizeof(buf), "GPU: %.48s", gpu_renderer);
        draw_text(buf, 28.0f, 48.0f, 1.8f);

        glColor3f(0.35f, 1.0f, 0.55f);
        snprintf(buf, sizeof(buf), "INPUT: %s", last_input);
        draw_text(buf, 28.0f, 68.0f, 1.8f);

        /* Center Crosshair */
        float cx = win_w * 0.5f;
        float cy = win_h * 0.5f;
        glColor3f(0.2f, 1.0f, 0.8f);
        glLineWidth(2.0f);
        glBegin(GL_LINES);
        glVertex2f(cx - 12.0f, cy); glVertex2f(cx - 4.0f, cy);
        glVertex2f(cx + 4.0f, cy);  glVertex2f(cx + 12.0f, cy);
        glVertex2f(cx, cy - 12.0f); glVertex2f(cx, cy - 4.0f);
        glVertex2f(cx, cy + 4.0f);  glVertex2f(cx, cy + 12.0f);
        glEnd();

        SDL_GL_SwapWindow(window);

        frame_count++;
        if (max_frames > 0 && frame_count >= max_frames) {
            running = false;
        }
    }

    if (controller) SDL_GameControllerClose(controller);
    if (joystick) SDL_JoystickClose(joystick);
    SDL_CloseAudio();
    SDL_GL_DeleteContext(glctx);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}

