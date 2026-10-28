# Continuous input runtime

The product target is camera-based continuous pointer control: aim, click,
double-click, drag, release and scroll across desktop applications. The present
architecture separates real-time decisions from optional context and display.
It does not claim that camera accuracy or user comfort is already equivalent to
a physical mouse; those require the device acceptance described below.

## Ownership and execution

| Owner | Responsibility | Boundary |
|---|---|---|
| Camera worker | Capture, mirror, MediaPipe VIDEO inference, timestamped landmarks | Submit directly to the control mailbox; no GUI event delivery required |
| ControlRuntime | One decision thread, one pending observation, one latest preview | Discards superseded pending observations; no backlog of stale commands |
| ControlEngine | Calibration, filtering, session gate, arbitration, pointer/scroll/shortcut state, dispatch | Configuration copied at construction; only its owner mutates history |
| InputGuard | Serialize native input and release, check evidence freshness, recover failed releases | Independent 25 ms polling; 250 ms evidence lease; stop forbids renewal |
| Accessibility worker | Read context and target geometry | Latest request per kind; maximum 120 ms cache age measured from query start |
| Telemetry worker | Write bounded diagnostic records | 256 pending records by default; overflow is counted, input never waits for disk |
| Qt main thread | Settings, preview, labels, HUD | Render immutable state and bounded discrete outcomes; never drive live input |

The runtime buffers at most 64 discrete feedback outcomes. This buffer describes
actions already dispatched; dropping old feedback cannot repeat an action.
Continuous moves and drags are represented by the latest state rather than a
per-frame UI event queue. Diagnostic counters report processed/dropped frames,
feedback overflow, step duration and frame age.

MediaPipe VIDEO inference remains synchronous within its dedicated worker. A
second asynchronous callback layer would not itself improve decision quality;
the bounded mailbox already separates capture from control. Qt's GUI objects
remain on the main thread. See the official [Qt threading
contract](https://doc.qt.io/qt-6/threads-qobject.html) and [MediaPipe running-mode
contract](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python).

## Intent is a temporal decision

The engine interprets landmark history, physical pinch evidence, activation,
current interaction state and gesture ownership. A pose label alone is not a
command. The deterministic pointer state machine distinguishes a short pinch
from sustained pinch movement; click coordinates stay locked while the separate
motion coordinate drives dragging. Confirmed opening releases; missing or
ambiguous evidence cancels. Relative mode reacquires the actual native cursor
position after loss or reactivation.

### Joint pinch admission and aim

`PinchIntentObserver` owns one physical episode. It first requires genuine open
pointing, then evaluates contraction, physical closure, confidence, other-finger
motion and palm coherence over time. Its immutable evidence drives the pointer
state machine directly: `idle → candidate → confirmed → released`, with
`cancelled` retaining click ownership until qualified opening. A candidate keeps
the visible pointer moving while storing its target privately; raw or delayed
pose labels cannot admit a click. After cancellation, a coherent genuinely open
pointing frame can resume movement immediately, independently of the additional
evidence needed to rearm a click.
Qualified release can arm a consecutive episode without an extra idle frame.

The open index tip is expressed in a wrist/middle-MCP palm coordinate frame.
Transporting it with the current palm preserves whole-hand translation, rotation
and scale while excluding index articulation. A bounded numeric history restores
an independent tracker, mapper and cursor filter at the trusted open reference,
then replays the clean closing trajectory. Candidate replay never overwrites the
visible pointer branch: its output still matches the ordinary fingertip path.
Only after confirmation does the clean branch replace the live filter state,
using copies so the two branches cannot alias. This also prevents a second
quick pinch from inheriting finger-curl filter drift. The click target is the
filtered coordinate at the first observable contraction; current clean motion is a separate drag channel.
This avoids both the already-bent fingertip coordinate and a fixed rollback that
would discard legitimate moving aim. Replay never reposts historical OS events.

