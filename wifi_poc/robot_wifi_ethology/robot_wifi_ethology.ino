/*
 * robot_wifi_ethology.ino
 * -----------------------
 * Full integration sketch: WiFi HTTP server + behavior hierarchy dispatch
 * + real servo/sensor hardware.
 *
 * Merges:
 *   hierarchy_serial.ino  — dispatch table, behavior registry, lock timer
 *   robot_poc.ino         — WiFi HTTP server, session tokens, route handlers
 *
 * Connects to an existing WPA network (NOT an AP).
 * Put your SSID and password in the two #define lines below.
 *
 * Compatible with:
 *   Uno R4 WiFi  (WiFiS3.h)
 *   Giga R1 WiFi (WiFi.h — change the #include below)
 *
 * HTTP endpoints  (all matched by the Python RobotWiFiClient)
 * -----------------------------------------------------------
 *   GET  /ping               → {status, session}
 *   POST /run                → {hierarchy:[...]}  → {status, session}
 *   POST /stop               → {session}          → {status}
 *   GET  /state              → full debug dump
 *   POST /reset              → force idle
 *   GET  /tick?<sensors>     → run one dispatch tick, return result
 *                              query params: contact_f, contact_r, ir, ldr_l, ldr_r
 *
 * Behavior registry (same names as Python BEHAVIOR_MAP)
 * -----------------------------------------------------
 *   escape_front    contact_front → reverse arc (timed, 2 s)
 *   escape_rear     contact_rear  → forward arc (timed, 2 s)
 *   avoid_object    IR high       → steer away from obstacle side
 *   approach_object IR high       → steer toward obstacle side
 *   seek_light      LDR gradient  → steer toward brighter side
 *   avoid_light     LDR gradient  → steer away from brighter side
 *   cruise_straight always        → drive straight
 *   cruise_arc      always        → gentle arc
 *
 * Pin assignments (Uno R4 / standard Johuco robot wiring)
 * -------------------------------------------------------
 *   D9   Left servo  (continuous rotation, 90 = stop)
 *   D10  Right servo (continuous rotation, 90 = stop)
 *   A0   Left IR proximity sensor
 *   A1   Right IR proximity sensor
 *   A2   Left LDR
 *   A3   Right LDR
 *   D2   Front contact (bumper switch, INPUT_PULLUP, LOW = pressed)
 *   D3   Rear contact  (bumper switch, INPUT_PULLUP, LOW = pressed)
 *
 * Serial monitor output
 * ---------------------
 * All HTTP requests and tick results are echoed to Serial at 115200 baud.
 * Serial commands from hierarchy_serial.ino still work (sensors:, tick, etc.)
 */

// ── Board / WiFi library ───────────────────────────────────────────────────
#include <WiFiS3.h>          // Uno R4 WiFi
// #include <WiFi.h>         // Giga R1 WiFi — swap if needed
#include <Servo.h>

// ── Network credentials — EDIT THESE ──────────────────────────────────────
#define WIFI_SSID   "NETGEAR66"
#define WIFI_PASS   "aquaticapple869"

// ── Hardware pins ──────────────────────────────────────────────────────────
#define PIN_SERVO_LEFT    9
#define PIN_SERVO_RIGHT   10
#define PIN_IR_LEFT       A0
#define PIN_IR_RIGHT      A1
#define PIN_LDR_LEFT      A2
#define PIN_LDR_RIGHT     A3
#define PIN_CONTACT_FRONT 2
#define PIN_CONTACT_REAR  3

// ── Behavior constants ─────────────────────────────────────────────────────
#define MAX_BEHAVIORS   16
#define ESCAPE_MS       2000UL   // lock duration (ms)
#define IR_THRESHOLD    400      // raw ADC — obstacle detected above this
#define LDR_DIFF_MIN    30       // minimum L/R difference to act on gradient

// ── Servo speed constants (continuous rotation servos) ─────────────────────
// 90 = stop, <90 = reverse, >90 = forward.  Tune to your servos.
#define SERVO_STOP      90
#define SERVO_FWD_FAST  120
#define SERVO_FWD_SLOW  100
#define SERVO_REV_FAST   60

// ── Servo objects ──────────────────────────────────────────────────────────
Servo servoLeft;
Servo servoRight;

void drive(int left_speed, int right_speed) {
    // left servo is typically mirrored — negate it
    servoLeft.write(180 - left_speed);
    servoRight.write(right_speed);
}

void halt() {
    servoLeft.write(SERVO_STOP);
    servoRight.write(SERVO_STOP);
}

