#!/usr/bin/env python3
"""
Check every quantitative claim in the paper against the artefact that produces it.

    python claims/verify_claims.py              # check against existing artefacts
    python claims/verify_claims.py --rerun      # re-run producers first, then check
    python claims/verify_claims.py --json       # machine-readable output

Exit code 0 when every checkable claim matches, 1 otherwise. Suitable for CI.

The point is not that this catches everything -- it cannot check prose, and it says so
by listing unverifiable claims explicitly rather than pretending they do not exist. The
point is that the numbers stop drifting silently. A paper is true on the day someone
writes it; this makes it true on the day someone reads it.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = Path(__file__).resolve().parent / "claims.yaml"

GREEN, RED, YELLOW, GREY, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = GREY = RESET = ""


def load_registry(path: Path) -> dict:
    try:
        import yaml  # noqa
    except ImportError:
        sys.exit("PyYAML is required: pip install -r claims/requirements.txt")
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── extractors ────────────────────────────────────────────────────────────────────
def _work_dir() -> Path:
    """Where stage outputs live. Honours ULAP_WORK_DIR like every other tool here."""
    return Path(os.environ.get("ULAP_WORK_DIR", ROOT / "blender"))


def extract(claim: dict, stdout_cache: dict) -> object:
    spec = claim.get("extract")
    if not spec:
        return None
    kind = spec["kind"]

    if kind == "stdout_regex":
        out = stdout_cache.get(claim.get("produced_by"), "")
        vals = re.findall(spec["pattern"], out)
        if not vals:
            return None
        return spec.get("join", "/").join(vals)

    art = claim.get("artifact")
    if art:
        p = Path(art)
        if not p.is_absolute():
            # stage artefacts live under the work dir; repo artefacts under ROOT
            cand = _work_dir() / art if art.startswith("sionna_out/") else ROOT / art
            if not cand.exists() and art.startswith("blender/"):
                # blender/ is untracked since 2026-07-30; a fresh clone holds no
                # stage outputs there. The same artefacts live under the work dir.
                cand = _work_dir() / art[len("blender/"):]
            p = cand
        if not p.exists():
            return None

    if kind == "md5_prefix":
        h = hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest()  # fingerprint, not a signature
        return h[: spec.get("length", 8)]

    if kind == "csv_first_last":
        rows = list(csv.DictReader(p.open()))
        col = spec["column"]
        return f"{float(rows[0][col]):.1f} .. {float(rows[-1][col]):.1f}"

    if kind == "csv_lookup":
        rows = list(csv.DictReader(p.open()))
        kc, vc = spec["key_column"], spec["value_column"]
        out = []
        for key in spec["keys"]:
            hit = next((r for r in rows if abs(float(r[kc]) - float(key)) < 1e-6), None)
            out.append(round(float(hit[vc])) if hit else None)
        return out

    if kind == "json_length":
        return len(json.loads(p.read_text())[spec["path"]])

    if kind in ("json_field", "json_fields"):
        d = json.loads(p.read_text())
        def dig(dotted):
            cur = d
            for k in dotted.split("."):
                cur = cur[k]
            return cur
        if kind == "json_field":
            val = dig(spec["path"])
            # some artefacts store fractions where the paper quotes percentages
            return round(val * spec["scale"], 4) if spec.get("scale") else val
        return [dig(x) for x in spec["paths"]]

    raise ValueError(f"unknown extractor: {kind}")


def safe_eval(expr: str, values: list[float]) -> float:
    """Evaluate a derived-claim expression WITHOUT eval().

    claims.yaml is editable by anyone opening a pull request and this runs in CI, so a
    real evaluator would be a remote-code-execution path. Only arithmetic over `v[i]`
    and abs()/min()/max() is permitted; anything else raises.
    """
    import ast, operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}
    funcs = {"abs": abs, "min": min, "max": max}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == "v":
            return values[int(ev(node.slice))]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in funcs and not node.keywords:
            return funcs[node.func.id](*(ev(a) for a in node.args))
        raise ValueError(f"expression not permitted: {ast.dump(node)}")

    return ev(ast.parse(expr, mode="eval"))


def matches(claim: dict, actual) -> bool:
    """Compare with the claim's own tolerance. Formatting differences are not failures."""
    if actual is None:
        return False
    expected = str(claim["paper_text"])

    tol = next((claim[k] for k in claim if k.startswith("tolerance_")), None)
    nums_e = [float(x) for x in re.findall(r"-?\d+\.?\d*", expected)]
    nums_a = [float(x) for x in re.findall(r"-?\d+\.?\d*", str(actual))]

    if tol is not None and len(nums_e) == len(nums_a) and nums_e:
        return all(abs(a - e) <= tol for a, e in zip(nums_a, nums_e))
    if len(nums_e) == len(nums_a) and nums_e:
        return all(abs(a - e) < 1e-9 for a, e in zip(nums_a, nums_e))
    return str(actual).strip() == expected.strip()


