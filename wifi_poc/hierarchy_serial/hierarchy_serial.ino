/*
 * hierarchy_serial.ino
 * ---------------------
 * Serial-only proof of concept for the runtime behavior dispatch system.
 *
 * NO WiFi.  NO real sensors or motors.
 * Sensor readings are injected via Serial commands so the dispatch logic
 * can be tested exhaustively before any hardware is involved.
 *
 * What this sketch validates
 * --------------------------
 *  1. JSON hierarchy string → function-pointer dispatch table
 *  2. Correct behavior fires given injected sensor state
 *  3. Behavior lock: timed behaviors (escape_*) suppress lower-priority
 *     behaviors for their full duration
 *  4. Unknown behavior names are skipped gracefully
 *  5. The registry is the single source of truth — adding a behavior
 *     means adding one entry to the registry; nothing else changes
 *
 * Serial commands (send via Serial Monitor, line ending = newline)
 * ---------------------------------------------------------------
 *  hierarchy:["escape_front","avoid_object","seek_light","cruise_straight"]
 *      Load a new hierarchy from a JSON array string.
 *      Same format the WiFi server will receive from Python.
 *
 *  sensors:contact_f=1,contact_r=0,ir=0,ldr_l=200,ldr_r=180
 *      Inject fake sensor readings.
 *      All fields optional — omitted fields keep their previous value.
 *      contact_f / contact_r : 1 = bumper pressed, 0 = clear
 *      ir                    : raw IR value (0–1023; threshold is 400)
 *      ldr_l / ldr_r         : LDR raw values (0–1023)
 *
 *  tick
 *      Run one iteration of the hierarchy with current sensor state.
 *      Prints which behavior fired (or "none — all conditions false").
 *
 *  tick:N
 *      Run N ticks, printing each.  e.g. tick:10
 *
 *  auto:on / auto:off
 *      Continuously run ticks at ~20 Hz (like a real robot loop).
 *      Useful for watching the lock timer expire in real time.
 *
 *  status
 *      Print current hierarchy, sensor state, and lock state.
 *
 *  reset
 *      Clear hierarchy, reset sensors, clear lock.
 *
 * Example session
 * ---------------
 *  > hierarchy:["escape_front","avoid_object","cruise_straight"]
 *  Hierarchy loaded: 3 behaviors
 *    [0] escape_front
 *    [1] avoid_object
 *    [2] cruise_straight
 *
 *  > sensors:contact_f=1
 *  Sensors updated: contact_f=1
 *
 *  > tick
 *  Tick 1: ESCAPE_FRONT fired  [locked for 2000ms]
 *
 *  > tick
 *  Tick 2: ESCAPE_FRONT locked  (850ms remaining)
 *
 *  > sensors:contact_f=0,ir=600
 *  Sensors updated: contact_f=0 ir=600
 *
 *  > tick
 *  Tick 3: ESCAPE_FRONT locked  (420ms remaining)   ← lock suppresses avoid
 *
 *  (after lock expires)
 *  > tick
 *  Tick 4: AVOID_OBJECT fired
 *
 *  > sensors:ir=0
 *  > tick
 *  Tick 5: CRUISE_STRAIGHT fired
 */

#include <string.h>
#include <stdlib.h>

// ── Constants ──────────────────────────────────────────────────────────────

#define MAX_BEHAVIORS   16      // max behaviors in a single hierarchy
#define ESCAPE_MS       2000UL  // lock duration for escape behaviors (ms)
#define IR_THRESHOLD    400     // raw ADC value above which IR "sees" obstacle
#define LDR_DIFF_MIN    30      // minimum L/R LDR difference to act on gradient

// ── Fake sensor state ──────────────────────────────────────────────────────
// In a real sketch these would be read from hardware pins.

struct SensorState {
    bool  contact_front;    // front bumper
    bool  contact_rear;     // rear bumper
    int   ir_raw;           // raw IR proximity value (0–1023)
    int   ldr_left;         // left LDR raw value  (0–1023)
    int   ldr_right;        // right LDR raw value (0–1023)
} sensors = {false, false, 0, 512, 512};

// ── Behavior lock ──────────────────────────────────────────────────────────
// When a timed behavior fires it sets lock_until_ms.
// All condition checks return false while a lock is active,
// except for the behavior that owns the lock.

unsigned long lock_until_ms   = 0;
int           lock_owner_idx  = -1;   // index in active hierarchy

bool is_locked() {
    return (lock_owner_idx >= 0) && (millis() < lock_until_ms);
}

void set_lock(int owner_idx) {
    lock_until_ms  = millis() + ESCAPE_MS;
    lock_owner_idx = owner_idx;
}

void clear_lock() {
    lock_until_ms  = 0;
    lock_owner_idx = -1;
}