// ── Sensor state ───────────────────────────────────────────────────────────
struct SensorState {
    bool contact_front;
    bool contact_rear;
    int  ir_raw;       // raw ADC 0–1023 (higher = closer)
    int  ldr_left;     // raw ADC 0–1023
    int  ldr_right;
} sensors = {false, false, 0, 512, 512};

void read_real_sensors() {
    sensors.contact_front = (digitalRead(PIN_CONTACT_FRONT) == LOW);
    sensors.contact_rear  = (digitalRead(PIN_CONTACT_REAR)  == LOW);
    sensors.ir_raw        = max(analogRead(PIN_IR_LEFT), analogRead(PIN_IR_RIGHT));
    sensors.ldr_left      = analogRead(PIN_LDR_LEFT);
    sensors.ldr_right     = analogRead(PIN_LDR_RIGHT);
}

// ── Behavior lock ──────────────────────────────────────────────────────────
unsigned long lock_until_ms  = 0;
int           lock_owner_idx = -1;

bool is_locked()              { return lock_owner_idx >= 0 && millis() < lock_until_ms; }
void set_lock(int owner_idx)  { lock_until_ms = millis() + ESCAPE_MS; lock_owner_idx = owner_idx; }
void clear_lock()             { lock_until_ms = 0; lock_owner_idx = -1; }

// ── Conditions ────────────────────────────────────────────────────────────
bool cond_front_contact()  { return sensors.contact_front; }
bool cond_rear_contact()   { return sensors.contact_rear; }
bool cond_proximity()      { return sensors.ir_raw >= IR_THRESHOLD; }
bool cond_light_gradient() { return abs(sensors.ldr_left - sensors.ldr_right) >= LDR_DIFF_MIN; }
bool cond_always()         { return true; }

// ── Actions ────────────────────────────────────────────────────────────────
// Each action drives the servos for one tick (~50 ms).
// The dispatch loop calls the action continuously while it fires.

void act_escape_front() {
    // Reverse arc away from whatever side had contact
    // Simple: reverse straight (contact detection is symmetric here)
    drive(SERVO_REV_FAST, SERVO_REV_FAST);
}

void act_escape_rear() {
    drive(SERVO_FWD_FAST, SERVO_FWD_FAST);
}

void act_avoid_object() {
    // Steer away from the closer side
    if (analogRead(PIN_IR_LEFT) > analogRead(PIN_IR_RIGHT)) {
        drive(SERVO_FWD_FAST, SERVO_FWD_SLOW);   // turn right
    } else {
        drive(SERVO_FWD_SLOW, SERVO_FWD_FAST);   // turn left
    }
}

void act_approach_object() {
    if (analogRead(PIN_IR_LEFT) > analogRead(PIN_IR_RIGHT)) {
        drive(SERVO_FWD_SLOW, SERVO_FWD_FAST);   // turn left toward obstacle
    } else {
        drive(SERVO_FWD_FAST, SERVO_FWD_SLOW);   // turn right toward obstacle
    }
}

void act_seek_light() {
    if (sensors.ldr_left > sensors.ldr_right) {
        drive(SERVO_FWD_SLOW, SERVO_FWD_FAST);   // turn left toward brighter
    } else {
        drive(SERVO_FWD_FAST, SERVO_FWD_SLOW);   // turn right toward brighter
    }
}

void act_avoid_light() {
    if (sensors.ldr_left > sensors.ldr_right) {
        drive(SERVO_FWD_FAST, SERVO_FWD_SLOW);   // turn right away from light
    } else {
        drive(SERVO_FWD_SLOW, SERVO_FWD_FAST);   // turn left away from light
    }
}

void act_cruise_straight() { drive(SERVO_FWD_FAST, SERVO_FWD_FAST); }
void act_cruise_arc()      { drive(SERVO_FWD_SLOW, SERVO_FWD_FAST); }

// ── Registry ───────────────────────────────────────────────────────────────
struct RegistryEntry {
    const char* name;
    bool (*condition)();
    void (*action)();
    bool timed;
};

const RegistryEntry REGISTRY[] = {
    { "escape_front",    cond_front_contact,  act_escape_front,    true  },
    { "escape_rear",     cond_rear_contact,   act_escape_rear,     true  },
    { "avoid_object",    cond_proximity,      act_avoid_object,    false },
    { "approach_object", cond_proximity,      act_approach_object, false },
    { "seek_light",      cond_light_gradient, act_seek_light,      false },
    { "avoid_light",     cond_light_gradient, act_avoid_light,     false },
    { "cruise_straight", cond_always,         act_cruise_straight, false },
    { "cruise_arc",      cond_always,         act_cruise_arc,      false },
};
const int REGISTRY_SIZE = sizeof(REGISTRY) / sizeof(REGISTRY[0]);

