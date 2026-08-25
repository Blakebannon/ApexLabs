# Operator runbook — corpus-2026-10-coached-delivery

Ten hours of real capture, twenty recordings, one driver. This is the whole
operating procedure. Read it before the first recording, not during it.

**Nothing in this runbook may be started until the owner has approved the
candidate protocol freeze.** The protocol is `draft` until then, and a draft
cannot be frozen — Apex Labs refuses it.

Owner and Engineering Review Authority: **Blake Bannon**.

---

## 0. What this corpus is, in one paragraph

Twenty 30-minute recordings in **one campaign with two explicit strata**.
Stratum A is the controlled primary: twelve recordings, six within-driver
coached/control pairs, all at Nürburgring GP-Short in the Toyota GR86, in a
frozen exactly balanced order. It is the only stratum the preregistered primary
comparison may use. Stratum B is engineering diversity: eight coached recordings
across Practice, Qualifying, Race and Offline Testing, four cars, three tracks and
two lap profiles. Stratum B is descriptive and observational; it
never enters the primary estimate. The admission gate enforces the separation.

## 1. One recorder invocation is one block and one arm — with exactly one exception

The recorder emits exactly one `collection-condition` marker, at start, carrying
the `--block` and `--condition` you passed on the command line. There is no
mid-session block or condition transition. A within-session A/B is not executable
against this product and must not be improvised by restarting mid-session.

**The one exception is engineering blocks E01 → E02.** That single invocation
produces two bundles, because iRacing itself changes session and the recorder
rolls over. See §6. Every other slot is one invocation, one bundle.

## 2. Before the campaign — once

1. **Owner approves the candidate freeze.** Use the hash sheet issued with the
   current freeze. The 2026-08-24 candidate sheet at
   `F:\ApexResearch\analysis\corpus-readiness-20260824\CANDIDATE-FREEZE-HASHES.txt`
   is **SUPERSEDED**; its hashes must not be treated as current.
2. **Track identities are all resolved.** There are no `OWNER-CONFIRM` sentinels
   left; every track string was read from your own Apex stores and every length
   measured from your own laps. Nothing here needs owner input before the freeze.
   Note the declared limitation in §3: this corpus has **no configuration over
   5 km**, and no analysis may claim a long-lap finding from it.
3. **Create the freeze.** The protocol file must live OUTSIDE the Apex Labs
   repository and the Labs tree must be clean at the commit the protocol names.
   This is not a style preference: `freeze_protocol` requires a clean committed
   Labs tree AND `apex_labs_source_commit == HEAD`, and committing the protocol
   into the repo would change HEAD and break that equality.

   ```powershell
   apex-labs experiment freeze `
     "<the protocol copy named in the approved hash sheet>" `
     --registry "<the registry named in the approved hash sheet>" `
     --frozen-at "<owner-approved UTC instant>" `
     --strategy counterbalanced `
     --method "exactly balanced order assignment, seeded permutation" `
     --seed 20261005 `
     --schedule-id corpus-2026-10-schedule-v2 `
     --schedule (Get-Content -Raw "F:\ApexResearch\analysis\corpus-readiness-20260824\protocol\schedule.json" | ConvertFrom-Json | Select-Object -ExpandProperty schedule | ConvertTo-Json -Depth 10 -Compress)
   ```

4. **Verify the freeze and record its hash.**
   ```powershell
   apex-labs experiment verify-freeze "<the snapshot named in the approved hash sheet>"
   ```
5. **Confirm the product build.** Record the exact `--source-revision`. It must
   not change for the life of the corpus. A product update ends the corpus.