// ── Condition functions ────────────────────────────────────────────────────
// Each returns true when the behavior's trigger condition is met.
// They consult only the fake sensor state — no hardware reads.

bool cond_front_contact()    { return sensors.contact_front; }
bool cond_rear_contact()     { return sensors.contact_rear; }
bool cond_proximity()        { return sensors.ir_raw >= IR_THRESHOLD; }
bool cond_light_gradient()   {
    return abs(sensors.ldr_left - sensors.ldr_right) >= LDR_DIFF_MIN;
}
bool cond_always()           { return true; }   // cruise behaviors always eligible

// ── Action functions ───────────────────────────────────────────────────────
// In a real sketch these would drive servos.
// Here they just print a description.

void act_escape_front()   { Serial.println("  action: reverse arc away from front obstacle"); }
void act_escape_rear()    { Serial.println("  action: spin away from rear obstacle"); }
void act_avoid_object()   { Serial.println("  action: arc away from nearer IR side"); }
void act_approach_object(){ Serial.println("  action: arc toward nearer IR side"); }
void act_seek_light()     { Serial.println("  action: arc toward brighter LDR side"); }
void act_avoid_light()    { Serial.println("  action: arc away from brighter LDR side"); }
void act_cruise_straight(){ Serial.println("  action: drive straight"); }
void act_cruise_arc()     { Serial.println("  action: drive gentle arc"); }

// ── Registry ───────────────────────────────────────────────────────────────
// The complete catalog of all known behaviors.
// To add a behavior: add one entry here.  Nothing else changes.

struct RegistryEntry {
    const char* name;           // must match Python BEHAVIOR_MAP key exactly
    bool (*condition)();
    void (*action)();
    bool timed;                 // true = behavior sets lock when it fires
};

const RegistryEntry REGISTRY[] = {
    { "escape_front",    cond_front_contact,    act_escape_front,    true  },
    { "escape_rear",     cond_rear_contact,     act_escape_rear,     true  },
    { "avoid_object",    cond_proximity,        act_avoid_object,    false },
    { "approach_object", cond_proximity,        act_approach_object, false },
    { "seek_light",      cond_light_gradient,   act_seek_light,      false },
    { "avoid_light",     cond_light_gradient,   act_avoid_light,     false },
    { "cruise_straight", cond_always,           act_cruise_straight, false },
    { "cruise_arc",      cond_always,           act_cruise_arc,      false },
};
const int REGISTRY_SIZE = sizeof(REGISTRY) / sizeof(REGISTRY[0]);

// ── Active hierarchy ───────────────────────────────────────────────────────
// Populated at runtime by parse_hierarchy().

struct BehaviorSlot {
    const RegistryEntry* entry;   // pointer into REGISTRY (never null if active)
    int                  reg_idx; // index into REGISTRY (for lock owner tracking)
};

BehaviorSlot active[MAX_BEHAVIORS];
int          active_count = 0;

// ── Registry lookup ────────────────────────────────────────────────────────

int find_in_registry(const char* name) {
    for (int i = 0; i < REGISTRY_SIZE; i++) {
        if (strcmp(REGISTRY[i].name, name) == 0) return i;
    }
    return -1;
}

// ── JSON array parser ──────────────────────────────────────────────────────
/*
 * Parses:  ["escape_front","avoid_object","cruise_straight"]
 * Extracts each quoted token and looks it up in the registry.
 * Populates active[] and active_count.
 *
 * Tolerant of extra whitespace.  Does not require a full JSON library.
 * Returns number of behaviors successfully loaded.
 */
int parse_hierarchy(const char* json) {
    clear_lock();
    active_count = 0;

    const char* p = json;
    while (*p && *p != '[') p++;   // find opening bracket
    if (!*p) return 0;
    p++;

    char token[32];

    while (*p && *p != ']' && active_count < MAX_BEHAVIORS) {
        // skip to next quote
        while (*p && *p != '"' && *p != ']') p++;
        if (!*p || *p == ']') break;
        p++;   // skip opening quote

        // copy token until closing quote
        int ti = 0;
        while (*p && *p != '"' && ti < (int)sizeof(token) - 1) {
            token[ti++] = *p++;
        }
        token[ti] = '\0';
        if (*p == '"') p++;   // skip closing quote

        if (ti == 0) continue;

        int idx = find_in_registry(token);
        if (idx >= 0) {
            active[active_count].entry   = &REGISTRY[idx];
            active[active_count].reg_idx = idx;
            active_count++;
        } else {
            Serial.print("  WARNING: unknown behavior '");
            Serial.print(token);
            Serial.println("' — skipped");
        }
    }

    return active_count;
}