// ── Active hierarchy ───────────────────────────────────────────────────────
struct BehaviorSlot {
    const RegistryEntry* entry;
    int reg_idx;
};

BehaviorSlot active[MAX_BEHAVIORS];
int          active_count = 0;

int find_in_registry(const char* name) {
    for (int i = 0; i < REGISTRY_SIZE; i++) {
        if (strcmp(REGISTRY[i].name, name) == 0) return i;
    }
    return -1;
}

int parse_hierarchy(const char* json) {
    clear_lock();
    active_count = 0;
    const char* p = json;
    while (*p && *p != '[') p++;
    if (!*p) return 0;
    p++;
    char token[32];
    while (*p && *p != ']' && active_count < MAX_BEHAVIORS) {
        while (*p && *p != '"' && *p != ']') p++;
        if (!*p || *p == ']') break;
        p++;
        int ti = 0;
        while (*p && *p != '"' && ti < (int)sizeof(token) - 1)
            token[ti++] = *p++;
        token[ti] = '\0';
        if (*p == '"') p++;
        if (ti == 0) continue;
        int idx = find_in_registry(token);
        if (idx >= 0) {
            active[active_count].entry   = &REGISTRY[idx];
            active[active_count].reg_idx = idx;
            active_count++;
        } else {
            Serial.print(F("  WARNING: unknown behavior '"));
            Serial.print(token);
            Serial.println(F("' — skipped"));
        }
    }
    return active_count;
}

// ── Dispatch tick ──────────────────────────────────────────────────────────
// Returns name of fired behavior (or "none").
// out_buf must be at least 32 bytes.
int run_one_tick(char* out_fired, int out_len) {
    if (is_locked()) {
        unsigned long remaining = lock_until_ms - millis();
        strncpy(out_fired, active[lock_owner_idx].entry->name, out_len - 1);
        active[lock_owner_idx].entry->action();
        return lock_owner_idx;
    }
    for (int i = 0; i < active_count; i++) {
        if (active[i].entry->condition()) {
            strncpy(out_fired, active[i].entry->name, out_len - 1);
            out_fired[out_len - 1] = '\0';
            if (active[i].entry->timed) set_lock(i);
            active[i].entry->action();
            return i;
        }
    }
    strncpy(out_fired, "none", out_len - 1);
    halt();
    return -1;
}

// ── Autonomous run loop ────────────────────────────────────────────────────
bool          robot_running  = false;
unsigned long last_tick_ms   = 0;
#define TICK_INTERVAL_MS 50   // 20 Hz

void robot_tick_loop() {
    if (!robot_running) return;
    unsigned long now = millis();
    if (now - last_tick_ms < TICK_INTERVAL_MS) return;
    last_tick_ms = now;
    read_real_sensors();
    char fired[32];
    run_one_tick(fired, sizeof(fired));
}

// ── WiFi / HTTP server ─────────────────────────────────────────────────────
WiFiServer server(80);

bool     occupied      = false;
char     session_token[32] = "";
char     hierarchy_buf[256] = "";

static unsigned int token_counter = 0;
void make_token(char* out, int out_len) {
    snprintf(out, out_len, "s%lu_%u", millis(), token_counter++);
}

int read_request(WiFiClient& client, char* buf, int buf_len) {
    const unsigned long TIMEOUT_MS = 2000;
    unsigned long start = millis();
    int idx = 0;
    while (client.connected() && (millis() - start < TIMEOUT_MS)) {
        while (client.available() && idx < buf_len - 1) {
            buf[idx++] = (char)client.read();
            start = millis();
        }
    }
    buf[idx] = '\0';
    return idx;
}

bool extract_json_string(const char* src, const char* key,
                          char* out, int out_len) {
    char search[48];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char* p = strstr(src, search);
    if (!p) return false;
    p += strlen(search);
    while (*p == ' ' || *p == ':') p++;
    if (*p != '"') return false;
    p++;
    int i = 0;
    while (*p && *p != '"' && i < out_len - 1) out[i++] = *p++;
    out[i] = '\0';
    return i > 0;
}

