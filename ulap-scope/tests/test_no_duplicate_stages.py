"""Guard: blender/ entry points that shadow a packaged stage must stay shims.

History: blender/*.py used to carry byte-for-byte hand-synced copies of
ulap_scope/stages/*.py ("kept in sync by hand"), and they drifted at least
once (HERE not honouring ULAP_WORK_DIR). The copies became thin runpy shims,
and blender/ was later untracked from the repository entirely (2026-07-30),
which removes the drift source outright. Zero shadowing scripts is therefore
the best state, and this guard's job is to keep hand-copies from coming BACK:
if a blender/<name>.py reappears with a packaged stage's basename, it must be
a shim, never a copy.

Rules enforced, for every blender/<name>.py whose basename also exists in
ulap_scope/stages/:
  1. it is small (a shim, not a stage: <= MAX_SHIM_LINES lines),
  2. it carries the shim marker pointing at the canonical location,
  3. it delegates via runpy rather than implementing the stage.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BLENDER_DIR = REPO_ROOT / "blender"
STAGES_DIR = REPO_ROOT / "ulap-scope" / "ulap_scope" / "stages"

SHIM_MARKER = "canonical stage lives in ulap-scope/ulap_scope/stages/"
MAX_SHIM_LINES = 40


def _shadowing_scripts():
    """blender/*.py whose basename is also a packaged stage."""
    stage_names = {p.name for p in STAGES_DIR.glob("*.py")} - {"__init__.py"}
    return sorted(p for p in BLENDER_DIR.glob("*.py") if p.name in stage_names)


def test_no_untracked_state_regression():
    """blender/ carries no shadowing scripts at all, or only compliant shims.

    The strongest state is zero shadowing scripts (blender/ untracked). A
    reappearing script is not itself a failure -- the shim-rule tests below
    judge it -- but a packaged stage must always exist for anything that does
    shadow, so the canonical location can never be the copy.
    """
    for path in _shadowing_scripts():
        assert (STAGES_DIR / path.name).is_file()


def test_every_shadowing_script_is_a_shim():
    offenders = []
    for path in _shadowing_scripts():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        problems = []
        if len(lines) > MAX_SHIM_LINES:
            problems.append(
                f"{len(lines)} lines (> {MAX_SHIM_LINES}) -- looks like a hand-copy"
            )
        if SHIM_MARKER not in text:
            problems.append(f"missing shim marker {SHIM_MARKER!r}")
        if "runpy" not in text:
            problems.append("does not delegate via runpy")
        if problems:
            offenders.append(f"blender/{path.name}: " + "; ".join(problems))
    assert not offenders, (
        "stage code has been copied back into blender/ -- edit the packaged "
        "copy under ulap-scope/ulap_scope/stages/ instead, and keep the "
        "blender/ file a shim:\n  " + "\n  ".join(offenders)
    )


def test_shims_point_at_an_existing_stage():
    """The shim's own basename must resolve to a real packaged stage file."""
    for path in _shadowing_scripts():
        assert (STAGES_DIR / path.name).is_file(), (
            f"blender/{path.name} shadows a stage that no longer exists"
        )
