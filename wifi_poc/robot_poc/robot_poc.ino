/*
 * robot_poc.ino
 * -------------
 * Proof-of-concept: Arduino hosts a WiFi access point and a simple
 * HTTP server.  A Python client can:
 *
 *   POST /run   — send a hierarchy + session token, start "running"
 *   POST /stop  — send session token, stop "running"
 *   GET  /ping  — check status
 *
 * No real robot behavior here — just validates the full comms stack
 * before anything is tied into robosim.
 *
 * Compatible with:
 *   Uno R4 WiFi   (WiFiS3.h)
 *   Giga R1 WiFi  (WiFi.h from Arduino_MKRWiFi1010 or WiFiNINA)
 *
 * To switch between boards, change the #include and WiFi object below.
 * Everything else is identical.
 *
 * Network:
 *   SSID     : ROBOT_AP
 *   Password : robotpass
 *   IP       : 192.168.4.1   (assigned automatically by AP mode)
 *   Port     : 80
 */

// ── Board selection ────────────────────────────────────────────────────────
// Uno R4 WiFi:
#include <WiFiS3.h>
// Giga R1 WiFi — comment out the line above and uncomment below:
// #include <WiFi.h>

// ── AP credentials ─────────────────────────────────────────────────────────
const char* AP_SSID = "ROBOT_AP";
const char* AP_PASS = "robotpass";   // min 8 chars for WPA2

// ── Server ─────────────────────────────────────────────────────────────────
WiFiServer server(80);

// ── Session / state ────────────────────────────────────────────────────────
bool     occupied      = false;
char     session_token[32] = "";   // token held by current client
char     hierarchy_buf[256] = "";  // last received hierarchy (raw JSON array)

// ── Helpers ────────────────────────────────────────────────────────────────

/*
 * Read the full HTTP request from client into buf (up to buf_len-1 bytes).
 * Returns number of bytes read.  Waits up to TIMEOUT_MS for data.
 */
int read_request(WiFiClient& client, char* buf, int buf_len) {
  const unsigned long TIMEOUT_MS = 2000;
  unsigned long start = millis();
  int idx = 0;

  while (client.connected() && (millis() - start < TIMEOUT_MS)) {
    while (client.available() && idx < buf_len - 1) {
      buf[idx++] = client.read();
      start = millis();   // reset timeout on each byte received
    }
    // Stop reading once we have a blank line + body (crude but sufficient for POC)
    if (idx > 4 &&
        buf[idx-4] == '\r' && buf[idx-3] == '\n' &&
        buf[idx-2] == '\r' && buf[idx-1] == '\n') {
      // Headers done, no body yet — keep reading until timeout
    }
  }
  buf[idx] = '\0';
  return idx;
}

/*
 * Extract a JSON string value for a given key from a flat JSON object.
 * e.g. extract_json_string(src, "session", out, sizeof(out))
 * Handles only simple string values (no nesting).
 * Returns true on success.
 */
bool extract_json_string(const char* src, const char* key, char* out, int out_len) {
  // Look for  "key":"value"  or  "key": "value"
  char search[48];
  snprintf(search, sizeof(search), "\"%s\"", key);
  const char* p = strstr(src, search);
  if (!p) return false;
  p += strlen(search);
  while (*p == ' ' || *p == ':') p++;
  if (*p != '"') return false;
  p++;   // skip opening quote
  int i = 0;
  while (*p && *p != '"' && i < out_len - 1) {
    out[i++] = *p++;
  }
  out[i] = '\0';
  return i > 0;
}

/*
 * Extract a JSON array (as raw text) for a given key.
 * e.g.  "hierarchy": ["a","b"]  → copies  ["a","b"]  into out.
 */
bool extract_json_array(const char* src, const char* key, char* out, int out_len) {
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
    else if (*p == ']') { depth--; out[i++] = *p++; if (depth == 0) break; continue; }
    out[i++] = *p++;
  }
  out[i] = '\0';
  return i > 0;
}

/*
 * Send an HTTP 200 JSON response.
 */
void send_json(WiFiClient& client, const char* body) {
  client.print("HTTP/1.1 200 OK\r\n");
  client.print("Content-Type: application/json\r\n");
  client.print("Connection: close\r\n");
  client.print("\r\n");
  client.print(body);
}

/*
 * Send an HTTP error response.
 */
