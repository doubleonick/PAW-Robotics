#include "CogCamera.h"

// ---- constructors -----------------------------------------------------------
CogCamera::CogCamera(std::initializer_list<uint8_t> signatures,
                     const std::array<const char*, 7>& sigNames,
                     uint8_t maxBlocks)
: _sigmap(makeSigmap(signatures)),
  _maxBlocks(maxBlocks),
  _sigNames(sigNames)
{
    // Lazy init on first call
    clearHistory(0);
}

CogCamera::CogCamera(uint8_t sigmap,
                     const std::array<const char*, 7>& sigNames,
                     uint8_t maxBlocks)
: _sigmap(sigmap & 0x7F),
  _maxBlocks(maxBlocks),
  _sigNames(sigNames)
{
    clearHistory(0);
}

// ---- configuration ----------------------------------------------------------
void CogCamera::setSignatures(std::initializer_list<uint8_t> signatures)
{
    _sigmap = makeSigmap(signatures);
}

void CogCamera::setSigmap(uint8_t sigmap)
{
    _sigmap = (sigmap & 0x7F);
}

void CogCamera::setSignatureNames(const std::array<const char*, 7>& sigNames)
{
    _sigNames = sigNames;
}

void CogCamera::setWindow(uint8_t frames)
{
    if (frames < 1) frames = 1;
    if (frames > MAX_WINDOW) frames = MAX_WINDOW;
    _window = frames;

    // Trim counts if needed (don’t need to rewrite content)
    for (uint8_t i = 0; i < 7; ++i) {
        if (_histCount[i] > _window) _histCount[i] = _window;
    }
}

void CogCamera::clearHistory(uint8_t signature)
{
    if (signature == 0) {
        for (uint8_t s = 0; s < 7; ++s) {
            _histHead[s] = 0;
            _histCount[s] = 0;
            for (uint8_t k = 0; k < MAX_WINDOW; ++k) {
                _hist[s][k].valid = false;
                _hist[s][k].frame = 0;
            }
        }
        _frameCounter = 0;
    } else if (signature >= 1 && signature <= 7) {
        uint8_t idx = signature - 1;
        _histHead[idx]  = 0;
        _histCount[idx] = 0;
        for (uint8_t k = 0; k < MAX_WINDOW; ++k) {
            _hist[idx][k].valid = false;
            _hist[idx][k].frame = 0;
        }
    }
}

// ---- acquisition ------------------------------------------------------------
int CogCamera::getBlocks(bool waitForFrame)
{
    ensureInit();

    // Fetch blocks for the selected signatures (no color-codes)
    int8_t rc = _pixy.ccc.getBlocks(waitForFrame, _sigmap, _maxBlocks);
    if (rc < 0) return rc;

    // One frame advanced; update history from current block list
    ++_frameCounter;
    updateHistoryFromCurrentFrame();

    return _pixy.ccc.numBlocks;
}

// ---- raw access -------------------------------------------------------------
uint8_t CogCamera::numBlocks() const       { return _pixy.ccc.numBlocks; }
int32_t CogCamera::frameWidth() const      { return _pixy.frameWidth;    }
int32_t CogCamera::frameHeight() const     { return _pixy.frameHeight;   }
const decltype(((PixyLink*)nullptr)->ccc.blocks)& CogCamera::blocks() const
{
    return _pixy.ccc.blocks;
}

// ---- numeric signature helpers ---------------------------------------------
int CogCamera::findFirstBySignature(uint16_t signature) const
{
    for (uint8_t i = 0; i < _pixy.ccc.numBlocks; ++i)
        if (_pixy.ccc.blocks[i].m_signature == signature)
            return i;
    return -1;
}

uint8_t CogCamera::countBySignature(uint8_t signature) const
{
    if (signature < 1 || signature > 7) return 0;
    uint8_t count = 0;
    for (uint8_t i = 0; i < _pixy.ccc.numBlocks; ++i)
        if (_pixy.ccc.blocks[i].m_signature == signature)
            ++count;
    return count;
}

bool CogCamera::getBlockBySignature(uint8_t signature, uint8_t index, CogBlockView& out) const
{
    if (signature < 1 || signature > 7) return false;

    uint8_t seen = 0;
    for (uint8_t i = 0; i < _pixy.ccc.numBlocks; ++i) {
        const auto& b = _pixy.ccc.blocks[i];
        if (b.m_signature == signature) {
            if (seen == index) {
                out.signature = b.m_signature;
                out.x         = b.m_x;
                out.y         = b.m_y;
                out.width     = b.m_width;
                out.height    = b.m_height;
                out.area      = static_cast<uint32_t>(b.m_width) * b.m_height;
                out.age       = b.m_age;
                return true;
            }
            ++seen;
        }
    }
    return false;
}

// ---- name helpers -----------------------------------------------------------
const char* CogCamera::nameFor(uint16_t signature) const
{
    if (signature >= 1 && signature <= 7)
        return _sigNames[signature - 1];
    return nullptr;
}

uint8_t CogCamera::countByName(const char* signatureName) const
{
    uint8_t sig = signatureFromName(signatureName);
    return countBySignature(sig);
}