bool extract_json_array(const char* src, const char* key,
                         char* out, int out_len) {
    char search[48];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char* p = strstr(src, search);
    if (!p) return false;
    p += strlen(search);
    while (*p == ' ' || *p == ':') p++;
    if (*p != '[') return false;
    int depth = 0, i = 0;
    while (*p && i < out_len - 1) {
        if (*p == '[') depth++;
        else if (*p == ']') {
            depth--;
            out[i++] = *p++;
            if (depth == 0) break;
            continue;
        }
        out[i++] = *p++;
    }
    out[i] = '\0';
    return i > 0;
}

// Extract query parameter from a URL like /tick?contact_f=1&ir=500
// Returns 0 if not found, atoi(value) otherwise.
int extract_query_int(const char* url, const char* key, int default_val) {
    char search[32];
    snprintf(search, sizeof(search), "%s=", key);
    const char* p = strstr(url, search);
    if (!p) return default_val;
    p += strlen(search);
    return atoi(p);
}

bool extract_query_bool(const char* url, const char* key, bool default_val) {
    char search[32];
    snprintf(search, sizeof(search), "%s=", key);
    const char* p = strstr(url, search);
    if (!p) return default_val;
    p += strlen(search);
    return atoi(p) != 0;
}

void send_json(WiFiClient& client, const char* body) {
    client.print(F("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"));
    client.print(body);
}

void send_error(WiFiClient& client, int code, const char* msg) {
    client.print(F("HTTP/1.1 "));
    client.print(code);
    client.print(F(" Error\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"error\":\""));
    client.print(msg);
    client.print(F("\"}"));
}

// ── Route handlers ─────────────────────────────────────────────────────────

void handle_ping(WiFiClient& client) {
    char body[128];
    snprintf(body, sizeof(body),
        "{\"status\":\"%s\",\"session\":\"%s\"}",
        occupied ? "busy" : "idle",
        occupied ? session_token : "");
    send_json(client, body);
    Serial.print(F("PING → ")); Serial.println(occupied ? "busy" : "idle");
}

void handle_run(WiFiClient& client, const char* request) {
    const char* body_start = strstr(request, "\r\n\r\n");
    if (!body_start) { send_error(client, 400, "no body"); return; }
    body_start += 4;

    if (occupied) {
        send_error(client, 503, "busy");
        Serial.println(F("RUN rejected: busy"));
        return;
    }

    char hier[200];
    if (!extract_json_array(body_start, "hierarchy", hier, sizeof(hier))) {
        send_error(client, 400, "missing hierarchy");
        return;
    }

    int n = parse_hierarchy(hier);
    make_token(session_token, sizeof(session_token));
    strncpy(hierarchy_buf, hier, sizeof(hierarchy_buf) - 1);
    occupied      = true;
    robot_running = true;
    last_tick_ms  = millis();

    char resp[128];
    snprintf(resp, sizeof(resp),
        "{\"status\":\"running\",\"session\":\"%s\",\"behaviors\":%d}",
        session_token, n);
    send_json(client, resp);

    Serial.print(F("RUN  session=")); Serial.print(session_token);
    Serial.print(F("  behaviors=")); Serial.println(n);
}

void handle_stop(WiFiClient& client, const char* request) {
    const char* body_start = strstr(request, "\r\n\r\n");
    if (!body_start) { send_error(client, 400, "no body"); return; }
    body_start += 4;

    char tok[32];
    if (!extract_json_string(body_start, "session", tok, sizeof(tok))) {
        send_error(client, 400, "missing session");
        return;
    }

    if (!occupied || strcmp(tok, session_token) != 0) {
        send_error(client, 403, "invalid session");
        Serial.print(F("STOP rejected: bad token ")); Serial.println(tok);
        return;
    }

    robot_running  = false;
    occupied       = false;
    session_token[0] = '\0';
    hierarchy_buf[0] = '\0';
    active_count   = 0;
    clear_lock();
    halt();

    send_json(client, "{\"status\":\"idle\"}");
    Serial.println(F("STOP → idle"));
}

