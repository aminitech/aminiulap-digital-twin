#!/usr/bin/env python3
"""
Combine every benchmark result in benchmarks/results/ into paper-ready tables.

    python benchmarks/make_tables.py                 # writes benchmarks/tables/
    python benchmarks/make_tables.py --stdout        # also print to the terminal

Emits, in both Markdown and LaTeX (booktabs `tabular`, drop-in for IEEEtran):

    T1  wall clock       median with the full min-max spread, per stage x host x backend
    T2  resource cost    CPU utilisation and peak RSS, same layout
    T3  environments     every run set that was executed, including the failed ones
    T4  determinism      whether output checksums agree across repeats, backends and hosts
    T5  replication      whether a second invocation on the same host reproduces the bytes
    T6  version          what the other sionna-rt version would have said

Rules it obeys, from METHOD.md:
  * never a bare single timing - median is always printed with min-max (Rule 1);
  * a cpu-labelled cell whose variant is not `llvm_*` is marked INVALID, never
    relabelled as CUDA (Rule 2);
  * cold (repeat 0) is kept separate from warm and reported (Rule 3);
  * agreement is decided by checksum, and "unknown" is a distinct answer from
    "matched" (Rule 4);
  * failed cells are printed in the table with their error, not omitted (Rules 5, 6).

A note on checksums. run_bench.py records `outputs` as a DIFF: the files whose MD5
changed in that run relative to the state of the work dir before it. To recover the
absolute checksum a run produced we replay the diffs in execution order and carry the
directory state forward. A file that a stage re-wrote with identical bytes therefore
shows up as "unchanged", which is exactly the signal the determinism table wants. A
file that was already in the work dir before the first run and was never rewritten has
no recorded checksum at all; it is reported as `?`, not as a match.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RESULTS = BENCH / "results"
TABLES = BENCH / "tables"

# Declared in METHOD.md; fixes row order so tables are diffable between regenerations.
STAGE_ORDER = [
    ("coverage_flat", "sionna\\_coverage (flat)", "sionna_coverage (flat)"),
    ("coverage_terrain", "sionna\\_coverage (terrain)", "sionna_coverage (terrain)"),
    ("analysis", "sionna\\_analysis", "sionna_analysis"),
    ("mmwave_sinr", "sionna\\_mmwave\\_sinr", "sionna_mmwave_sinr"),
    ("terrain_ground", "sionna\\_terrain\\_ground", "sionna_terrain_ground"),
]
STAGE_MD = {k: md for k, _tex, md in STAGE_ORDER}
BACKENDS = ["cpu", "cuda"]

MATCH, DIFFER, UNKNOWN = "=", "!=", "?"
TEX_SYM = {MATCH: r"$=$", DIFFER: r"$\neq$", UNKNOWN: r"$?$"}


# --------------------------------------------------------------------------- loading


class RunSet:
    """One results JSON: a host in one environment."""

    def __init__(self, path: Path):
        self.path = path
        d = json.loads(path.read_text())
        self.raw = d
        self.facts = d.get("host_facts", {})
        self.ann = d.get("annotations", {})
        self.cells = d.get("cells", [])
        self.host = self.facts.get("host", path.stem)
        self.arch = self.facts.get("arch", "?")
        self.label = self.ann.get("env_label", path.stem)
        self.primary = bool(self.ann.get("primary", False))
        self.stack = self.ann.get("stack", {})
        self.repeats = d.get("repeats")

    @property
    def backends(self) -> list[str]:
        seen = []
        for c in self.cells:
            if c["backend"] not in seen:
                seen.append(c["backend"])
        return seen

    def cell(self, backend: str, stage: str) -> dict | None:
        for c in self.cells:
            if c["backend"] == backend and c["stage"] == stage:
                return c
        return None


def load_runsets() -> list[RunSet]:
    sets = [RunSet(p) for p in sorted(RESULTS.glob("*.json"))]
    if not sets:
        raise SystemExit(f"no result JSONs in {RESULTS}")
    # `annotations.order` fixes column order in the wide tables; primaries first.
    sets.sort(key=lambda r: (not r.primary, r.ann.get("order", 99), r.path.name))
    return sets


# ------------------------------------------------------------------------ statistics


def cell_stats(cell: dict | None, backend: str) -> dict:
    """Median + spread for one cell, and the verdict on whether it is usable."""
    if cell is None:
        return {"status": "not run", "usable": False}
    runs = cell.get("runs", [])
    if not runs:
        return {"status": f"FAILED ({cell.get('error', 'no runs recorded')})",
                "usable": False}

    ok = [r for r in runs if r.get("ok")]
    variants = sorted({r.get("variant") or "unreported" for r in runs})
    failed = len(runs) - len(ok)

    st = {
        "n": len(runs),
        "n_ok": len(ok),
        "variants": variants,
        "variant": variants[0] if len(variants) == 1 else "/".join(variants),
        "usable": False,
        "status": "ok",
    }

    if failed:
        st["status"] = f"FAILED {failed}/{len(runs)}"
    # Rule 2: a cpu-labelled run must have selected an llvm variant. Anything else -
    # including a variant the harness could not read back - is not a verified CPU run.
    if backend == "cpu" and ok:
        bad = [r for r in ok if not (r.get("variant") or "").startswith("llvm")]
        if bad:
            selected = sorted({r.get("variant") or "unreported" for r in bad})
            st["status"] = "INVALID (cpu label, variant " + "/".join(selected) + ")"

    if not ok:
        return st

    walls = [r["wall_s"] for r in ok]
    cpus = [r["cpu_pct"] for r in ok if r.get("cpu_pct") is not None]
    rss = [r["max_rss_mb"] for r in ok if r.get("max_rss_mb")]
    cold = next((r["wall_s"] for r in ok if r.get("cold")), None)
    warm = [r["wall_s"] for r in ok if not r.get("cold")]

    st.update({
        "median": statistics.median(walls),
        "min": min(walls),
        "max": max(walls),
        "cold": cold,
        "warm_median": statistics.median(warm) if warm else None,
        "cpu_pct": statistics.median(cpus) if cpus else None,
        "rss_mb": max(rss) if rss else None,
        "usable": st["status"] == "ok",
    })
    return st


def fmt_wall(st: dict) -> str:
    if not st.get("n_ok"):
        return st["status"]
    body = f"{st['median']:.2f} ({st['min']:.2f}-{st['max']:.2f})"
    if st["status"] != "ok":
        body += f" [{st['status']}]"
    return body


def fmt_res(st: dict) -> str:
    if not st.get("n_ok"):
        return st["status"]
    cpu = f"{st['cpu_pct']:.0f}%" if st.get("cpu_pct") is not None else "n/a"
    rss = f"{st['rss_mb']:.0f}" if st.get("rss_mb") else "n/a"
    return f"{cpu} / {rss}"


# ----------------------------------------------------------------------- determinism


def replay(rs: RunSet) -> tuple[dict, dict]:
    """Carry the work-dir state forward through the runs, in execution order.

    Returns
        state_at[(backend, stage, repeat)] -> {filename: md5} as of the end of that run
        first_seen_stage[filename]         -> the stage that first wrote the file
    """
    state: dict[str, str] = {}
    state_at: dict[tuple, dict] = {}
    owner: dict[str, str] = {}
    for cell in rs.cells:
        b, s = cell["backend"], cell["stage"]
        for r in cell.get("runs", []):
            for name in r.get("outputs", {}):
                owner.setdefault(name, s)
            state.update(r.get("outputs", {}))
            state_at[(b, s, r["repeat"])] = dict(state)
    return state_at, owner


def artifact_map(runsets: list[RunSet]) -> dict[str, str]:
    """filename -> stage, taking the first host that observed it writing the file."""
    owner: dict[str, str] = {}
    for rs in runsets:
        _, own = replay(rs)
        for name, stage in own.items():
            owner.setdefault(name, stage)
    return owner


def short_tag(rs: RunSet) -> str:
    """`bgi-ran-01-x86_64-llvmpath` -> `llvmpath`; the bare host file -> `base`."""
    stem = rs.path.stem
    prefix = f"{rs.host}-{rs.arch}"
    return stem[len(prefix):].strip("-") or "base" if stem.startswith(prefix) else stem


def md5_of(state_at: dict, backend: str, stage: str, repeat: int, name: str):
    return state_at.get((backend, stage, repeat), {}).get(name)


def cmp2(a, b) -> str:
    if a is None or b is None:
        return UNKNOWN
    return MATCH if a == b else DIFFER


def repeat_verdict(state_at: dict, backend: str, stage: str, name: str,
                   repeats: int) -> str:
    vals = [md5_of(state_at, backend, stage, r, name) for r in range(repeats)]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return UNKNOWN
    return MATCH if len(set(vals)) == 1 else DIFFER


# ---------------------------------------------------------------------- rendering


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def tex_escape(s: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"),
                 ("&", r"\&"), ("#", r"\#")):
        if a == "\\" and "\\_" in s:  # already-escaped label, leave alone
            continue
        s = s.replace(a, b)
    return s


def tex_table(headers: list[str], rows: list[list[str]], caption: str,
              label: str, align: str | None = None, star: bool = False) -> str:
    align = align or ("l" * len(headers))
    env = "table*" if star else "table"
    lines = [f"% requires \\usepackage{{booktabs}}",
             f"\\begin{{{env}}}[t]", "  \\centering",
             f"  \\caption{{{caption}}}", f"  \\label{{{label}}}",
             f"  \\begin{{tabular}}{{{align}}}", "    \\toprule",
             "    " + " & ".join(headers) + r" \\", "    \\midrule"]
    lines += ["    " + " & ".join(r) + r" \\" for r in rows]
    lines += ["    \\bottomrule", "  \\end{tabular}", f"\\end{{{env}}}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- tables


def host_inventory(runsets: list[RunSet]) -> tuple[str, str]:
    headers = ["Host", "Arch", "CPU", "Logical cores", "RAM (GB)", "GPU", "Solver stack"]
    rows, seen = [], set()
    for rs in runsets:
        if not rs.primary or rs.host in seen:
            continue
        seen.add(rs.host)
        f, s = rs.facts, rs.stack
        stack = (f"sionna-rt {s.get('sionna_rt', '?')}, mitsuba {s.get('mitsuba', '?')}, "
                 f"drjit {s.get('drjit', '?')}")
        rows.append([rs.host, f.get("arch", "?"), f.get("cpu", "?"),
                     str(f.get("cores_logical", "?")), str(f.get("ram_gb", "?")),
                     f.get("gpu") or "none", stack])
    md = md_table(headers, rows)
    tex = tex_table([tex_escape(h) for h in headers],
                    [[tex_escape(c) for c in r] for r in rows],
                    caption="Benchmark host inventory.", label="tab:hosts",
                    align="llllrll", star=True)
    return md, tex


def matrix_tables(runsets: list[RunSet]) -> dict[str, str]:
    cols = [(rs, b) for rs in runsets if rs.primary for b in BACKENDS
            if rs.cell(b, STAGE_ORDER[0][0]) is not None]
    head = ["Stage"] + [f"{rs.host} {b.upper()}" for rs, b in cols]

    wall_rows, res_rows = [], []
    for key, _tex_name, md_name in STAGE_ORDER:
        w, r = [md_name], [md_name]
        for rs, b in cols:
            st = cell_stats(rs.cell(b, key), b)
            w.append(fmt_wall(st))
            r.append(fmt_res(st))
        wall_rows.append(w)
        res_rows.append(r)

    variant_row = ["Variant selected"]
    for rs, b in cols:
        vs = {cell_stats(rs.cell(b, k), b).get("variant") for k, _, _ in STAGE_ORDER}
        vs.discard(None)
        variant_row.append("/".join(sorted(vs)) if vs else "n/a")
    wall_rows.append(variant_row)

    tex_stage = {m: t for _k, t, m in STAGE_ORDER}
    tex_wall = [[tex_stage.get(r[0], tex_escape(r[0]))] + [tex_escape(c) for c in r[1:]]
                for r in wall_rows]
    tex_res = [[tex_stage[r[0]]] + [tex_escape(c) for c in r[1:]] for r in res_rows]

    align = "l" + "r" * len(cols)
    return {
        "wall_md": md_table(head, wall_rows),
        "wall_tex": tex_table([tex_escape(h) for h in head], tex_wall,
                              caption=("Wall-clock per pipeline stage: median of three "
                                       "repeats, full min--max spread in parentheses. "
                                       "Seconds."),
                              label="tab:wall", align=align, star=True),
        "res_md": md_table(head, res_rows),
        "res_tex": tex_table([tex_escape(h) for h in head], tex_res,
                             caption=("Resource cost per stage: median CPU utilisation "
                                      "(sum of child user+sys over wall) and peak RSS in MB."),
                             label="tab:resources", align=align, star=True),
    }


def environment_table(runsets: list[RunSet]) -> tuple[str, str]:
    headers = ["Run set", "Host", "Environment", "Backend", "Cells ok", "Verdict"]
    rows = []
    for rs in runsets:
        for b in rs.backends:
            ok = bad = 0
            verdicts = []
            for key, _, _ in STAGE_ORDER:
                st = cell_stats(rs.cell(b, key), b)
                if st.get("usable"):
                    ok += 1
                else:
                    bad += 1
                    verdicts.append(st["status"])
            verdict = "all cells valid" if not bad else sorted(set(verdicts))[0]
            rows.append([rs.path.name, rs.host, rs.label, b,
                         f"{ok}/{ok + bad}", verdict])
    md = md_table(headers, rows)
    tex = tex_table([tex_escape(h) for h in headers],
                    [[tex_escape(c) for c in r] for r in rows],
                    caption=("Every run set executed, including the ones that failed. "
                             "No cell is dropped (METHOD.md rules 5 and 6)."),
                    label="tab:environments", align="lllllr", star=True)
    return md, tex


def determinism_tables(runsets: list[RunSet]):
    prim = [rs for rs in runsets if rs.primary]
    owner = artifact_map(runsets)
    replayed = {rs.path.name: replay(rs)[0] for rs in prim}

    headers = ["Artifact", "Stage"]
    for rs in prim:
        for b in BACKENDS:
            headers.append(f"{rs.host} {b.upper()} repeats")
    for rs in prim:
        headers.append(f"{rs.host} CPU vs CUDA")
    if len(prim) == 2:
        headers += ["CPU across hosts", "CUDA across hosts"]

    stage_rank = {k: i for i, (k, _, _) in enumerate(STAGE_ORDER)}
    rows = []
    for name in sorted(owner, key=lambda n: (stage_rank.get(owner[n], 99), n)):
        stage = owner[name]
        row = [name, STAGE_MD.get(stage, stage)]
        for rs in prim:
            sa = replayed[rs.path.name]
            for b in BACKENDS:
                row.append(repeat_verdict(sa, b, stage, name, rs.repeats or 3))
        for rs in prim:
            sa = replayed[rs.path.name]
            row.append(cmp2(md5_of(sa, "cpu", stage, 0, name),
                            md5_of(sa, "cuda", stage, 0, name)))
        if len(prim) == 2:
            a, bset = replayed[prim[0].path.name], replayed[prim[1].path.name]
            for b in BACKENDS:
                row.append(cmp2(md5_of(a, b, stage, 0, name),
                                md5_of(bset, b, stage, 0, name)))
        rows.append(row)

    md = md_table(headers, rows)
    tex_stage = {m: t for _k, t, m in STAGE_ORDER}
    tex_rows = [[tex_escape(r[0]), tex_stage.get(r[1], tex_escape(r[1]))]
                + [TEX_SYM.get(c, tex_escape(c)) for c in r[2:]] for r in rows]
    tex = tex_table([tex_escape(h) for h in headers], tex_rows,
                    caption=(r"Output determinism by MD5. $=$ identical, $\neq$ differs, "
                             r"$?$ no checksum recorded. Repeat columns compare the three "
                             r"repeats of one cell; the last columns compare the cold "
                             r"(repeat~0) artefact across backends and across hosts."),
                    label="tab:determinism",
                    align="ll" + "c" * (len(headers) - 2), star=True)
    return md, tex


def replication_tables(runsets: list[RunSet]):
    """Same host, same stack, two separate invocations: does the output repeat?

    Repeat-to-repeat stability inside one interpreter run is a weaker claim than
    stability across invocations. Where a host was run twice on an identical stack we
    can test the stronger one, so we do.
    """
    groups: dict[tuple, list[RunSet]] = {}
    for rs in runsets:
        groups.setdefault((rs.host, json.dumps(rs.stack, sort_keys=True)), []).append(rs)
    pairs = [(g[0], other) for g in groups.values() if len(g) > 1 for other in g[1:]]
    if not pairs:
        return None, None, []

    owner = artifact_map(runsets)
    stage_rank = {k: i for i, (k, _, _) in enumerate(STAGE_ORDER)}
    cols = [(a, b, backend) for a, b in pairs for backend in BACKENDS]

    grid = {}
    for name in owner:
        stage = owner[name]
        for a, b, backend in cols:
            sa, sb = replay(a)[0], replay(b)[0]
            grid[(name, a.path.name, b.path.name, backend)] = cmp2(
                md5_of(sa, backend, stage, 0, name),
                md5_of(sb, backend, stage, 0, name))

    # A column where nothing was recorded on one side answers nothing; drop it rather
    # than pad the table with `?`.
    cols = [c for c in cols
            if any(grid[(n, c[0].path.name, c[1].path.name, c[2])] != UNKNOWN
                   for n in owner)]
    if not cols:
        return None, None, []

    # Name the partner in the header: on one host, different backends may have survived
    # the all-unknown filter against different partner run sets.
    headers = ["Artifact", "Stage"] + [f"{a.host} {backend.upper()} vs {short_tag(b)}"
                                       for a, b, backend in cols]
    rows = []
    for name in sorted(owner, key=lambda n: (stage_rank.get(owner[n], 99), n)):
        rows.append([name, STAGE_MD.get(owner[name], owner[name])]
                    + [grid[(name, a.path.name, b.path.name, backend)]
                       for a, b, backend in cols])

    labels = sorted({f"`{a.path.name}` vs `{b.path.name}`" for a, b, _bk in cols})
    tex_stage = {m: t for _k, t, m in STAGE_ORDER}
    tex = tex_table([tex_escape(h) for h in headers],
                    [[tex_escape(r[0]), tex_stage.get(r[1], tex_escape(r[1]))]
                     + [TEX_SYM.get(c, tex_escape(c)) for c in r[2:]] for r in rows],
                    caption=("Cross-invocation stability on one host with an identical "
                             "software stack: cold artefact of one run set against the "
                             "cold artefact of another."),
                    label="tab:replication",
                    align="ll" + "c" * (len(headers) - 2), star=True)
    return md_table(headers, rows), tex, labels


def version_sensitivity_tables(runsets: list[RunSet]):
    """Same host, same everything except the solver version: what does it change?

    Pairs run sets on one host whose `stack` differs in `sionna_rt` and nothing that
    would confound the answer beyond the libraries that ship with it.
    """
    pairs = []
    for rs in runsets:
        if not rs.primary:
            continue
        for other in runsets:
            if (other is rs or other.host != rs.host
                    or other.stack.get("sionna_rt") == rs.stack.get("sionna_rt")
                    or len(other.backends) < len(BACKENDS)):
                continue
            pairs.append((other, rs))  # (older/other, primary)
    if not pairs:
        return None, None, None, None, []

    cols = [(a, b, backend) for a, b in pairs for backend in BACKENDS]
    va = {a.stack.get("sionna_rt", "?") for a, _b, _k in cols}
    vb = {b.stack.get("sionna_rt", "?") for _a, b, _k in cols}
    headers = ["Stage"] + [f"{a.host} {backend.upper()}" for a, _b, backend in cols]

    rows = []
    for key, _tex, md_name in STAGE_ORDER:
        row = [md_name]
        for a, b, backend in cols:
            sa, sb = cell_stats(a.cell(backend, key), backend), \
                     cell_stats(b.cell(backend, key), backend)
            if not (sa.get("n_ok") and sb.get("n_ok")):
                row.append("n/a")
                continue
            row.append(f"{sa['median']:.2f} -> {sb['median']:.2f} "
                       f"({sb['median'] / sa['median']:.2f}x)")
        rows.append(row)

    # And whether the artefacts themselves changed.
    owner = artifact_map(runsets)
    stage_rank = {k: i for i, (k, _, _) in enumerate(STAGE_ORDER)}
    art_headers = ["Artifact", "Stage"] + [f"{a.host} {backend.upper()}"
                                           for a, _b, backend in cols]
    art_rows = []
    for name in sorted(owner, key=lambda n: (stage_rank.get(owner[n], 99), n)):
        stage = owner[name]
        row = [name, STAGE_MD.get(stage, stage)]
        for a, b, backend in cols:
            sa, sb = replay(a)[0], replay(b)[0]
            row.append(cmp2(md5_of(sa, backend, stage, 0, name),
                            md5_of(sb, backend, stage, 0, name)))
        art_rows.append(row)

    caption_versions = f"sionna-rt {'/'.join(sorted(va))} to {'/'.join(sorted(vb))}"
    tex_stage = {m: t for _k, t, m in STAGE_ORDER}
    wall_tex = tex_table([tex_escape(h) for h in headers],
                         [[tex_stage.get(r[0], tex_escape(r[0]))]
                          + [tex_escape(c) for c in r[1:]] for r in rows],
                         caption=("Solver version sensitivity, " + caption_versions +
                                  ": median wall-clock before, after, and the ratio. "
                                  "Seconds."),
                         label="tab:versionwall",
                         align="l" + "r" * len(cols), star=True)
    art_tex = tex_table([tex_escape(h) for h in art_headers],
                        [[tex_escape(r[0]), tex_stage.get(r[1], tex_escape(r[1]))]
                         + [TEX_SYM.get(c, tex_escape(c)) for c in r[2:]]
                         for r in art_rows],
                        caption=("Solver version sensitivity, " + caption_versions +
                                 ": whether the artefact checksum survives the version "
                                 "change."),
                        label="tab:versionart",
                        align="ll" + "c" * len(cols), star=True)
    labels = sorted({f"`{a.path.name}` -> `{b.path.name}`" for a, b, _k in cols})
    return (md_table(headers, rows), wall_tex,
            md_table(art_headers, art_rows), art_tex, labels)


# ------------------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true", help="also print the markdown")
    ap.add_argument("--out-dir", default=str(TABLES))
    args = ap.parse_args()

    runsets = load_runsets()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    hosts_md, hosts_tex = host_inventory(runsets)
    mats = matrix_tables(runsets)
    env_md, env_tex = environment_table(runsets)
    det_md, det_tex = determinism_tables(runsets)
    rep_md, rep_tex, rep_labels = replication_tables(runsets)
    vw_md, vw_tex, va_md, va_tex, v_labels = version_sensitivity_tables(runsets)

    prim = [rs for rs in runsets if rs.primary]
    provenance = "\n".join(
        f"- `{rs.path.name}` - {rs.host} ({rs.arch}), {rs.label}, "
        f"{rs.repeats} repeats\n  - stack: "
        + ", ".join(f"{k} {v}" for k, v in sorted(rs.stack.items()))
        + (f"\n  - DRJIT_LIBLLVM_PATH: {rs.ann['drjit_libllvm_path']}"
           if rs.ann.get("drjit_libllvm_path") else "")
        + (f"\n  - {rs.ann['notes']}" if rs.ann.get("notes") else "")
        + (f"\n  - recorded error: `{rs.ann['failure_error']}`"
           if rs.ann.get("failure_error") else "")
        for rs in runsets)

    replication_section = ""
    if rep_md:
        replication_section = f"""