bool CogCamera::getBlockByName(const char* signatureName, uint8_t index, CogBlockView& out) const
{
    uint8_t sig = signatureFromName(signatureName);
    if (sig == 0) return false;
    return getBlockBySignature(sig, index, out);
}

// ---- sliding-window "largest block" filter ---------------------------------
bool CogCamera::largestOverWindowBySignature(uint8_t signature, CogBlockView& out) const
{
    if (signature < 1 || signature > 7) return false;
    const uint8_t sIdx = signature - 1;

    if (_histCount[sIdx] == 0) return false;

    bool     found = false;
    uint32_t bestArea = 0;

    // Scan the last _histCount entries (<= _window) for this signature
    const uint8_t count = _histCount[sIdx];
    uint8_t head = _histHead[sIdx];

    for (uint8_t i = 0; i < count; ++i) {
        // Walk backward from head-1, wrapping
        uint8_t pos = (head + MAX_WINDOW - 1 - i) % MAX_WINDOW;
        const HistEntry& e = _hist[sIdx][pos];
        if (!e.valid) continue;

        if (!found || e.b.area > bestArea) {
            bestArea = e.b.area;
            out      = e.b;
            found    = true;
        }
    }
    return found;
}

bool CogCamera::largestOverWindowByName(const char* signatureName, CogBlockView& out) const
{
    uint8_t sig = signatureFromName(signatureName);
    if (sig == 0) return false;
    return largestOverWindowBySignature(sig, out);
}

// ---- optional utilities -----------------------------------------------------
void CogCamera::setLamp(uint8_t upperOn, uint8_t lowerOn)
{
    ensureInit();
    _pixy.setLamp(upperOn, lowerOn);
}

void CogCamera::setLED(uint8_t r, uint8_t g, uint8_t b)
{
    ensureInit();
    _pixy.setLED(r, g, b);
}

// ---- helpers ----------------------------------------------------------------
uint8_t CogCamera::makeSigmap(std::initializer_list<uint8_t> sigs)
{
    uint8_t mask = 0;
    for (uint8_t s : sigs)
        if (s >= 1 && s <= 7)
            mask |= (1u << (s - 1));
    return mask;
}

void CogCamera::ensureInit()
{
    if (_initialized) return;
    _pixy.init();                                   // must init before use
    _pixy.changeProg("color_connected_components"); // safe even on newer FW
    _initialized = true;
}

uint8_t CogCamera::signatureFromName(const char* signatureName) const
{
    if (!signatureName || !*signatureName) return 0;
    for (uint8_t i = 0; i < 7; ++i) {
        const char* nm = _sigNames[i];
        if (nm && strcmp(nm, signatureName) == 0)
            return i + 1;
    }
    return 0; // not found
}

void CogCamera::pushHist(uint8_t signature, const HistEntry& e)
{
    if (signature < 1 || signature > 7) return;
    uint8_t sIdx = signature - 1;

    // Write at head
    _hist[sIdx][_histHead[sIdx]] = e;

    // Advance head
    _histHead[sIdx] = (_histHead[sIdx] + 1) % MAX_WINDOW;

    // Grow count up to window size
    if (_histCount[sIdx] < _window) {
        _histCount[sIdx]++;
    }
    // If already at _window length, we overwrite in ring fashion (OK)
}

void CogCamera::updateHistoryFromCurrentFrame()
{
    // For each signature 1..7, find largest block in this frame and push one entry
    // Only consider signatures that are enabled in _sigmap to avoid filling with irrelevant data.
    struct Accum {
        bool     found;
        CogBlockView best;
    } acc[7];

    for (uint8_t s = 0; s < 7; ++s) {
        acc[s].found = false;
        acc[s].best  = CogBlockView{};
    }

    // Evaluate current frame blocks
    for (uint8_t i = 0; i < _pixy.ccc.numBlocks; ++i) {
        const auto& b = _pixy.ccc.blocks[i];
        if (b.m_signature < 1 || b.m_signature > 7) continue;

        // Skip if signature is not enabled in our sigmap
        uint8_t bit = 1u << (b.m_signature - 1);
        if ( (_sigmap & bit) == 0 ) continue;

        uint32_t area = static_cast<uint32_t>(b.m_width) * b.m_height;
        Accum& a = acc[b.m_signature - 1];
        if (!a.found || area > a.best.area) {
            a.found           = true;
            a.best.signature  = b.m_signature;
            a.best.x          = b.m_x;
            a.best.y          = b.m_y;
            a.best.width      = b.m_width;
            a.best.height     = b.m_height;
            a.best.area       = area;
            a.best.age        = b.m_age;
        }
    }

    // Push one entry per signature: either valid best, or an invalid placeholder
    for (uint8_t s = 1; s <= 7; ++s) {
        // Respect sigmap: only maintain history for watched signatures
        if ( (_sigmap & (1u << (s - 1))) == 0 ) continue;

        HistEntry e;
        e.frame = _frameCounter;

        if (acc[s - 1].found) {
            e.valid = true;
            e.b     = acc[s - 1].best;
        } else {
            e.valid = false; // no detection this frame for this signature
            e.b     = CogBlockView{};
            e.b.signature = s;
        }
        pushHist(s, e);
    }
}