// ── Dispatch: run one tick ─────────────────────────────────────────────────
/*
 * Iterates the active hierarchy from highest to lowest priority.
 * Fires the first behavior whose condition is met.
 *
 * If a timed behavior currently holds the lock:
 *   - If the lock owner's condition is still met (or lock hasn't expired),
 *     the owner continues running.
 *   - If the lock has expired, it is cleared and normal evaluation resumes.
 *
 * Returns the index of the fired behavior, or -1 if none fired.
 */
int run_one_tick(int tick_num) {
    Serial.print("Tick ");
    Serial.print(tick_num);
    Serial.print(": ");

    // Check if a lock is active
    if (is_locked()) {
        unsigned long remaining = lock_until_ms - millis();
        const char* owner_name = active[lock_owner_idx].entry->name;

        // Print lock owner name in upper case for readability
        char upper[32];
        int i = 0;
        while (owner_name[i] && i < 31) {
            upper[i] = (owner_name[i] >= 'a' && owner_name[i] <= 'z')
                       ? owner_name[i] - 32 : owner_name[i];
            i++;
        }
        upper[i] = '\0';

        Serial.print(upper);
        Serial.print(" locked  (");
        Serial.print(remaining);
        Serial.println("ms remaining)");
        active[lock_owner_idx].entry->action();
        return lock_owner_idx;
    }

    // Normal evaluation: first condition that is true wins
    for (int i = 0; i < active_count; i++) {
        if (active[i].entry->condition()) {
            const char* name = active[i].entry->name;

            // Print behavior name in upper case
            char upper[32];
            int j = 0;
            while (name[j] && j < 31) {
                upper[j] = (name[j] >= 'a' && name[j] <= 'z')
                           ? name[j] - 32 : name[j];
                j++;
            }
            upper[j] = '\0';

            Serial.print(upper);
            Serial.print(" fired");

            if (active[i].entry->timed) {
                set_lock(i);
                Serial.print("  [locked for ");
                Serial.print(ESCAPE_MS);
                Serial.println("ms]");
            } else {
                Serial.println();
            }

            active[i].entry->action();
            return i;
        }
    }

    Serial.println("none — all conditions false");
    return -1;
}

// ── Status printer ─────────────────────────────────────────────────────────

void print_status() {
    Serial.println("--- Status ---");

    Serial.print("Hierarchy (");
    Serial.print(active_count);
    Serial.println(" behaviors):");
    for (int i = 0; i < active_count; i++) {
        Serial.print("  [");
        Serial.print(i);
        Serial.print("] ");
        Serial.println(active[i].entry->name);
    }

    Serial.println("Sensors:");
    Serial.print("  contact_front="); Serial.println(sensors.contact_front ? "1" : "0");
    Serial.print("  contact_rear ="); Serial.println(sensors.contact_rear  ? "1" : "0");
    Serial.print("  ir_raw       ="); Serial.println(sensors.ir_raw);
    Serial.print("  ldr_left     ="); Serial.println(sensors.ldr_left);
    Serial.print("  ldr_right    ="); Serial.println(sensors.ldr_right);

    Serial.print("Lock: ");
    if (is_locked()) {
        Serial.print("ACTIVE — owner=");
        Serial.print(active[lock_owner_idx].entry->name);
        Serial.print("  remaining=");
        Serial.print(lock_until_ms - millis());
        Serial.println("ms");
    } else {
        Serial.println("none");
    }
    Serial.println("--------------");
}

// ── Sensor command parser ──────────────────────────────────────────────────
/*
 * Parses:  contact_f=1,contact_r=0,ir=500,ldr_l=300,ldr_r=200
 * Each key=value pair is optional.
 */
void parse_sensors(const char* args) {
    char buf[128];
    strncpy(buf, args, sizeof(buf) - 1);
    buf[sizeof(buf)-1] = '\0';

    Serial.print("Sensors updated:");
    char* token = strtok(buf, ",");
    while (token) {
        char* eq = strchr(token, '=');
        if (eq) {
            *eq = '\0';
            const char* key = token;
            int val = atoi(eq + 1);
            if      (strcmp(key, "contact_f") == 0) { sensors.contact_front = (val != 0); Serial.print(" contact_f="); Serial.print(val); }
            else if (strcmp(key, "contact_r") == 0) { sensors.contact_rear  = (val != 0); Serial.print(" contact_r="); Serial.print(val); }
            else if (strcmp(key, "ir")        == 0) { sensors.ir_raw        = val;        Serial.print(" ir=");        Serial.print(val); }
            else if (strcmp(key, "ldr_l")     == 0) { sensors.ldr_left      = val;        Serial.print(" ldr_l=");     Serial.print(val); }
            else if (strcmp(key, "ldr_r")     == 0) { sensors.ldr_right     = val;        Serial.print(" ldr_r=");     Serial.print(val); }
            else { Serial.print(" [unknown key: "); Serial.print(key); Serial.print("]"); }
        }
        token = strtok(NULL, ",");
    }
    Serial.println();
}