void handle_state(WiFiClient& client) {
    // Build JSON state dump
    char body[512];
    char hier_names[128] = "[";
    for (int i = 0; i < active_count; i++) {
        if (i > 0) strncat(hier_names, ",", sizeof(hier_names) - strlen(hier_names) - 1);
        strncat(hier_names, "\"", sizeof(hier_names) - strlen(hier_names) - 1);
        strncat(hier_names, active[i].entry->name, sizeof(hier_names) - strlen(hier_names) - 1);
        strncat(hier_names, "\"", sizeof(hier_names) - strlen(hier_names) - 1);
    }
    strncat(hier_names, "]", sizeof(hier_names) - strlen(hier_names) - 1);

    snprintf(body, sizeof(body),
        "{\"status\":\"%s\","
        "\"session\":\"%s\","
        "\"hierarchy\":%s,"
        "\"sensors\":{"
        "\"contact_front\":%s,"
        "\"contact_rear\":%s,"
        "\"ir_raw\":%d,"
        "\"ldr_left\":%d,"
        "\"ldr_right\":%d},"
        "\"lock\":{\"active\":%s,\"remaining_ms\":%ld}}",
        occupied ? "busy" : "idle",
        session_token,
        hier_names,
        sensors.contact_front ? "true" : "false",
        sensors.contact_rear  ? "true" : "false",
        sensors.ir_raw,
        sensors.ldr_left,
        sensors.ldr_right,
        is_locked() ? "true" : "false",
        is_locked() ? (long)(lock_until_ms - millis()) : 0L
    );
    send_json(client, body);
}

void handle_reset(WiFiClient& client) {
    robot_running  = false;
    occupied       = false;
    session_token[0] = '\0';
    hierarchy_buf[0] = '\0';
    active_count   = 0;
    clear_lock();
    halt();
    sensors = {false, false, 0, 512, 512};
    send_json(client, "{\"status\":\"idle\",\"message\":\"reset\"}");
    Serial.println(F("RESET → idle"));
}

void handle_tick(WiFiClient& client, const char* request) {
    // Extract first line to get URL
    char url[128];
    strncpy(url, request, sizeof(url) - 1);
    url[sizeof(url)-1] = '\0';
    // Null-terminate at first space after the path
    char* sp = strchr(url + 4, ' ');
    if (sp) *sp = '\0';

    if (!occupied) {
        send_error(client, 400, "no run active — POST /run first");
        return;
    }

    // Override sensor values from query params if provided
    if (strstr(url, "?")) {
        sensors.contact_front = extract_query_bool(url, "contact_f", sensors.contact_front);
        sensors.contact_rear  = extract_query_bool(url, "contact_r", sensors.contact_rear);
        sensors.ir_raw        = extract_query_int(url, "ir",    sensors.ir_raw);
        sensors.ldr_left      = extract_query_int(url, "ldr_l", sensors.ldr_left);
        sensors.ldr_right     = extract_query_int(url, "ldr_r", sensors.ldr_right);
    } else {
        // No injected values — read real sensors
        read_real_sensors();
    }

    char fired[32];
    int  idx = run_one_tick(fired, sizeof(fired));

    char body[256];
    snprintf(body, sizeof(body),
        "{\"fired\":\"%s\","
        "\"locked\":%s,"
        "\"remaining_ms\":%ld,"
        "\"sensors\":{"
        "\"contact_front\":%s,"
        "\"contact_rear\":%s,"
        "\"ir_raw\":%d,"
        "\"ldr_left\":%d,"
        "\"ldr_right\":%d}}",
        fired,
        is_locked() ? "true" : "false",
        is_locked() ? (long)(lock_until_ms - millis()) : 0L,
        sensors.contact_front ? "true" : "false",
        sensors.contact_rear  ? "true" : "false",
        sensors.ir_raw,
        sensors.ldr_left,
        sensors.ldr_right
    );
    send_json(client, body);

    Serial.print(F("TICK → ")); Serial.println(fired);
}

// ── HTTP request dispatcher ────────────────────────────────────────────────

void http_dispatch(WiFiClient& client, const char* request) {
    if      (strncmp(request, "GET /ping",   9) == 0) handle_ping(client);
    else if (strncmp(request, "GET /state", 10) == 0) handle_state(client);
    else if (strncmp(request, "GET /tick",   9) == 0) handle_tick(client, request);
    else if (strncmp(request, "POST /run",   9) == 0) handle_run(client, request);
    else if (strncmp(request, "POST /stop", 10) == 0) handle_stop(client, request);
    else if (strncmp(request, "POST /reset",11) == 0) handle_reset(client);
    else {
        send_error(client, 404, "not found");
        Serial.print(F("404: ")); Serial.println(request);
    }
}

// ── Serial command handling (kept from hierarchy_serial for debugging) ──────

char serial_buf[256];
int  serial_idx = 0;

