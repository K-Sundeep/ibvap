# IBVAP — final demo video shot list

Locked structure for submission. Record intro/close and each live-demo beat
as **separate clips** and edit together — don't do one continuous take.
Have a backup recording of each beat from an earlier successful run in case
today's live capture has a bad take.

Total: ~2:20 (fits the 2-3 min window with room to spare if a beat runs long).

---

| Time | Segment | Visual | Voiceover / on-screen text | Notes |
|---|---|---|---|---|
| 0:00-0:10 | **Intro** | IBVAP logo/title slide, PS 26187 + team name | "IBVAP — Intelligent Border Video Analytics Platform." | Static slide, no narration rush — let it read. |
| 0:10-0:30 | **Problem → Solution** | Split: plain CCTV feed (or a still) → cut to IBVAP dashboard | "Border out-posts already run CCTV, but it only records — someone has to watch. Proprietary FRS/ANPR hardware to add intelligence is too costly to deploy at scale. IBVAP turns the CCTV they already have into an intelligent sentinel — no new hardware, just software." | Keep the cut fast — one problem beat, one solution beat, don't linger on either. |
| 0:30-1:45 | **Live demo — core loop** | Screen recording, dashboard | (see beat-by-beat below) | This is the graded core of the video — the fence intrusion loop, live and unedited within the clip. |
| 1:45-2:05 | **Wow module — ANPR** | Screen recording, ANPR zone camera | "Same explainable-alert pattern extends to vehicles: a plate matching the watchlist fires an alert with the match and the evidence." | Only include if today's Go/No-Go confirmed ANPR is reliable — see fallback below. |
| 2:05-2:20 | **Close — impact** | Cut back to logo/title slide | "Deployable in days, not months — turning every BOP's existing CCTV into an intelligence layer, without a single new camera." | End on the same slide as the intro for a clean bookend. |

### Live demo beat-by-beat (0:30-1:45)
Straight from `docs/test_scenario.md` — don't deviate from the rehearsed run:
1. Dashboard open, cam1 (and at least one other camera tile) live — proves
   multi-stream ingest at a glance, even though the fence test is on cam1.
2. Fence overlay already visible on cam1 (pre-drawn, not live-edited).
3. Test clip plays — tracking box + ID visible on the person as they walk.
4. Person crosses the line → alert appears in AlertsFeed within ~1-2s →
   EventLog updates in the same shot.
5. Brief zoom/highlight on the alert's snapshot + reason text ("track
   crossed virtual line") with voiceover: *"every alert states why it
   fired — not a black-box score."*

### If ANPR isn't reliable by today
Cut segment to: 0:30-1:55 live demo (absorb the extra 10s into a slightly
longer close on the fence beat), skip straight to close. Don't include a
shaky ANPR take just to check the box — a clean 2:00 video beats a 2:20
video with a visible stumble in it.

---

## Recording checklist before hitting record
- [ ] Same fixed test clip and fence from `docs/test_scenario.md` — untouched
- [ ] Screen resolution/zoom level checked so text in the UI is readable in
      the final video, not just on your monitor
- [ ] No other RTSP client (VLC/ffplay) open anywhere — single-client
      listen mode will silently drop the ingest connection
- [ ] Audio levels checked on a short test recording first
- [ ] Backup clip of a known-good run saved separately, filename-labeled,
      before attempting the "real" take