6. **Launch Apex once on the M55 build, and confirm the store carries
   `RecordedUtc`.** As of 2026-08-24 the live coaching stores do **not**:

   | store | rows | `RecordedUtc` |
   |---|---|---|
   | `%LOCALAPPDATA%\ApexSimCoach\desktop` | 644 | absent |
   | `%LOCALAPPDATA%\ApexTrackCoach\desktop` | 2926 | absent |

   Both predate Milestone 55B. `SqliteCoachingEventStore` adds the column on open
   (`ALTER TABLE Events ADD COLUMN RecordedUtc TEXT NULL`), so simply starting the
   M55 build once migrates it. Existing rows stay NULL — that is correct and
   harmless, they are `unavailable_legacy_stream` — and every append from then on
   carries a truthful instant.

   **Until this is done, every control block fails closed** with
   `control-arm-store-predates-recorded-utc`, and the §6b transition check cannot
   answer either. Verify with:

   ```powershell
   apex-labs corpus coaching-binding `
     --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop" `
     --since "2026-01-01T00:00:00Z"
   ```

   `"recorded_utc_available": true` is the pass condition.
7. **Confirm the simulator build.** Same rule.
8. **Save the car setup once per car** and never touch it again. The gate refuses
   a corpus spanning two setup hashes.
9. **Run the transition rehearsal in §6 first**, before any scheduled recording.

## 3. Track and car identity — do not override it

The recorder writes the track identity iRacing reports:
`manifest.session.track.id` from `WeekendInfo:TrackName`, and
`track.layout` from `WeekendInfo:TrackConfigName`, falling back to `TrackName`
when the config name is empty.

**Do not pass `--track` or `--layout`.** An override is an operator claim about
identity rather than a measurement.

**The recorder normalizes what iRacing reports; the schedule is written to the
normalized form.** With no override the recorder applies
`value.Trim().ToLowerInvariant().Replace(' ', '-')` to both WeekendInfo strings,
so the space-separated form held in the Apex coaching stores is *not* what a
bundle carries. The schedule declares the right-hand column and nothing else:

| Configuration | id | `WeekendInfo:TrackName` / `TrackConfigName` | recorder writes `track` / `layout` | measured | observations |
|---|---|---|---|---|---|
| Nürburgring GP-Short | 257 | `nurburgring gpshort` / `nurburgring gpshort` | `nurburgring-gpshort` / `nurburgring-gpshort` | 4567 m | 296 |
| Oulton Park International | 180 | `oulton international` / `International` | `oulton-international` / `international` | 4286 m | 84 |
| Tsukuba 2000 Full | 324 | `tsukuba 2kfull` / `tsukuba 2kfull` | `tsukuba-2kfull` / `tsukuba-2kfull` | 2084 m | 276 |

An earlier revision of this runbook attributed the hyphens in the 2026-08-23
bundles to `--track`/`--layout` overrides. That was wrong: hyphenation is what
the **no-override** path produces, and those bundles are consistent with no
override having been passed. The 2026-10 schedule was originally built from the
Apex-store form and would have been refused `track-mismatch` and
`layout-mismatch` on every block. `tests/test_recorder_identity_normalization.py`
now requires every scheduled identity to be a fixed point of that normalization,
so a schedule declaring a form the recorder cannot produce fails in the test
suite rather than after a recording is driven.

**Declared limitation — no long-lap stratum.** Slot 19 was designed as a >5 km
long-lap slot. No such configuration has a verifiable recorder identity in your
data: an exhaustive read-only scan of 147,660 string cells across both Apex data
roots found eleven track names ever recorded, the longest 4567 m. Nürburgring
Grand Prix Full is installed and was preferred, but you have never driven it, the
iRacing install exposes no readable track-name table, and the folder+config
derivation fails on compound configurations — so adopting it would be guessing a
slug. Nordschleife (20.8 km) and Combined (25.4 km) are your longest installed
layouts and are excluded by design: one to two timed laps in thirty minutes is not
enough repeated clean laps. Slot 19 therefore uses the longest **verified**
layout, `nurburgring-gpshort`, and keeps its engineering value by varying the car
— the Cadillac CTS-V Racecar is the fastest in the corpus, so it probes cue-gap
distribution through speed rather than distance. **The long-lap question is
deferred, not answered.** To restore it: load Nürburgring Grand Prix Full once
with Apex running, read the truthful `TrackName`/`TrackConfigName` back out of the
store, and regenerate.

If a bundle comes back with `track-mismatch` or `layout-mismatch`, the fix is to
correct the schedule to what iRacing actually reported and regenerate — never to
edit the bundle.

## 4. The normal per-recording sequence

This is every slot except E01/E02. One invocation, one bundle, no transition.
**Order matters, and it is not symmetrical.**

### 4a. A coached slot

Stratum A coached arm, and all of stratum B.

1. **Start coaching first.** Apex Sim Coach running from the **unpackaged
   production** install (data root `%LOCALAPPDATA%\ApexSimCoach\desktop`). Press
   **Start Coaching**. Nothing calls `StopCoachingAsync` automatically — the Stop
   Coaching button is its only caller — so coaching stays up until you press it.
2. **Confirm the measured session, not the label.** iRacing must already be in
   the session type the schedule row requires. Read it off the sim. A row that
   says `practice` and a sim in Offline Testing is a wasted 30 minutes.
3. **Confirm car, track, layout, fuel and tyres** against the schedule row.
4. **Start the recorder**, with the row's values pasted, not retyped:

   ```powershell
   ApexTrackCoach.ResearchRecorder.exe record `
     --output-root "F:\ApexResearch\corpus-2026-10" `
     --participant "<pseudonym>" `
     --protocol corpus-2026-10-coached-delivery `
     --block "<the row's block_id>" `
     --condition "<the row's condition_id>" `
     --coaching enabled `
     --simulator-version "<exact iRacing version>" `
     --source-revision "<the frozen 40-char product sha>" `
     --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop"
   ```