def in_paper(paper_src: str, claim: dict) -> bool | None:
    """Is the claimed string actually present in the paper? None if the paper is absent."""
    if paper_src is None:
        return None
    needle = str(claim["paper_text"])
    if needle in paper_src:
        return True
    nums = re.findall(r"-?\d+\.?\d+", needle)
    return bool(nums) and all(n in paper_src for n in nums)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true", help="re-run producers before checking")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--python", default=sys.executable, help="interpreter with sionna-rt")
    args = ap.parse_args()

    reg = load_registry(REG)
    # The papers repo is a sibling checkout, and this repo is often used from a git
    # worktree (where ../.. is not the parent directory). Resolve in order: explicit
    # env override, the registry's relative path, then a search of likely siblings.
    env_paper = os.environ.get("ULAP_PAPER_TEX")
    candidates = [Path(env_paper)] if env_paper else []
    candidates.append((REG.parent / reg["paper"]["file"]))
    rel = reg["paper"]["file"].lstrip("./")
    while rel.startswith("../"):
        rel = rel[3:]
    for base in (ROOT.parent, Path.home() / "Ulap"):
        candidates.append(base / rel)
    paper_path = next((c.resolve() for c in candidates if c.exists()), candidates[-1].resolve())
    paper_src = paper_path.read_text(encoding="utf-8") if paper_path.exists() else None
    if paper_src is None:
        print(f"{YELLOW}paper not found at {paper_path} — checking artefacts only{RESET}\n")

    stdout_cache: dict[str, str] = {}
    if args.rerun:
        producers = {c["produced_by"] for c in reg["claims"] if c.get("produced_by")}
        env = {**os.environ, "MPLBACKEND": "Agg"}
        env.setdefault("ULAP_WORK_DIR", str(_work_dir()))
        for prod in sorted(producers):
            script = ROOT / prod
            if not script.exists():
                print(f"{YELLOW}skip re-run, missing {prod}{RESET}")
                continue
            print(f"{GREY}re-running {prod} …{RESET}")
            r = subprocess.run([args.python, str(script)], capture_output=True,
                               text=True, env=env, cwd=str(ROOT))
            stdout_cache[prod] = r.stdout

    results, npass, nfail, nskip = [], 0, 0, 0
    for claim in reg["claims"]:
        cid = claim["id"]
        if claim.get("status") == "pending":
            print(f"  {YELLOW}PENDING{RESET}  {cid:32s} {GREY}{claim['what']}{RESET}")
            nskip += 1
            results.append({"id": cid, "state": "pending"}); continue

        if claim.get("derived_from"):
            base = next(c for c in reg["claims"] if c["id"] == claim["derived_from"])
            vals = [float(x) for x in re.findall(r"-?\d+\.?\d*", str(base["paper_text"]))]
            actual = round(safe_eval(claim["expression"], vals), 3)
        else:
            try:
                actual = extract(claim, stdout_cache)
            except Exception as e:
                actual = f"<error: {e}>"

        if actual is None:
            print(f"  {YELLOW}NO DATA{RESET}  {cid:32s} {GREY}artefact missing — "
                  f"run with --rerun{RESET}")
            nskip += 1
            results.append({"id": cid, "state": "no-data"}); continue

        ok = matches(claim, actual)
        present = in_paper(paper_src, claim)
        state = "pass" if ok else "fail"
        if ok and present is False:
            state = "fail"

        if state == "pass":
            print(f"  {GREEN}PASS{RESET}     {cid:32s} {claim['paper_text']}")
            npass += 1
        else:
            print(f"  {RED}FAIL{RESET}     {cid:32s}")
            print(f"           paper says : {claim['paper_text']}")
            print(f"           code says  : {actual}")
            if present is False:
                print(f"           {RED}and the claimed string is NOT in the paper{RESET}")
            nfail += 1
        results.append({"id": cid, "state": state, "paper": claim["paper_text"],
                        "actual": actual})

    print()
    for u in reg.get("unverifiable", []):
        print(f"  {GREY}UNCHECKABLE  {u['claim']}{RESET}")

    print(f"\n{npass} passed, {nfail} failed, {nskip} not checked")
    if args.as_json:
        print(json.dumps({"pass": npass, "fail": nfail, "skip": nskip,
                          "results": results}, indent=2, default=str))
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(main())
