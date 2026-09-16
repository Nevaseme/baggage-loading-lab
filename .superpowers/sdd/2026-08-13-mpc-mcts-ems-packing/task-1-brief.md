### Task 1: Pure EMS and support-layer state

**Files:**
- Create: `simulator/agents/highscore/ems.py`
- Create: `simulator/tests/test_highscore_ems.py`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems-packing/task-1-report.md`

**Global constraints:** standard library and NumPy only; no `simulator/src`, dependency, network, Git, or public API changes; all loops deadline-aware; both rejected experiment flags stay default-off.

**Interfaces:**

```python
@dataclass(frozen=True)
class EMS:
    rect: Rect
    bottom_z: float
    max_height: float
    container_index: int
    protection: tuple[bool, bool]

@dataclass(frozen=True)
class ProxyAction:
    item: ItemSpec
    pool_index: int
    container_index: int
    orientation: int
    box: AABB
    support_key: tuple[int, int]

@dataclass
class ProxyState:
    spaces: tuple[EMS, ...]
    boxes: tuple[AABB, ...]
    placed_ids: tuple[int, ...]

def build_proxy_state(state: PackingState, clearance: float) -> ProxyState: ...
def propose_actions(state: ProxyState, item: ItemSpec, pool_index: int,
                    *, limit: int, deadline: float) -> list[ProxyAction]: ...
def apply_action(state: ProxyState, action: ProxyAction,
                 clearance: float) -> ProxyState | None: ...
def state_key(state: ProxyState, remaining_ids: tuple[int, ...],
              quantum: float = 0.01) -> tuple: ...
```

1. TDD RED for EMS split/prune using `Rect(0,2,0,2)` minus centered `1x1`; residuals cover unoccupied area, never overlap footprint, containment pruned. Include boundary-touch and sub-mm overlap.
2. Implement float64 split/prune. Split left/right/front/back positive rectangles; deterministic sort may round but feasibility may not.
3. TDD RED for floor, main shelf, small shelf, placed-top support layers; separate Z; no unsupported bridging; priority/soft independent; tilted boxes obstacle-only.
4. Implement `build_proxy_state` with the same floor/shelf conventions as CandidateGenerator.
5. TDD RED for proposals/transitions: six official orientations; 0.75m item spans old lane; order by heightmap increase then residual EMS; protected support rejection; expanded-AABB collision rejection.
6. Implement corners/centre/wall alignments, 1mm deterministic dedupe, support/protection/height/conservative path checks, `apply_action`, and deterministic quantized transposition key.
7. Run EMS, geometry, candidate, and full highscore unittest discovery. Self-review. Record exact RED/GREEN commands, pass counts, timings, files, and concerns in report.

Use `apply_patch` for edits. Do not implement Task 2. Return only status, tests, changed files, concerns.