5. **Drive 30 minutes.** Watch for `Apex coaching evidence is bound to this live
   session.` — the recorder prints it once, within the first few minutes. If you
   instead see `WARNING: after N minutes of capture, no Apex coaching evidence is
   bound…`, stop and fix `--apex-data-root`; finalization will refuse the bundle.
6. **Stop and finalize the recorder FIRST.** Press Enter. Wait for
   `STOPPING: closing the iRacing source and importing coaching evidence...`
   and then `COMPLETED: <bundle path>`.
7. **Confirm the bundle is COMPLETED** — the `COMPLETE` marker file exists in the
   bundle directory. A bundle without it is `.incomplete` and is not evidence.
8. **Only then press Stop Coaching.** The recorder reads the live Apex store
   during step 6 to import the bound session's coaching evidence. Tearing the
   coaching session down while that read is pending is the one avoidable way to
   lose a finished 30-minute recording.

### 4b. A control slot

Stratum A control arm only. **Read this whole section before the first control
block; the control is the part of this design most easily faked by accident.**

1. **Apex must not be coaching.** Press **Stop Coaching**, or never press Start
   Coaching in the first place. That is the control condition, and it is the only
   one available.

   `--coaching disabled` is a **recorder declaration**, not a product control. It
   makes the recorder skip the coaching-evidence import and write the disabled
   marker. It does not stop Apex from coaching. Muting is not a control either:
   `SetVoiceEnabled` gates the speech engine only, so delivery still happens and
   is still recorded — a muted run is a coached run with the sound off.
2. **iRacing in Offline Testing.** Every stratum A row requires it.
3. **Start the recorder** with the row's values and **`--coaching disabled`**.
   `--apex-data-root` is not required by the recorder for a control block and is
   not used by it.
4. **Drive 30 minutes. No cue should be heard.** If one is, the manipulation
   failed: stop, and re-run the row from the start.
5. **Stop and finalize the recorder, and confirm COMPLETED**, as in §4a steps
   6–7.
