# IBVAP — ANPR demo scenario (Phase 3)

Same philosophy as `docs/test_scenario.md`: one fixed setup, rehearsed until
it's reliable, not varied on demo day. Scope matches the project doc —
ANPR confined to a single controlled zone, not general-purpose.

---

## Fixed setup

- **Camera / zone:** one dedicated ANPR camera (or a tightly cropped ROI on
  an existing camera) framing a single-lane approach — a gate, checkpoint,
  or narrow road segment where exactly one vehicle is in frame at a time.
- **Blacklist enrollment:** enroll one clearly fictional demo plate ahead of
  time — e.g. `KA01ZZ0001` — through whatever enrollment UI/flow exists.
  Do this **before** recording, not live; enrollment is a data-entry step,
  not something worth burning demo time or risk on. A quick screenshot of
  the enrolled entry is enough to show it exists.
- **Vehicle clip:** a single vehicle, plate clearly legible, moving at a
  slow/walking-equivalent pace toward the camera, near-frontal angle
  (avoid steep side angles). One pass only — no other vehicles in frame.
  Reliability > realism for the demo take; a harder clip is a good stress
  test for later, not for the recorded run.

## Rehearsal sequence

1. Show the dashboard with the ANPR zone camera live, blacklist already
   enrolled (brief cut to the enrollment screen/screenshot).
2. Vehicle clip plays — plate should stay in frame long enough for at least
   a few consecutive readable frames before it exits.
3. Plate ROI box appears around the plate on the live feed (if the UI draws
   it) — visible proof detection is running, not just OCR happening
   invisibly in the background.
4. OCR'd plate text appears, matched against the blacklist.
5. Alert fires in AlertsFeed: camera_id, matched plate string, a snapshot
   crop of the plate (and ideally the full vehicle), reason text like
   "plate matched blacklist: KA01ZZ0001" — same explainable-alert pattern
   as the intrusion alerts.
6. EventLog updates with the same event.
7. `python scripts/query_events.py --camera_id <anpr_camera_id> --type
   watchlist_hit` (adjust `--type` to whatever the CV/ML lead actually
   named it) confirms the row, same as the fence test.

**Keep it to this single clean pass for the recorded take.** A second
vehicle or a non-blacklisted plate as a contrast beat is a nice stretch
goal if there's rehearsal time left over, but don't add it at the cost of
reliability on the one match that matters.

---

## Likely failure modes + one-line mitigations (for judge Q&A)

**1. Motion blur from vehicle speed.**
Fast-moving vehicles smear the plate across frames, making individual
characters unrecognizable to OCR.
*Mitigation:* the demo zone is scoped to slow-approach areas (gates,
checkpoints) where vehicles are naturally moving slowly anyway — this
matches real BOP checkpoint conditions, not a demo-only shortcut. In
production, the system samples multiple frames and OCRs the sharpest one
rather than committing to a single blurry frame.

**2. Plate angle and low-resolution crops.**
A steep side angle or a plate that's small in-frame (vehicle far from
camera) both degrade character legibility for OCR.
*Mitigation:* the pipeline includes a perspective-correction step before
OCR, and — just as importantly — a minimum crop-size/confidence threshold
that rejects the read rather than guessing. A missed read is far better
than a wrong blacklist match; the system is tuned to fail closed, not to
force an answer from a bad crop.

**3. Poor lighting / glare (night, headlights, direct sun).**
Low light or glare on the plate surface is the hardest of the three —
honest answer, not fully solved by software alone at this scope.
*Mitigation:* for this sprint, ANPR is scoped to daylight/well-lit zones;
under poor lighting the system lowers confidence and defers to human
review rather than asserting a match. Production deployment would pair
this with IR-capable cameras at night, which is a hardware change outside
this software-only PS scope — worth stating plainly if asked, rather than
overclaiming what a pure-software layer can fix.