void parse_serial_sensors(const char* args) {
    char buf[128];
    strncpy(buf, args, sizeof(buf) - 1);
    char* token = strtok(buf, ",");
    while (token) {
        char* eq = strchr(token, '=');
        if (eq) {
            *eq = '\0';
            int val = atoi(eq + 1);
            if      (strcmp(token, "contact_f") == 0) sensors.contact_front = (val != 0);
            else if (strcmp(token, "contact_r") == 0) sensors.contact_rear  = (val != 0);
            else if (strcmp(token, "ir")        == 0) sensors.ir_raw        = val;
            else if (strcmp(token, "ldr_l")     == 0) sensors.ldr_left      = val;
            else if (strcmp(token, "ldr_r")     == 0) sensors.ldr_right     = val;
        }
        token = strtok(NULL, ",");
    }
    Serial.println(F("Sensors updated."));
}

void dispatch_serial(char* line) {
    int len = strlen(line);
    while (len > 0 && (line[len-1]=='\r'||line[len-1]=='\n'||line[len-1]==' '))
        line[--len] = '\0';
    if (len == 0) return;

    if (strncmp(line, "sensors:", 8) == 0) {
        parse_serial_sensors(line + 8);
    } else if (strncmp(line, "tick", 4) == 0) {
        if (active_count == 0) {
            Serial.println(F("No hierarchy loaded."));
            return;
        }
        read_real_sensors();
        char fired[32];
        run_one_tick(fired, sizeof(fired));
        Serial.print(F("Fired: ")); Serial.println(fired);
    } else if (strcmp(line, "status") == 0) {
        Serial.print(F("Status: "));  Serial.println(occupied ? "busy" : "idle");
        Serial.print(F("Running: ")); Serial.println(robot_running ? "yes" : "no");
        Serial.print(F("Behaviors: ")); Serial.println(active_count);
        Serial.print(F("IR: "));   Serial.println(sensors.ir_raw);
        Serial.print(F("LDR L: ")); Serial.println(sensors.ldr_left);
        Serial.print(F("LDR R: ")); Serial.println(sensors.ldr_right);
    } else if (strcmp(line, "halt") == 0) {
        halt();
        Serial.println(F("Halted."));
    } else if (strcmp(line, "real") == 0) {
        read_real_sensors();
        Serial.print(F("IR=")); Serial.print(sensors.ir_raw);
        Serial.print(F(" LDR_L=")); Serial.print(sensors.ldr_left);
        Serial.print(F(" LDR_R=")); Serial.println(sensors.ldr_right);
    } else {
        Serial.print(F("Unknown: ")); Serial.println(line);
        Serial.println(F("Commands: sensors:, tick, status, halt, real"));
    }
}

void read_serial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (serial_idx > 0) {
                serial_buf[serial_idx] = '\0';
                dispatch_serial(serial_buf);
                serial_idx = 0;
            }
        } else if (serial_idx < (int)sizeof(serial_buf) - 1) {
            serial_buf[serial_idx++] = c;
        }
    }
}

// ── Setup ──────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000);

    Serial.println(F("\n=== Robot Ethology WiFi ==="));

    // Hardware
    servoLeft.attach(PIN_SERVO_LEFT);
    servoRight.attach(PIN_SERVO_RIGHT);
    halt();

    pinMode(PIN_CONTACT_FRONT, INPUT_PULLUP);
    pinMode(PIN_CONTACT_REAR,  INPUT_PULLUP);

    Serial.println(F("Hardware: OK"));

    // WiFi
    Serial.print(F("Connecting to ")); Serial.print(WIFI_SSID); Serial.print(F("..."));
    int attempts = 0;
    while (WiFi.begin(WIFI_SSID, WIFI_PASS) != WL_CONNECTED) {
        delay(1000);
        Serial.print('.');
        if (++attempts >= 20) {
            Serial.println(F("\nWiFi FAILED. Halting."));
            while (true);
        }
    }
    Serial.println(F(" connected"));
    Serial.print(F("IP: ")); Serial.println(WiFi.localIP());

    server.begin();
    Serial.println(F("HTTP server on port 80"));
    Serial.println(F("Ready. POST /run to start.\n"));
}

// ── Loop ───────────────────────────────────────────────────────────────────

void loop() {
    // Run autonomous robot tick if active
    robot_tick_loop();

    // Read Serial debug commands
    read_serial();

    // Handle HTTP clients
    WiFiClient client = server.available();
    if (!client) return;

    char request[512];
    read_request(client, request, sizeof(request));
    if (strlen(request) > 0) {
        http_dispatch(client, request);
    }
    client.stop();
}