6. **Admit the bundle WITH `--apex-data-root`.** This is not optional for a
   control block:

   ```powershell
   apex-labs corpus admit `
     --protocol-snapshot "<snapshot.json>" `
     --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop" `
     "F:\ApexResearch\corpus-2026-10\<session-id>"
   ```

   The gate opens the Apex coaching store read-only (`mode=ro&immutable=1`) and
   uses the Milestone 55B durable append-time `RecordedUtc` to ask whether any
   cue was delivered inside the recording's wall-clock window. Zero delivered
   cues in the window is the proof. This audit is possible only because M55B put
   a truthful append-time UTC on every persisted coaching event; before it, every
   event carried the finalization instant and the question was unanswerable.

7. **The control fails closed.** The gate refuses the block, rather than
   admitting it, whenever it cannot *prove* absence:

   | Refusal | Meaning |
   |---|---|
   | `control-arm-unverified` | No `--apex-data-root` supplied. Absence was never checked. |
   | `control-arm-store-unreadable` | The store is missing or unreadable. |
   | `control-arm-store-predates-recorded-utc` | Pre-M55B store: it cannot place an event in wall-clock time. |
   | `control-block-delivered-cues` | Cues were delivered inside the window. Apex was coaching. |
   | `control-block-missing-disabled-marker` | The bundle does not declare the disabled condition. |

   None of these is annotatable. A control block that cannot be proven silent is
   not a weaker control; it is not a control.

## 5. After every recording

```powershell
ApexTrackCoach.ResearchRecorder.exe validate --bundle "F:\ApexResearch\corpus-2026-10\<session-id>"
apex-labs apex-research inspect "F:\ApexResearch\corpus-2026-10\<session-id>"
```

Then admit it against the freeze **before** driving the next one, so a systematic
mistake costs one recording rather than twenty. A single-bundle admit reports
`schedule-incomplete` at corpus level; that is expected. What matters is the
per-bundle entry: `admitted: true` with no refusals.

### If a bundle is refused

| Refusal | What happened | What to do |
|---|---|---|
| `block-not-in-schedule` | Wrong or mistyped block id | Re-run the scheduled row |
| `condition-mismatch` / `coaching-state-mismatch` | Wrong arm recorded | Re-run the scheduled row |
| `measured-session-type-mismatch` | Wrong iRacing session type | Re-run in the required session type |
| `operator-label-contradicts-measurement` | Label names a different session type | Re-run with correct labels |
| `track-mismatch` / `layout-mismatch` | A `--track`/`--layout` override, or a wrong schedule row | See §3 |
| `timestamp-provenance-legacy` / `-absent` | Coaching stream predates durable append-time UTC | Wrong product build — stop the campaign and check `--source-revision` |
| `coached-block-no-delivered-cues` | Coaching never spoke | Investigate before continuing; this is the Race-stratum failure mode |
| `control-block-delivered-cues` | Delivery happened in a control block | Manipulation failed; re-run |
| `control-arm-unverified` / `-store-unreadable` / `-store-predates-recorded-utc` | Absence could not be proven | Re-admit with the correct `--apex-data-root`; if the store genuinely cannot answer, the block is void |
| `recording-too-short` | Under 24 minutes | Re-run |
| `setup-varies` / `product-build-varies` | Something changed mid-corpus | Stop. The corpus may be finished at the last consistent block |

A refused recording is **not** deleted. Move it to
`F:\ApexResearch\corpus-2026-10\refused\` and note why. Refused recordings are
part of the attrition record.

## 6. The Practice → Qualifying transition — E01 and E02

This is the only slot pair produced by one invocation, and the only one where the
right action is to do nothing at the moment it matters.

### 6a. What actually happens, and why you must not intervene

When iRacing advances Practice → Qualifying:

- `LiveCoachingBridge.HandleSessionInfo` ends the old coaching session exactly
  once and binds the new one. `CoachingOrchestrator.HandleSessionEnded` runs the
  Milestone 16 closure coordinator: delivery drains, receipts append, the stream
  closes, the journal seals. The old coaching session completes properly.
- A **new, distinct** coaching session is created, with a distinct identity
  (`apex-ir-local-t180-ctoyotagr86-Open_Qualify-n1`) and its own cadence policy.
  `CoachingCadenceProfiles.ModeOf("Open Qualify")` gives `QualifyingFocused`
  (`MaxActiveObjectives = 2`, `MinSecondsBetweenDirectives = 30`) against
  Practice's `PracticeAggressive` (4, no minimum). The policy is fixed at session
  creation and travels inside `SessionCreated`.
- The recorder detects the identity change, finalizes the Practice bundle, and
  opens a second one by itself.

**Do NOT press Stop Coaching or Start Coaching across this transition. Do not
stop the recorder.** Leave both running. Nothing requires manual intervention,
and intervening breaks the one thing this slot exists to measure.

### 6b. The observation window, and the console condition to wait for

There is a real window and it is documented in the product's own tests
(`SessionTransitionProvenanceTests`, Milestone 37.2): the bridge rebinds
immediately while the orchestrator keeps the old binding until the new coaching
session is created, **which needs several completed laps of observation**.
Measured in the 2026-08-23 pilot, that window was **~510 s, three to four
completed laps**. During it the new research bundle exists and **no coaching
binding exists for it**.

Stop the recorder inside that window and `ReadCoachingEvidenceFor` finds no
binding, `CloseBundleAsync` fails safely, and the new bundle finalizes as
**INCOMPLETE**. That is what happened to
`research-329d96c3084f478db106dc488b74390f.incomplete`.

**The recorder cannot tell you when the new binding is ready.**
`CoachingBindingProbe` latches: once it has reported `Bound` for the Practice
session, `Evaluate` returns Quiet for the rest of the invocation. On the far side
of the transition it prints **neither** a bound line **nor** a warning. Do not
wait for a line that will never come.

**Use this instead, in a second PowerShell window**, with the wall-clock instant
the `SESSION TRANSITION #1` line appeared:

