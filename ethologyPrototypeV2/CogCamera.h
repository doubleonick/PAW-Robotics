#ifndef COGCAMERA_H
#define COGCAMERA_H

#include <Arduino.h>
#include <array>
#include <string.h> // for strcmp

// -------- Transport selection (default SPI via Pixy2.h) ---------------------
#if defined(COGCAM_LINK_I2C)
  #include <Pixy2I2C.h>
  using PixyLink = Pixy2I2C;
#elif defined(COGCAM_LINK_UART)
  #include <Pixy2UART.h>
  using PixyLink = Pixy2UART;
#elif defined(COGCAM_LINK_SPI_SS)
  #include <Pixy2SPI_SS.h>
  using PixyLink = Pixy2SPI_SS;
#else
  #include <Pixy2.h>  // SPI (ICSP) default
  using PixyLink = Pixy2;
#endif
// ----------------------------------------------------------------------------

class CogCamera {
public:
    // Lightweight view of a block (computed area = width*height)
    struct CogBlockView {
        uint16_t signature;  // 1..7
        int16_t  x;          // center x (0..316 typical)
        int16_t  y;          // center y (0..208 typical)
        uint16_t width;      // pixels
        uint16_t height;     // pixels
        uint32_t area;       // width * height
        uint16_t age;        // frames tracked
    };

    // ---- construction ------------------------------------------------------
    explicit CogCamera(std::initializer_list<uint8_t> signatures,
                       const std::array<const char*, 7>& sigNames = {nullptr,nullptr,nullptr,nullptr,nullptr,nullptr,nullptr},
                       uint8_t maxBlocks = 0xFF);

    explicit CogCamera(uint8_t sigmap = 0x7F, // bits 0..6 == sig1..sig7
                       const std::array<const char*, 7>& sigNames = {nullptr,nullptr,nullptr,nullptr,nullptr,nullptr,nullptr},
                       uint8_t maxBlocks = 0xFF);

    // ---- configuration -----------------------------------------------------
    void setSignatures(std::initializer_list<uint8_t> signatures);
    void setSigmap(uint8_t sigmap); // only bits 0..6 honored
    void setSignatureNames(const std::array<const char*, 7>& sigNames);

    // Sliding-window size (frames). 1..MAX_WINDOW. Default = 5.
    void setWindow(uint8_t frames);
    uint8_t window() const { return _window; }

    // Clear history (sig=0 clears all; 1..7 clears that signature only)
    void clearHistory(uint8_t signature = 0);

    // ---- acquisition -------------------------------------------------------
    // Grabs new blocks and updates history. Returns >=0 (#blocks) or <0 on error.
    int getBlocks(bool waitForFrame = true);

    // ---- raw access --------------------------------------------------------
    uint8_t numBlocks() const;
    int32_t frameWidth() const;
    int32_t frameHeight() const;
    const decltype(((PixyLink*)nullptr)->ccc.blocks)& blocks() const;

    // ---- numeric signature helpers ----------------------------------------
    int         findFirstBySignature(uint16_t signature) const;
    uint8_t     countBySignature(uint8_t signature) const;
    bool        getBlockBySignature(uint8_t signature, uint8_t index, CogBlockView& out) const;

    // ---- name helpers ------------------------------------------------------
    const char* nameFor(uint16_t signature) const;
    uint8_t     countByName(const char* signatureName) const;
    bool        getBlockByName(const char* signatureName, uint8_t index, CogBlockView& out) const;

    // ---- sliding-window "largest block" filter -----------------------------
    bool largestOverWindowBySignature(uint8_t signature, CogBlockView& out) const;
    bool largestOverWindowByName(const char* signatureName, CogBlockView& out) const;

    // ---- optional utilities ------------------------------------------------
    void setLamp(uint8_t upperOn, uint8_t lowerOn);
    void setLED(uint8_t r, uint8_t g, uint8_t b);

private:
    // ===== internals ========================================================
    PixyLink _pixy;
    bool     _initialized = false;
    uint8_t  _sigmap      = 0x7F;     // bits 0..6 (sigs 1..7)
    uint8_t  _maxBlocks   = 0xFF;

    std::array<const char*, 7> _sigNames{};

    // ---- history ring buffers ---------------------------------------------
    static constexpr uint8_t MAX_WINDOW = 20;  // upper bound to bound SRAM use
    uint8_t  _window       = 5;               // active window length
    uint32_t _frameCounter = 0;               // increments on each getBlocks()

    struct HistEntry {
        bool         valid;
        CogBlockView b;
        uint32_t     frame; // frame index when captured
    };

    // One ring buffer per signature (1..7), each with MAX_WINDOW slots
    HistEntry _hist[7][MAX_WINDOW];
    uint8_t   _histHead[7]  = {0,0,0,0,0,0,0}; // next write index per sig
    uint8_t   _histCount[7] = {0,0,0,0,0,0,0}; // number of valid entries per sig (<= _window)

    // ---- helpers -----------------------------------------------------------
    static uint8_t makeSigmap(std::initializer_list<uint8_t> sigs);
    void    ensureInit();
    uint8_t signatureFromName(const char* signatureName) const;

    // Per-frame ingestion: record largest block per signature into history
    void    updateHistoryFromCurrentFrame();

    // Push a single entry into ring for given signature (1..7)
    void    pushHist(uint8_t signature, const HistEntry& e);
};

#endif // COGCAMERA_H