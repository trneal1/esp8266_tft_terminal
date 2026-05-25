/*
 * ESP8266 Remote Terminal over TCP  (v9 — ILI9341 / ST7796 / ST7735 Edition)
 * ─────────────────────────────────────────────────────────────────────────────
 * Listens on TCP port 8888 for newline-delimited JSON commands that control
 * an Adafruit GFX-compatible SPI display.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 *  SUPPORTED DISPLAYS
 * ─────────────────────────────────────────────────────────────────────────────
 *  SPI displays (MOSI/MISO/SCK on default SPI pins; CS/DC/RST configured below)
 *   DISPLAY_ILI9341      Adafruit_ILI9341    240×320   2.4 / 2.8 in
 *   DISPLAY_ST7796       Adafruit_ST7796S    320×480   4 in
 *   DISPLAY_ST7735       Adafruit_ST7735     128×128 or 128×160   1.8 in
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * DEPENDENCIES (Arduino Library Manager):
 *   ESP8266WiFi    — bundled with the esp8266 board package
 *   ArduinoJson    — v6.x by Benoit Blanchon
 *   Adafruit_GFX   — by Adafruit
 *   + the specific driver library for your chosen display (see above)
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * JSON COMMAND REFERENCE
 * ─────────────────────────────────────────────────────────────────────────────
 * Every command is a single-line JSON object terminated with '\n'.
 * Responses:  {"ok":true}  or  {"ok":false,"error":"<message>"}
 *
 *   {"cmd":"text","x":10,"y":20,"text":"Hello","color":"#FF0000","size":2}
 *   {"cmd":"clear"}
 *   {"cmd":"bg","color":"#001122"}
 *   {"cmd":"fill_rect","x":10,"y":10,"w":100,"h":50,"color":"#00FF00"}
 *   {"cmd":"rect",     "x":10,"y":10,"w":100,"h":50,"color":"#00FF00"}
 *   {"cmd":"fill_circle","x":120,"y":160,"r":40,"color":"#0000FF"}
 *   {"cmd":"circle",     "x":120,"y":160,"r":40,"color":"#0000FF"}
 *   {"cmd":"hline","x":0,"y":60,"len":200,"color":"#FFFFFF"}
 *   {"cmd":"vline","x":60,"y":0,"len":120,"color":"#FFFFFF"}
 *   {"cmd":"line","x0":0,"y0":0,"x1":319,"y1":239,"color":"#FFFFFF"}
 *   {"cmd":"fill_screen","color":"#001830"}
 *   {"cmd":"rotation","r":1}   →  {"ok":true,"w":<w>,"h":<h>}
 *   {"cmd":"pixel","x":120,"y":160,"color":"#FF0000"}
 *   {"cmd":"triangle","x0":10,"y0":10,"x1":50,"y1":80,"x2":90,"y2":10,"color":"#FFFFFF"}
 *   {"cmd":"fill_triangle","x0":10,"y0":10,"x1":50,"y1":80,"x2":90,"y2":10,"color":"#FFFFFF"}
 *   {"cmd":"rounded_rect","x":10,"y":10,"w":100,"h":60,"r":8,"color":"#00FF00"}
 *   {"cmd":"fill_rounded_rect","x":10,"y":10,"w":100,"h":60,"r":8,"color":"#00FF00"}
 *   {"cmd":"brightness","v":128}
 *   {"cmd":"ping"}             →  {"ok":true,"uptime_ms":<ms>}
 *   {"cmd":"query"}            →  {"ok":true,"w":…,"h":…,"rotation":…,"bg":…,"free_heap":…}
 *
 * Color: "#RGB" or "#RRGGBB" hex string, or raw uint16 integer.
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ═══════════════════════════════════════════════════════════════════════════
//  USER CONFIGURATION  ← edit only this section
// ═══════════════════════════════════════════════════════════════════════════

static const char*    WIFI_SSID     = "TRNNET-2G";
static const char*    WIFI_PASSWORD = "ripcord1";
static const uint16_t TCP_PORT      = 8888;
static const uint32_t TCP_CLIENT_IDLE_TIMEOUT_MS = 120000UL;

// mDNS / DHCP hostname.  Leave blank ("") for the ESP8266 SDK default.
static const char*    WIFI_HOSTNAME = "esp_tft3";

// ── Display selection ────────────────────────────────────────────────────
// Uncomment EXACTLY ONE:

#define DISPLAY_ILI9341          // Adafruit_ILI9341   240×320
// #define DISPLAY_ST7796        // Adafruit_ST7796S   320×480
// #define DISPLAY_ST7735        // Adafruit_ST7735    128×128 / 128×160

// ── SPI pin assignments (NodeMCU / Wemos D1 Mini) ───────────────────────
#define TFT_CS    D8  // D8
#define TFT_DC     D1  // D4
#define TFT_RST    0  // D3  — use -1 to skip hardware reset

// ── ST7735 init variant ─────────────────────────────────────────────────
// Only relevant when DISPLAY_ST7735 is selected.
// Options: INITR_BLACKTAB | INITR_GREENTAB | INITR_144GREENTAB | INITR_MINI160x80
#define ST7735_TAB  INITR_BLACKTAB

// ── Screen rotation ──────────────────────────────────────────────────────
// 0=portrait  1=landscape  2=portrait-flip  3=landscape-flip
#define TFT_ROTATION  3

// ── Backlight PWM pin ────────────────────────────────────────────────────
// Set to a GPIO number to enable the "brightness" command.
// -1 disables the feature (no pin driven).
// Do NOT reuse any SPI pin.
#define TFT_BL_PIN   -1

// ═══════════════════════════════════════════════════════════════════════════
//  DISPLAY ABSTRACTION LAYER  — do not edit below this line
// ═══════════════════════════════════════════════════════════════════════════

#include <ESP8266WiFi.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <SPI.h>

// ── Count how many display defines are active ────────────────────────────
#define DISP_COUNT_DEFINED  ( \
    defined(DISPLAY_ILI9341) + \
    defined(DISPLAY_ST7796)  + \
    defined(DISPLAY_ST7735)    \
)
#if DISP_COUNT_DEFINED != 1
  #error "Uncomment EXACTLY ONE DISPLAY_xxx define in the USER CONFIGURATION section."
#endif

// ── Per-driver includes, constructor, and color macros ───────────────────

#if defined(DISPLAY_ILI9341)
  #include <Adafruit_ILI9341.h>
  static Adafruit_ILI9341 tft(TFT_CS, TFT_DC, TFT_RST);
  #define DISP_BEGIN()   tft.begin()
  #define DISP_NAME      "ILI9341"
  #define COLOR_BLACK    ILI9341_BLACK
  #define COLOR_WHITE    ILI9341_WHITE
  #define COLOR_GREEN    ILI9341_GREEN
  #define COLOR_CYAN     ILI9341_CYAN

#elif defined(DISPLAY_ST7796)
  #include <Adafruit_ST7796S.h>
  static Adafruit_ST7796S tft(TFT_CS, TFT_DC, TFT_RST);
  #define DISP_BEGIN()   tft.init()
  #define DISP_NAME      "ST7796"
  #define COLOR_BLACK    ST77XX_BLACK
  #define COLOR_WHITE    ST77XX_WHITE
  #define COLOR_GREEN    ST77XX_GREEN
  #define COLOR_CYAN     ST77XX_CYAN

#elif defined(DISPLAY_ST7735)
  #include <Adafruit_ST7735.h>
  static Adafruit_ST7735 tft(TFT_CS, TFT_DC, TFT_RST);
  #define DISP_BEGIN()   tft.initR(ST7735_TAB)
  #define DISP_NAME      "ST7735"
  #define COLOR_BLACK    ST77XX_BLACK
  #define COLOR_WHITE    ST77XX_WHITE
  #define COLOR_GREEN    ST77XX_GREEN
  #define COLOR_CYAN     ST77XX_CYAN

#endif  // display selection

// SPI TFTs draw immediately; commit is a no-op.
#define DISP_NEEDS_COMMIT 0
#define DISP_COMMIT()     /* nothing */