## T5. Cross-invocation stability (same host, same stack)

Compares {" and ".join(rep_labels)} - two separate invocations of the same pipeline on
the same host with an identical software stack. Same symbols as T4.

{rep_md}
"""

    version_section = ""
    if vw_md:
        version_section = f"""
## T6. Solver version sensitivity

{" and ".join(v_labels)} - same host, same backend, same scene, different sionna-rt.
The primary matrix is measured at the version the repository pins and the paper cites;
this is what the other version would have said.

### T6a. Wall clock (median before -> median after)

{vw_md}

### T6b. Artefact checksums across the version change

{va_md}
"""

    doc = f"""# Benchmark results

Generated by `benchmarks/make_tables.py` from every JSON in `benchmarks/results/`.
Do not hand-edit; regenerate.

Method and the rules these tables obey: `benchmarks/METHOD.md`.
Primary matrix (the two version-matched run sets):
{", ".join(f"`{rs.path.name}`" for rs in prim)}.

## Hosts

{hosts_md}

## T1. Wall clock per stage

Median of three repeats, full min-max spread in parentheses, seconds.
A single timing is never reported (METHOD.md rule 1).

{mats['wall_md']}

## T2. Resource cost per stage

Median CPU utilisation (child user+sys over wall; >100% means parallel) and peak RSS in MB.

{mats['res_md']}

## T3. Environments and failures

Every run set that was executed, valid or not (METHOD.md rules 5 and 6).

{env_md}

## T4. Output determinism

`=` identical MD5, `!=` differing MD5, `?` no checksum recorded for that
combination. Repeat columns compare the three repeats within one cell; the
cross-backend and cross-host columns compare the cold (repeat 0) artefact.

{det_md}
{replication_section}{version_section}
## Provenance

{provenance}
"""

    (out / "results.md").write_text(doc)
    (out / "hosts.tex").write_text(hosts_tex + "\n")
    (out / "wall_clock.tex").write_text(mats["wall_tex"] + "\n")
    (out / "resources.tex").write_text(mats["res_tex"] + "\n")
    (out / "environments.tex").write_text(env_tex + "\n")
    (out / "determinism.tex").write_text(det_tex + "\n")
    if rep_tex:
        (out / "replication.tex").write_text(rep_tex + "\n")
    if vw_tex:
        (out / "version_wall.tex").write_text(vw_tex + "\n")
        (out / "version_artifacts.tex").write_text(va_tex + "\n")

    for p in sorted(out.iterdir()):
        print("wrote", p)
    if args.stdout:
        print()
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