void send_error(WiFiClient& client, int code, const char* msg) {
  char status[8];
  snprintf(status, sizeof(status), "%d", code);
  client.print("HTTP/1.1 ");
  client.print(status);
  client.print(" Error\r\n");
  client.print("Content-Type: application/json\r\n");
  client.print("Connection: close\r\n");
  client.print("\r\n");
  client.print("{\"error\":\"");
  client.print(msg);
  client.print("\"}");
}

/*
 * Generate a simple session token from millis() + a counter.
 * Not cryptographic — just unique enough for one classroom.
 */
void make_token(char* out, int out_len) {
  static unsigned int counter = 0;
  snprintf(out, out_len, "s%lu_%u", millis(), counter++);
}

// ── Route handlers ─────────────────────────────────────────────────────────

void handle_ping(WiFiClient& client) {
  char body[128];
  snprintf(body, sizeof(body),
    "{\"status\":\"%s\",\"session\":\"%s\"}",
    occupied ? "busy" : "idle",
    occupied ? session_token : "");
  send_json(client, body);

  Serial.print("PING → status: ");
  Serial.println(occupied ? "busy" : "idle");
}

void handle_run(WiFiClient& client, const char* request) {
  // Find JSON body (after the blank line \r\n\r\n)
  const char* body_start = strstr(request, "\r\n\r\n");
  if (!body_start) { send_error(client, 400, "no body"); return; }
  body_start += 4;

  if (occupied) {
    send_error(client, 503, "busy");
    Serial.println("RUN rejected: busy");
    return;
  }

  // Extract hierarchy array
  char hier[200];
  if (!extract_json_array(body_start, "hierarchy", hier, sizeof(hier))) {
    send_error(client, 400, "missing hierarchy");
    return;
  }

  // Generate session token
  make_token(session_token, sizeof(session_token));
  strncpy(hierarchy_buf, hier, sizeof(hierarchy_buf) - 1);
  occupied = true;

  char resp[128];
  snprintf(resp, sizeof(resp),
    "{\"status\":\"running\",\"session\":\"%s\"}", session_token);
  send_json(client, resp);

  Serial.print("RUN started  session=");
  Serial.print(session_token);
  Serial.print("  hierarchy=");
  Serial.println(hierarchy_buf);
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
    Serial.print("STOP rejected: bad token ");
    Serial.println(tok);
    return;
  }

  occupied = false;
  session_token[0] = '\0';
  hierarchy_buf[0]  = '\0';

  send_json(client, "{\"status\":\"idle\"}");
  Serial.println("STOP accepted → idle");
}

// ── Route dispatcher ────────────────────────────────────────────────────────

void dispatch(WiFiClient& client, const char* request) {
  // Identify method + path from first line
  if (strncmp(request, "GET /ping",  9) == 0) { handle_ping(client); return; }
  if (strncmp(request, "POST /run",  9) == 0) { handle_run(client, request);  return; }
  if (strncmp(request, "POST /stop", 10) == 0) { handle_stop(client, request); return; }

  send_error(client, 404, "not found");
  Serial.print("404: ");
  Serial.println(request);   // prints first line only (rest is also there but readable)
}

// ── Setup ──────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);   // wait for Serial Monitor (up to 3s)

  Serial.println("\n=== Robot POC starting ===");

  // Start AP
  Serial.print("Starting AP \"");
  Serial.print(AP_SSID);
  Serial.print("\" ...");

  int status = WiFi.beginAP(AP_SSID, AP_PASS);
  if (status != WL_AP_LISTENING) {
    Serial.println(" FAILED.  Halting.");
    while (true);
  }
  Serial.println(" OK");

  // The AP always assigns itself 192.168.4.1 in the Arduino WiFi libraries
  Serial.print("AP IP: ");
  Serial.println(WiFi.localIP());

  server.begin();
  Serial.println("HTTP server listening on port 80");
  Serial.println("Ready.\n");
}

// ── Loop ───────────────────────────────────────────────────────────────────

void loop() {
  WiFiClient client = server.available();
  if (!client) return;

  Serial.println("-- client connected --");

  char request[512];
  read_request(client, request, sizeof(request));

  if (strlen(request) > 0) {
    dispatch(client, request);
  }

  client.stop();
  Serial.println("-- client disconnected --");
}
