# IBVAP — 6-slide SIH PPT content

Drop directly into the **official SIH template** (not built as a standalone
deck here, since the template is mandatory and I don't have it on hand).
Bullets kept short and visual-first per the submission requirements — treat
each bullet as a label for a diagram/icon/screenshot, not a sentence to read
aloud off the slide.

---

## Slide 1 — Title / mandatory fields

- **Problem Statement ID:** 26187
- **Title:** AI-Based Intelligent Video Analytics Platform for Border
  Surveillance using existing CCTV Infrastructure
- **Organization:** Ministry of Home Affairs (MHA)
- **Department:** Sashastra Seema Bal (SSB), Police II Division
- **Category:** Software | **Theme:** Smart Automation
- **Team name / members** — [fill in]
- **Solution name:** IBVAP — Intelligent Border Video Analytics Platform
- *[Visual: team logo/name + one establishing image of a border CCTV setup]*

## Slide 2 — Solution & USP

- **One line:** Turn any standard CCTV into an intelligent border sentinel —
  no new hardware, just smart software.
- Software-only AI layer over existing IP CCTV — no FRS/ANPR hardware
- **USPs:**
  - Hardware-agnostic — works with cameras SSB already owns
  - Edge-first — analytics run at the BOP, only metadata + clips go upstream
  - Watchlist operations — offline enrollment, live match, audit trail
  - Virtual fence editor — operator-drawn polygons/tripwires per camera
  - Explainable alerts — every alert states *why* it fired, not a black-box
    score
- *[Visual: before/after — "plain CCTV" vs "IBVAP dashboard" side by side]*

## Slide 3 — Technical approach & architecture

- **3-layer architecture:**
  1. Edge/Video Ingestion — RTSP/ONVIF → local server, on-prem
  2. AI Analytics Microservices — Detection (YOLOv8/v10), Tracking
     (ByteTrack/BoT-SORT), ANPR (EasyOCR/PaddleOCR), Rules (fence/loitering/
     night)
  3. Command, Alerting & Logging — WebSocket dashboard, Telegram/SMS, SQLite
     event store, webhook to external C2
- **Flow:** IP-CCTV → Edge Ingestion → AI Workers → Backend API → Dashboard
  + Alerts + External C2
- Target: end-to-end alert under 1-2s per stream on a mid-range GPU
- *[Visual: the 3-layer flow diagram — this slide should be almost all
  diagram, minimal text]*

## Slide 4 — Feasibility & risk mitigation

- **Feasibility:**
  - Software-only — no procurement, deployable on cameras already in service
  - Pretrained models (YOLO/ByteTrack/OCR) — no training pipeline needed
  - GPU rented, not purchased — scales cost with deployment, not upfront capex
- **Risks & mitigations:**
  - RTSP drops in the field → auto-reconnect with backoff, per-stream
    isolation (one camera failing doesn't affect others)
  - Low-bandwidth remote sites → edge-first processing, only metadata/short
    clips transmitted upstream
  - ANPR accuracy under poor lighting/angle → confidence threshold, fails
    closed (no match) rather than guessing
  - Scale to many BOPs → stateless microservices, horizontally scalable per
    camera/site
- *[Visual: simple risk → mitigation table, 4 rows max]*

## Slide 5 — Target audience impact & benefits

- **Primary users:** SSB personnel at Border Out Posts, check posts, sector
  command centers
- **Benefits:**
  - Reduces continuous manual monitoring burden on personnel
  - Faster response — real-time alerts vs. passive recording
  - Lower cost than proprietary smart-camera hardware at the same scale
  - Audit trail for every alert — accountability and after-action review
  - Deployable across the large set of BOPs that already have CCTV but no
    intelligence layer today
- *[Visual: icon row — personnel, response time, cost, audit trail]*

## Slide 6 — Related work / references

- **CIBMS (BSF multi-sensor smart fencing):** hardware-heavy (thermal,
  radar, ground sensors), high capex, sector-level — IBVAP is software-only,
  low capex, site-level, complementary rather than competing
- **Commercial products (Irisity, Intozi, Senstar):** proprietary, often
  cloud-centric — IBVAP is edge-first and explainable
- **Precedent:** BSF's 2026 Unified AI Platform (RTSP → AI analytics →
  alerts) validates this architecture direction; SSB has already procured
  CCTV with FRS/ANPR, confirming these capabilities are expected
- *[Visual: simple comparison table — CIBMS / commercial / IBVAP across
  capex, deployment speed, hardware dependency]*

---

## Notes
- Keep every slide visual-first — flowcharts, icons, screenshots over
  paragraphs, per the submission requirements.
- Slide 3's architecture diagram and slide 4's risk table are the two most
  worth spending extra polish time on — they're what a technical judge will
  actually scrutinize.
- Demo video link goes in the PPT (title or close slide) once it's hosted —
  see the submission checklist.