// ─── Network ─────────────────────────────────────────────────────────────
static WiFiServer server(TCP_PORT);
static WiFiClient client;
static uint32_t lastClientActivityMs = 0;
static char*  lineBuf = nullptr;
static size_t lineCap = 0;
static size_t linePos = 0;

// ─── Runtime state ───────────────────────────────────────────────────────
static uint16_t bgColor = COLOR_BLACK;
static int16_t  DISP_W  = 0;   // set after tft init
static int16_t  DISP_H  = 0;

// Shared scratch buffer for error strings — never nested
static char errBuf[192];

// ═══════════════════════════════════════════════════════════════════════════
//  VALIDATION HELPERS
// ═══════════════════════════════════════════════════════════════════════════

static inline bool isHexDigit(char c) {
    return (c >= '0' && c <= '9') ||
           (c >= 'A' && c <= 'F') ||
           (c >= 'a' && c <= 'f');
}

static bool validateColorString(const char* s, char* errOut, size_t errLen) {
    if (!s || s[0] != '#') {
        snprintf(errOut, errLen,
                 "color \"%s\" must start with '#' (e.g. \"#FF0000\" or \"#F00\")",
                 s ? s : "null");
        return false;
    }
    size_t len = strlen(s + 1);
    if (len != 3 && len != 6) {
        snprintf(errOut, errLen,
                 "color \"%s\": expected 3 or 6 hex digits after '#', got %u",
                 s, (unsigned)len);
        return false;
    }
    for (size_t i = 1; i <= len; ++i) {
        if (!isHexDigit(s[i])) {
            snprintf(errOut, errLen,
                     "color \"%s\": non-hex character '%c' at position %u",
                     s, s[i], (unsigned)i);
            return false;
        }
    }
    return true;
}