The physical first-close timestamp is separate from confident-closure dwell.
Confirmation delay cannot shorten a long hold into a short click. Drag distance
starts at physical closure, so palm travel during gradual approach and finger
curl alone do not start a drag. Aiming assistance runs once after confirmation;
its target adjustment does not count as hand travel. Raw opening immediately
stops drag movement while debounced release posts mouse-up once.

Current policies use a 200 ms observation window, at least two genuine open
samples spanning 40 ms, at least two confident closed samples spanning 55 ms,
and a 250 ms candidate timeout. Filter snapshots span at most 250 ms/64 frames;
the motion trace is bounded to 64 frames with a separately retained drag anchor.
Missing reconstruction history, inconsistent palm geometry, discontinuous
timestamps and camera frame-size changes cancel the episode. A frame-size
change releases any held button and discards that observation before rearming.
Snapshots expose the effective phase and cancellation reason. Candidates report
no locked position, so neither the HUD nor camera preview claims a target lock.
Confirmation can visibly correct the pointer back to the reconstructed target;
previously delivered movement and application hover effects cannot be undone.

These are explicit temporal rules and a locally planar palm model, not a trained
intent predictor. Out-of-plane motion, occlusion and noisy landmarks still need
camera validation. Identical observed motions with different human intentions
cannot be distinguished by these rules. The target estimate and confirmation
policy trade responsiveness against accidental activation; synthetic accuracy
does not establish real-user accuracy.

Core scrolling has its own dwell, direction-confirmation and timed-repeat
lifecycle. It keeps the aimed cursor position fixed, stops on loss of pose or
session ownership, and does not require a system-provided scroll-area identity.
The operating system delivers wheel input to the application under that cursor.
The optional semantic-context lane still requires a fresh target identity.
`pointer_scroll.enabled=false` retains the contextual-only scrolling path.

Custom static templates, completed DTW motion sequences and combinations remain
optional lanes. They cannot consume a frame while a pointer interaction owns
it. Models may suggest target assistance; they do not own mouse-down/up state.
No untrained sequence model or remote language-model call is placed in the
latency-critical input loop.

## Failure and shutdown

1. Duplicate, regressing, stale, future or malformed observations release input
   and reset incomplete intent before further dispatch.
2. A stalled camera expires the lease without requiring another frame or GUI
   callback. A resumed stream starts a fresh interaction.
3. Stop first revokes the session without waiting for the native dispatch lock.
   Late observations cannot renew it and late decisions cannot press a button.
   Release runs on the control owner/watchdog. A still-running old owner or an
   owed native release prevents restart.
4. Failed mouse-up remains owed and is retried. Another press cannot proceed
   while native release remains pending.
5. Accessibility failure disables assistance or semantic actions. Core pointer
   and scroll operations continue independently. Expired target results are
   unusable even when a slow query eventually completes.
6. Telemetry shutdown precedes closing its underlying store. If a write cannot
   finish within the join budget, disposal is deferred rather than closing a
   database still in use.

The freshness limits are software policy, not hard real-time guarantees. A
native input API that itself blocks while holding the dispatch lock cannot be
preempted safely by a Python watchdog. Stop remains responsive and release is
retried after that API returns. Process isolation would be a further
step if device measurements show such stalls. Context snapshots are bounded in
age, not atomic with application UI changes.

## Evidence and device acceptance

Headless landmark replay exercises the actual engine and native adapters with
fake OS sinks. Thread tests withhold Qt event processing, block accessibility
and telemetry, stop in-flight work, and verify bounded queues. These tests
establish software behavior, not camera recognition accuracy.

For physical acceptance, record the app version, camera mode, lighting,
distance, handedness and display arrangement. Compare the same tasks with a
physical mouse: small-target selection, repeated clicks, double clicks, text
selection, drag-and-drop, long-page scroll, reverse scroll and hand reacquisition.
Include camera unplugging, application hangs, permission loss and Stop during
drag. Record task success, unintended clicks, missed releases, motion-to-event
latency (p50/p95/p99), correction count and user fatigue after sustained use.
No universal equivalence claim should be made from inference timing alone.