```powershell
apex-labs corpus coaching-binding `
  --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop" `
  --since "<UTC instant of the SESSION TRANSITION line>"
```

It is read-only and opens the store `mode=ro&immutable=1`. **The binding is ready
when it reports:**

```
"binding_ready": true
"delivered_since": <one or more>
"sessions_since": [ { "session_id": "apex-…-Open_Qualify-n1", "delivered": >=1, … } ]
```

`binding_ready: true` means Apex delivered a cue to the new session after the
transition, which it cannot do for a session it has not created and bound. Until
then it reports `binding_ready: false` and **the recorder must keep running**.
Deliveries from the Practice session do not count — they are before `--since`.

The audible cross-check is the same fact by ear: **you hear a coaching cue while
in Qualifying.**

### 6c. The rehearsal — budget 15 to 20 minutes, not 5 to 10

Run this once before the campaign, outside the corpus, with throwaway block and
condition ids. It is not a scheduled recording and its bundles are discarded.

1. Start coaching. iRacing in **Practice** at Oulton International, GR86.
2. Start the recorder (`--coaching enabled`, correct `--apex-data-root`, a
   throwaway `--block`).
3. Drive Practice until the recorder prints
   `Apex coaching evidence is bound to this live session.` and you have heard a
   cue. Typically 4–6 minutes.
4. **Advance iRacing to Qualifying. Touch nothing else.**
5. Note the wall-clock instant of `SESSION TRANSITION #1`, and watch for the
   `COMPLETED:` / `STARTED:` pair.
6. **Keep driving Qualifying and keep completing laps.** The new coaching session
   needs several completed laps before it exists at all — expect **8 to 12
   minutes** here, not two. Poll §6b until `binding_ready: true`.
7. Only then press Enter to stop.
8. Confirm **two** bundles exist and **both** carry a `COMPLETE` marker.

**Total: 15–20 minutes.** The earlier 5–10 minute estimate did not account for
the observation window and would have ended the rehearsal inside it, producing an
`.incomplete` bundle and a false conclusion that rollover does not work.