static uint16_t hexToColor565(const char* hex) {
    uint32_t rgb = 0;
    size_t len = strlen(hex + 1);
    if (len == 3) {
        char exp[7];
        snprintf(exp, sizeof(exp), "%c%c%c%c%c%c",
                 hex[1], hex[1], hex[2], hex[2], hex[3], hex[3]);
        rgb = strtoul(exp, nullptr, 16);
    } else {
        rgb = strtoul(hex + 1, nullptr, 16);
    }
    return tft.color565((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
}

static bool parseColor(JsonVariant v, const char* field,
                        uint16_t* out, char* errOut, size_t errLen) {
    if (v.isNull()) {
        snprintf(errOut, errLen, "required field \"%s\" (color) is missing", field);
        return false;
    }
    if (v.is<const char*>()) {
        const char* s = v.as<const char*>();
        if (!validateColorString(s, errOut, errLen)) return false;
        *out = hexToColor565(s);
        return true;
    }
    if (v.is<int>()) { *out = (uint16_t)v.as<int>(); return true; }
    snprintf(errOut, errLen,
             "field \"%s\" must be a color string (\"#RRGGBB\") or a uint16 integer", field);
    return false;
}

static bool parseColorOpt(JsonVariant v, const char* field,
                           uint16_t defaultColor,
                           uint16_t* out, char* errOut, size_t errLen) {
    if (v.isNull()) { *out = defaultColor; return true; }
    return parseColor(v, field, out, errOut, errLen);
}

static bool parseCoord(JsonVariant v, const char* field, int16_t maxVal,
                        int16_t* out, char* errOut, size_t errLen) {
    if (v.isNull()) {
        snprintf(errOut, errLen,
                 "required field \"%s\" (integer coordinate) is missing", field);
        return false;
    }
    if (!v.is<int>()) {
        snprintf(errOut, errLen,
                 "field \"%s\" must be an integer [0, %d]", field, (int)maxVal - 1);
        return false;
    }
    int val = v.as<int>();
    if (val < 0 || val >= (int)maxVal) {
        snprintf(errOut, errLen,
                 "field \"%s\"=%d is outside display bounds [0, %d]",
                 field, val, (int)maxVal - 1);
        return false;
    }
    *out = (int16_t)val;
    return true;
}

static bool parseDim(JsonVariant v, const char* field,
                      int16_t* out, char* errOut, size_t errLen) {
    if (v.isNull()) {
        snprintf(errOut, errLen,
                 "required field \"%s\" (positive integer) is missing", field);
        return false;
    }
    if (!v.is<int>()) {
        snprintf(errOut, errLen,
                 "field \"%s\" must be a positive integer, got a non-integer", field);
        return false;
    }
    int val = v.as<int>();
    if (val <= 0) {
        snprintf(errOut, errLen, "field \"%s\"=%d must be greater than 0", field, val);
        return false;
    }
    *out = (int16_t)val;
    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
//  RESPONSE SENDERS
// ═══════════════════════════════════════════════════════════════════════════

static void sendError(const char* msg) {
    if (!client || !client.connected()) return;
    client.print(F("{\"ok\":false,\"error\":\""));
    for (const char* p = msg; *p; ++p) {
        if      (*p == '"')  client.print(F("\\\""));
        else if (*p == '\\') client.print(F("\\\\"));
        else                 client.write((uint8_t)*p);
    }
    client.println(F("\"}"));
    Serial.print(F("[ERR] ")); Serial.println(msg);
}

static void sendOK() {
    if (!client || !client.connected()) return;
    client.println(F("{\"ok\":true}"));
}

static void closeClient(const __FlashStringHelper* reason) {
    if (lineBuf || lastClientActivityMs != 0) {
        Serial.print(F("Client closed: "));
        Serial.println(reason);
    }
    client.stop();
    if (lineBuf) {
        free(lineBuf);
        lineBuf = nullptr;
    }
    lineCap = 0;
    linePos = 0;
    lastClientActivityMs = 0;
}

// ═══════════════════════════════════════════════════════════════════════════
//  COMMAND HANDLERS
// ═══════════════════════════════════════════════════════════════════════════

static void cmdText(JsonDocument& doc) {
    int16_t  x, y;
    uint16_t color;
    if (!parseCoord(doc["x"], "x", DISP_W, &x, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y"], "y", DISP_H, &y, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    JsonVariant tv = doc["text"];
    if (tv.isNull())            { sendError("required field \"text\" is missing"); return; }
    if (!tv.is<const char*>())  { sendError("field \"text\" must be a string"); return; }
    const char* text = tv.as<const char*>();
    if (!text || strlen(text) == 0) { sendError("field \"text\" must not be empty"); return; }
    int sz = 1;
    JsonVariant sv = doc["size"];
    if (!sv.isNull()) {
        if (!sv.is<int>()) { sendError("field \"size\" must be an integer in [1, 8]"); return; }
        sz = sv.as<int>();
        if (sz < 1 || sz > 8) {
            snprintf(errBuf, sizeof(errBuf), "field \"size\"=%d is out of range [1, 8]", sz);
            sendError(errBuf); return;
        }
    }
    if (!parseColorOpt(doc["color"], "color", COLOR_WHITE, &color, errBuf, sizeof(errBuf))) {
        sendError(errBuf); return;
    }
    tft.setCursor(x, y);
    tft.setTextColor(color);
    tft.setTextSize((uint8_t)sz);
    tft.setTextWrap(true);
    tft.print(text);
    DISP_COMMIT();
    sendOK();
}

static void cmdClear(JsonDocument& /*doc*/) {
    tft.fillScreen(bgColor);
    DISP_COMMIT();
    sendOK();
}

static void cmdBg(JsonDocument& doc) {
    uint16_t color;
    if (!parseColor(doc["color"], "color", &color, errBuf, sizeof(errBuf))) {
        sendError(errBuf); return;
    }
    bgColor = color;
    sendOK();
}

static bool extractRect(JsonDocument& doc,
                         int16_t& x, int16_t& y,
                         int16_t& w, int16_t& h, uint16_t& color) {
    if (!parseCoord(doc["x"], "x", DISP_W, &x, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y"], "y", DISP_H, &y, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["w"], "w",         &w, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["h"], "h",         &h, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseColor(doc["color"], "color", &color, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    return true;
}

static void cmdFillRect(JsonDocument& doc) {
    int16_t x, y, w, h; uint16_t c;
    if (!extractRect(doc, x, y, w, h, c)) return;
    tft.fillRect(x, y, w, h, c); DISP_COMMIT(); sendOK();
}

static void cmdRect(JsonDocument& doc) {
    int16_t x, y, w, h; uint16_t c;
    if (!extractRect(doc, x, y, w, h, c)) return;
    tft.drawRect(x, y, w, h, c); DISP_COMMIT(); sendOK();
}

static bool extractCircle(JsonDocument& doc,
                            int16_t& x, int16_t& y,
                            int16_t& r, uint16_t& color) {
    if (!parseCoord(doc["x"], "x", DISP_W, &x, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y"], "y", DISP_H, &y, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["r"], "r",         &r, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseColor(doc["color"], "color", &color, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    return true;
}

static void cmdFillCircle(JsonDocument& doc) {
    int16_t x, y, r; uint16_t c;
    if (!extractCircle(doc, x, y, r, c)) return;
    tft.fillCircle(x, y, r, c); DISP_COMMIT(); sendOK();
}

static void cmdCircle(JsonDocument& doc) {
    int16_t x, y, r; uint16_t c;
    if (!extractCircle(doc, x, y, r, c)) return;
    tft.drawCircle(x, y, r, c); DISP_COMMIT(); sendOK();
}

static void cmdHLine(JsonDocument& doc) {
    int16_t x, y, len; uint16_t c;
    if (!parseCoord(doc["x"],   "x",   DISP_W, &x,   errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y"],   "y",   DISP_H, &y,   errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseDim  (doc["len"], "len",          &len, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseColor(doc["color"], "color", &c,  errBuf, sizeof(errBuf)))       { sendError(errBuf); return; }
    tft.drawFastHLine(x, y, len, c); DISP_COMMIT(); sendOK();
}

static void cmdVLine(JsonDocument& doc) {
    int16_t x, y, len; uint16_t c;
    if (!parseCoord(doc["x"],   "x",   DISP_W, &x,   errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y"],   "y",   DISP_H, &y,   errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseDim  (doc["len"], "len",          &len, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseColor(doc["color"], "color", &c,  errBuf, sizeof(errBuf)))       { sendError(errBuf); return; }
    tft.drawFastVLine(x, y, len, c); DISP_COMMIT(); sendOK();
}

static void cmdLine(JsonDocument& doc) {
    int16_t x0, y0, x1, y1; uint16_t c;
    if (!parseCoord(doc["x0"], "x0", DISP_W, &x0, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y0"], "y0", DISP_H, &y0, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["x1"], "x1", DISP_W, &x1, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y1"], "y1", DISP_H, &y1, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseColor(doc["color"], "color", &c, errBuf, sizeof(errBuf)))     { sendError(errBuf); return; }
    tft.drawLine(x0, y0, x1, y1, c); DISP_COMMIT(); sendOK();
}

static void cmdFillScreen(JsonDocument& doc) {
    uint16_t c;
    if (!parseColor(doc["color"], "color", &c, errBuf, sizeof(errBuf))) {
        sendError(errBuf); return;
    }
    tft.fillScreen(c); DISP_COMMIT(); sendOK();
}

static void cmdRotation(JsonDocument& doc) {
    JsonVariant rv = doc["r"];
    if (rv.isNull())   { sendError("required field \"r\" (rotation) is missing"); return; }
    if (!rv.is<int>()) { sendError("field \"r\" must be an integer: 0=portrait, 1=landscape, 2=portrait-flip, 3=landscape-flip"); return; }
    int rot = rv.as<int>();
    if (rot < 0 || rot > 3) {
        snprintf(errBuf, sizeof(errBuf), "field \"r\"=%d is invalid; must be 0, 1, 2, or 3", rot);
        sendError(errBuf); return;
    }
    tft.setRotation((uint8_t)rot);
    DISP_W = tft.width();
    DISP_H = tft.height();
    Serial.print(F("Rotation=")); Serial.print(rot);
    Serial.print(F("  "));  Serial.print(DISP_W);
    Serial.print('x');      Serial.println(DISP_H);
    if (!client || !client.connected()) return;
    client.print(F("{\"ok\":true,\"w\":"));
    client.print(DISP_W);
    client.print(F(",\"h\":"));
    client.print(DISP_H);
    client.println(F("}"));
}

static void cmdPixel(JsonDocument& doc) {
    int16_t x, y; uint16_t c;
    if (!parseCoord(doc["x"],     "x",     DISP_W, &x, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseCoord(doc["y"],     "y",     DISP_H, &y, errBuf, sizeof(errBuf))) { sendError(errBuf); return; }
    if (!parseColor(doc["color"], "color", &c,      errBuf, sizeof(errBuf)))     { sendError(errBuf); return; }
    tft.drawPixel(x, y, c); DISP_COMMIT(); sendOK();
}

static bool extractTriangle(JsonDocument& doc,
                              int16_t& x0, int16_t& y0,
                              int16_t& x1, int16_t& y1,
                              int16_t& x2, int16_t& y2,
                              uint16_t& color) {
    if (!parseCoord(doc["x0"], "x0", DISP_W, &x0, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y0"], "y0", DISP_H, &y0, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["x1"], "x1", DISP_W, &x1, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y1"], "y1", DISP_H, &y1, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["x2"], "x2", DISP_W, &x2, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y2"], "y2", DISP_H, &y2, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseColor(doc["color"], "color", &color, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    return true;
}

static void cmdTriangle(JsonDocument& doc) {
    int16_t x0, y0, x1, y1, x2, y2; uint16_t c;
    if (!extractTriangle(doc, x0, y0, x1, y1, x2, y2, c)) return;
    tft.drawTriangle(x0, y0, x1, y1, x2, y2, c); DISP_COMMIT(); sendOK();
}

static void cmdFillTriangle(JsonDocument& doc) {
    int16_t x0, y0, x1, y1, x2, y2; uint16_t c;
    if (!extractTriangle(doc, x0, y0, x1, y1, x2, y2, c)) return;
    tft.fillTriangle(x0, y0, x1, y1, x2, y2, c); DISP_COMMIT(); sendOK();
}

static bool extractRoundedRect(JsonDocument& doc,
                                 int16_t& x, int16_t& y,
                                 int16_t& w, int16_t& h,
                                 int16_t& r, uint16_t& color) {
    if (!parseCoord(doc["x"], "x", DISP_W, &x, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseCoord(doc["y"], "y", DISP_H, &y, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["w"], "w",         &w, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["h"], "h",         &h, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseDim  (doc["r"], "r",         &r, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    if (!parseColor(doc["color"], "color", &color, errBuf, sizeof(errBuf))) { sendError(errBuf); return false; }
    return true;
}

static void cmdRoundedRect(JsonDocument& doc) {
    int16_t x, y, w, h, r; uint16_t c;
    if (!extractRoundedRect(doc, x, y, w, h, r, c)) return;
    tft.drawRoundRect(x, y, w, h, r, c); DISP_COMMIT(); sendOK();
}

static void cmdFillRoundedRect(JsonDocument& doc) {
    int16_t x, y, w, h, r; uint16_t c;
    if (!extractRoundedRect(doc, x, y, w, h, r, c)) return;
    tft.fillRoundRect(x, y, w, h, r, c); DISP_COMMIT(); sendOK();
}

static void cmdBrightness(JsonDocument& doc) {
#if TFT_BL_PIN < 0
    sendError("brightness: no backlight pin configured (TFT_BL_PIN is -1)");
#else
    JsonVariant vv = doc["v"];
    if (vv.isNull())   { sendError("required field \"v\" (0-255) is missing"); return; }
    if (!vv.is<int>()) { sendError("field \"v\" must be an integer in [0, 255]"); return; }
    int val = vv.as<int>();
    if (val < 0 || val > 255) {
        snprintf(errBuf, sizeof(errBuf), "field \"v\"=%d is out of range [0, 255]", val);
        sendError(errBuf); return;
    }
    analogWrite(TFT_BL_PIN, val);
    sendOK();
#endif
}

static void cmdPing(JsonDocument& /*doc*/) {
    if (!client || !client.connected()) return;
    client.print(F("{\"ok\":true,\"uptime_ms\":"));
    client.print(millis());
    client.println(F("}"));
}

static void cmdQuery(JsonDocument& /*doc*/) {
    if (!client || !client.connected()) return;
    client.print(F("{\"ok\":true,\"w\":"));
    client.print(DISP_W);
    client.print(F(",\"h\":"));
    client.print(DISP_H);
    client.print(F(",\"rotation\":"));
    client.print((int)tft.getRotation());
    client.print(F(",\"bg\":"));
    client.print(bgColor);
    client.print(F(",\"free_heap\":"));
    client.print(ESP.getFreeHeap());
    client.println(F("}"));
}

// ═══════════════════════════════════════════════════════════════════════════
//  TOP-LEVEL DISPATCHER
// ═══════════════════════════════════════════════════════════════════════════

static void handleCommand(const char* jsonLine) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, jsonLine);
    if (err) {
        snprintf(errBuf, sizeof(errBuf), "JSON parse error: %s", err.c_str());
        sendError(errBuf); return;
    }
    if (!doc.is<JsonObject>()) { sendError("JSON root must be an object { … }"); return; }

    JsonVariant cmdv = doc["cmd"];
    if (cmdv.isNull())           { sendError("missing required field \"cmd\""); return; }
    if (!cmdv.is<const char*>()) { sendError("field \"cmd\" must be a string"); return; }
    const char* cmd = cmdv.as<const char*>();
    if (!cmd || strlen(cmd) == 0) { sendError("field \"cmd\" must not be empty"); return; }

    if      (strcmp(cmd, "text")              == 0) cmdText(doc);
    else if (strcmp(cmd, "clear")             == 0) cmdClear(doc);
    else if (strcmp(cmd, "bg")                == 0) cmdBg(doc);
    else if (strcmp(cmd, "fill_rect")         == 0) cmdFillRect(doc);
    else if (strcmp(cmd, "rect")              == 0) cmdRect(doc);
    else if (strcmp(cmd, "fill_circle")       == 0) cmdFillCircle(doc);
    else if (strcmp(cmd, "circle")            == 0) cmdCircle(doc);
    else if (strcmp(cmd, "hline")             == 0) cmdHLine(doc);
    else if (strcmp(cmd, "vline")             == 0) cmdVLine(doc);
    else if (strcmp(cmd, "line")              == 0) cmdLine(doc);
    else if (strcmp(cmd, "fill_screen")       == 0) cmdFillScreen(doc);
    else if (strcmp(cmd, "rotation")          == 0) cmdRotation(doc);
    else if (strcmp(cmd, "pixel")             == 0) cmdPixel(doc);
    else if (strcmp(cmd, "triangle")          == 0) cmdTriangle(doc);
    else if (strcmp(cmd, "fill_triangle")     == 0) cmdFillTriangle(doc);
    else if (strcmp(cmd, "rounded_rect")      == 0) cmdRoundedRect(doc);
    else if (strcmp(cmd, "fill_rounded_rect") == 0) cmdFillRoundedRect(doc);
    else if (strcmp(cmd, "brightness")        == 0) cmdBrightness(doc);
    else if (strcmp(cmd, "ping")              == 0) cmdPing(doc);
    else if (strcmp(cmd, "query")             == 0) cmdQuery(doc);
    else {
        snprintf(errBuf, sizeof(errBuf),
                 "unknown cmd \"%.*s\"",
                 96,
                 cmd);
        sendError(errBuf);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  ARDUINO SETUP
// ═══════════════════════════════════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    Serial.println(F("\r\nESP8266 TCP Terminal v9 (ILI9341 / ST7796 / ST7735)"));

    DISP_BEGIN();
    Serial.println(F("Driver: " DISP_NAME));

    tft.setRotation(TFT_ROTATION);
    DISP_W = tft.width();
    DISP_H = tft.height();
    Serial.print(F("Display: ")); Serial.print(DISP_W); Serial.print('x'); Serial.println(DISP_H);

#if TFT_BL_PIN >= 0
    pinMode(TFT_BL_PIN, OUTPUT);
    analogWrite(TFT_BL_PIN, 255);
    Serial.print(F("Backlight pin: ")); Serial.println(TFT_BL_PIN);
#endif

    tft.fillScreen(COLOR_BLACK);
    tft.setTextColor(COLOR_CYAN);
    tft.setTextSize(1);
    tft.setCursor(2, 2);
    tft.print(F("Connecting WiFi ..."));

    WiFi.mode(WIFI_STA);
    if (WIFI_HOSTNAME && strlen(WIFI_HOSTNAME) > 0) {
        WiFi.setHostname(WIFI_HOSTNAME);
        Serial.print(F("Hostname: ")); Serial.println(WIFI_HOSTNAME);
    }
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print(F("Connecting"));
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print('.'); }
    Serial.println(F("\r\nConnected"));
    Serial.print(F("IP: ")); Serial.println(WiFi.localIP());
    Serial.print(F("Hostname: ")); Serial.println(WiFi.getHostname());

    tft.fillScreen(COLOR_BLACK);
    tft.setTextColor(COLOR_GREEN);
    tft.setTextSize(1);
    tft.setCursor(2, 2);
    tft.print(F("TCP terminal ready"));
    tft.setCursor(2, 12);
    tft.print(WiFi.localIP());
    tft.print(':');
    tft.print(TCP_PORT);
    if (WIFI_HOSTNAME && strlen(WIFI_HOSTNAME) > 0) {
        tft.setCursor(2, 22);
        tft.print(WiFi.getHostname());
    }

    server.begin();
    server.setNoDelay(true);
}

// ═══════════════════════════════════════════════════════════════════════════
//  ARDUINO LOOP
// ═══════════════════════════════════════════════════════════════════════════

void loop() {
    uint32_t now = millis();

    if (!client || !client.connected()) {
        if (lineBuf || lastClientActivityMs != 0) {
            closeClient(F("disconnected"));
        }
        WiFiClient incoming = server.accept();
        if (incoming) {
            client = incoming;
            lastClientActivityMs = now;
            Serial.print(F("Client: ")); Serial.println(client.remoteIP());
            client.println(F("{\"info\":\"ESP8266 TCP terminal v9 ready\"}"));
        }
    }

    if (client && client.connected()) {
        if (!lineBuf) {
            lineCap = 512;
            lineBuf = (char*)malloc(lineCap);
            if (!lineBuf) { yield(); return; }
        }

        while (client.available()) {
            lastClientActivityMs = now = millis();
            char c = client.read();
            if (c == '\r') continue;
            if (c == '\n') {
                lineBuf[linePos] = '\0';
                int len = (int)linePos;
                linePos = 0;
                if (len == 0) break;
                Serial.print(F("[RX] "));
                if (len <= 120) Serial.println(lineBuf);
                else { Serial.write(lineBuf, 120); Serial.println(F("...")); }
                handleCommand(lineBuf);
                break;
            }

            if (linePos >= lineCap - 1) {
                while (client.available()) { if (client.read() == '\n') break; }
                linePos = 0;
                sendError("command line too long (>511 bytes)");
                break;
            }
            lineBuf[linePos++] = c;
            yield();
        }

        if (!client.connected()) {
            closeClient(F("disconnected"));
        } else if (lastClientActivityMs != 0 &&
                   (uint32_t)(now - lastClientActivityMs) > TCP_CLIENT_IDLE_TIMEOUT_MS) {
            closeClient(F("idle timeout"));
        }
    }

    yield();
}