// ── Command dispatcher ─────────────────────────────────────────────────────

static int  tick_counter = 0;
static bool auto_mode    = false;
static unsigned long last_auto_ms = 0;

void dispatch_command(char* line) {
    // Strip trailing whitespace / CR
    int len = strlen(line);
    while (len > 0 && (line[len-1] == '\r' || line[len-1] == '\n' || line[len-1] == ' ')) {
        line[--len] = '\0';
    }
    if (len == 0) return;

    // ── hierarchy:[ ... ] ────────────────────────────────────────────────
    if (strncmp(line, "hierarchy:", 10) == 0) {
        int n = parse_hierarchy(line + 10);
        Serial.print("Hierarchy loaded: ");
        Serial.print(n);
        Serial.println(" behaviors");
        for (int i = 0; i < active_count; i++) {
            Serial.print("  [");
            Serial.print(i);
            Serial.print("] ");
            Serial.println(active[i].entry->name);
        }
        return;
    }

    // ── sensors:... ─────────────────────────────────────────────────────
    if (strncmp(line, "sensors:", 8) == 0) {
        parse_sensors(line + 8);
        return;
    }

    // ── tick or tick:N ───────────────────────────────────────────────────
    if (strncmp(line, "tick", 4) == 0) {
        if (active_count == 0) {
            Serial.println("No hierarchy loaded.  Send: hierarchy:[\"...\"]");
            return;
        }
        int n = 1;
        if (line[4] == ':') n = max(1, atoi(line + 5));
        for (int i = 0; i < n; i++) {
            run_one_tick(++tick_counter);
        }
        return;
    }

    // ── auto:on / auto:off ───────────────────────────────────────────────
    if (strcmp(line, "auto:on") == 0) {
        if (active_count == 0) {
            Serial.println("No hierarchy loaded.  Load one first.");
            return;
        }
        auto_mode    = true;
        last_auto_ms = millis();
        Serial.println("Auto mode ON  (20 Hz).  Send 'auto:off' to stop.");
        return;
    }
    if (strcmp(line, "auto:off") == 0) {
        auto_mode = false;
        Serial.println("Auto mode OFF.");
        return;
    }

    // ── status ───────────────────────────────────────────────────────────
    if (strcmp(line, "status") == 0) {
        print_status();
        return;
    }

    // ── reset ────────────────────────────────────────────────────────────
    if (strcmp(line, "reset") == 0) {
        active_count = 0;
        clear_lock();
        sensors = {false, false, 0, 512, 512};
        tick_counter = 0;
        auto_mode    = false;
        Serial.println("Reset complete.");
        return;
    }

    // ── help ─────────────────────────────────────────────────────────────
    if (strcmp(line, "help") == 0) {
        Serial.println("Commands:");
        Serial.println("  hierarchy:[\"name1\",\"name2\",...]  load hierarchy");
        Serial.println("  sensors:contact_f=1,ir=500,...    inject sensor values");
        Serial.println("  tick                              run one tick");
        Serial.println("  tick:N                            run N ticks");
        Serial.println("  auto:on / auto:off                continuous 20Hz ticks");
        Serial.println("  status                            show current state");
        Serial.println("  reset                             clear everything");
        Serial.println("Known behaviors:");
        for (int i = 0; i < REGISTRY_SIZE; i++) {
            Serial.print("  ");
            Serial.print(REGISTRY[i].name);
            if (REGISTRY[i].timed) Serial.print("  (timed)");
            Serial.println();
        }
        return;
    }

    Serial.print("Unknown command: '");
    Serial.print(line);
    Serial.println("'  (send 'help' for command list)");
}

// ── Serial line reader ─────────────────────────────────────────────────────

char serial_buf[256];
int  serial_idx = 0;

void read_serial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (serial_idx > 0) {
                serial_buf[serial_idx] = '\0';
                dispatch_command(serial_buf);
                serial_idx = 0;
            }
        } else if (serial_idx < (int)sizeof(serial_buf) - 1) {
            serial_buf[serial_idx++] = c;
        }
    }
}

// ── Setup / loop ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000);

    Serial.println();
    Serial.println("=== Hierarchy Dispatch — Serial Test Harness ===");
    Serial.println("Send 'help' for command list.");
    Serial.println();
}

void loop() {
    read_serial();

    // Auto-tick at ~20 Hz
    if (auto_mode && active_count > 0) {
        unsigned long now = millis();
        if (now - last_auto_ms >= 50) {
            last_auto_ms = now;
            run_one_tick(++tick_counter);
        }
    }
}