If step 6 never reaches `binding_ready: true`, do **not** stop the recorder in
the hope of salvaging the bundle. Keep driving and report it: an unbound
Qualifying session is a product finding, not an operator error.

### 6d. Admitting E01 and E02

The rollover does **not** read the next schedule row. It derives the new block id
from the outgoing one, by the Product rule in `ResearchRolloverIdentity`:

```
NextBlockId(previous, rolloverIndex, measuredSessionType)
    => $"{previous}-r{rolloverIndex}-{Slug(measuredSessionType)}"
```

so with `rolloverIndex = 1` and `Slug("Open Qualify") = "qualifying"`:

| | block_id | condition_id | measured |
|---|---|---|---|
| **E01** | `corpus-2026-10-b-e01-practice-oulton` | `engineering-practice-oulton` | `practice` |
| **E02** | `corpus-2026-10-b-e01-practice-oulton-r1-qualifying` | `engineering-practice-oulton` | `qualifying` |

The condition id is **carried over verbatim**, not regenerated. The schedule is
written to match both, so both bundles admit against their own rows with nothing
edited. Admit them together:

```powershell
apex-labs corpus admit --protocol-snapshot "<snapshot.json>" `
  --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop" `
  "F:\ApexResearch\corpus-2026-10\<practice-session-id>" `
  "F:\ApexResearch\corpus-2026-10\<qualifying-session-id>"
```

**Never rename a bundle to match the schedule.** Bundles are hash-sealed, and
renaming one to fit a plan is editing measured evidence after the fact — the
exact failure this corpus exists to make impossible. If a block id does not
match, the schedule is wrong; fix the schedule and regenerate.

### 6e. A rollover in any other slot

`SESSION TRANSITION #n` outside E01/E02 means iRacing changed session during a
slot that should have had one session. The rolled-over bundle is **not** a
scheduled block. Set it aside in `refused\` and re-run the scheduled row from the
start.

## 7. Pacing

- At most **4 recordings per day**, at least **10 minutes** between them.
- The 20 recordings spread across **at least 5 days**, so fatigue and day effects
  land on both arms rather than on one.
- Both recordings of a **stratum A pair** should be on the **same day**, back to
  back with the standard break. Pairing is what removes the day effect; splitting
  a pair across days throws that away.
- **E01 and E02 are one sitting** of roughly 65 minutes. Do not schedule them at
  the end of a session.
- Stop any block for discomfort or equipment trouble. A stopped block is a
  recorded deviation, not a failure, and it is always the right call.

## 8. At the end

```powershell
apex-labs corpus admit --protocol-snapshot "<snapshot.json>" `
  --apex-data-root "$env:LOCALAPPDATA\ApexSimCoach\desktop" `
  (Get-ChildItem -Directory "F:\ApexResearch\corpus-2026-10" | Where-Object Name -like 'research-*').FullName
```

`corpus_admitted: true` means every scheduled block is present exactly once and
each one is individually admissible. Anything else names what is missing. Partial
admission is deliberately not offered: a half-collected counterbalanced design is
not a smaller version of the design, it is a different and unbalanced one.

Only then does ingestion and analysis begin, and the inferential analysis
definition is written **after** the corpus exists and **before** any result is
computed.

## 9. Things this runbook will not let you do

- Change the schedule because a day went badly. The schedule is hash-bound into
  the freeze; a different order is a different experiment.
- Record a 21st recording "to be safe". Add it and the design is unbalanced.
- Fix a mislabelled bundle by editing or renaming it. Bundles are hash-sealed;
  re-record instead.
- Pass `--track` or `--layout` to make a bundle match a row.
- Substitute a track you have not driven for one in the schedule. If the row
  and the sim disagree, the sim is right and the schedule is regenerated.
- Admit a control block without `--apex-data-root`.
- Stop coaching before the recorder has finalized a coached bundle.
- Stop the recorder at a transition while `binding_ready` is still `false`.
- Ingest a refused bundle "just to look". Looking is how post-hoc selection
  starts.
