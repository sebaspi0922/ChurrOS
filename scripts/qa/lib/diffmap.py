"""qa-diffmap: git diff BASE...SHA -> features.yaml -> pruebas a correr."""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qalib  # noqa: E402


def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def load_yaml(path):
    """YAML mínimo (el subconjunto que usa features.yaml). Usa PyYAML si está."""
    try:
        import yaml
        return yaml.safe_load(open(path))
    except ImportError:
        pass
    root, stack = {}, [(-1, None)]  # (indent, container)
    stack = [(-1, root)]
    lines = []
    for raw in open(path):
        s = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if s.strip():
            lines.append(s)
    pending_key = {}
    for s in lines:
        ind = len(s) - len(s.lstrip())
        body = s.strip()
        while stack and ind <= stack[-1][0] and len(stack) > 1:
            stack.pop()
        cont = stack[-1][1]
        if body.startswith("- "):
            item = body[2:]
            if not isinstance(cont, list):
                raise ValueError(f"lista inesperada: {s}")
            if re.match(r"^[\w-]+:\s", item) or re.match(r"^[\w-]+:$", item):
                d = {}
                cont.append(d)
                stack.append((ind, d))
                k, _, v = item.partition(":")
                if v.strip():
                    d[k.strip()] = _scalar(v)
                else:
                    d[k.strip()] = None; pending_key[id(d)] = k.strip()
                # los siguientes campos del dict van con indent ind+2
                stack[-1] = (ind + 1, d)
            else:
                cont.append(_scalar(item))
            continue
        k, _, v = body.partition(":")
        k = k.strip()
        if v.strip():
            cont[k] = _scalar(v)
        else:
            cont[k] = []
            stack.append((ind, cont[k]))
    return root


def glob_re(g):
    out, i = "", 0
    while i < len(g):
        if g.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif g.startswith("**", i):
            out += ".*"; i += 2
        elif g[i] == "*":
            out += "[^/]*"; i += 1
        elif g[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(g[i]); i += 1
    return re.compile("^" + out + "$")


def git(*a, repo=qalib.REPO):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout


def compute(sha, base="origin/main", edition="niri", features_path=None):
    features_path = features_path or os.path.join(qalib.QA_DIR, "features.yaml")
    cfg = load_yaml(features_path)
    merge_base = git("merge-base", base, sha).strip()
    files = [f for f in git("diff", "--name-only", f"{base}...{sha}").splitlines() if f]
    stat = git("diff", "--stat", f"{base}...{sha}")
    docs = [glob_re(g) for g in cfg.get("docs_only", [])]
    feats = cfg.get("features", [])
    for f in feats:
        f["_re"] = [glob_re(g) for g in f.get("paths", [])]
    mapped, docs_files, unmapped = {}, [], []
    for path in files:
        hit = [f for f in feats if any(r.match(path) for r in f["_re"])]
        if hit:
            for f in hit:
                mapped.setdefault(f["id"], []).append(path)
        elif any(r.match(path) for r in docs):
            docs_files.append(path)
        else:
            unmapped.append(path)
    selected = []
    for f in feats:
        if f["id"] not in mapped:
            continue
        eds = f.get("editions") or []
        selected.append({"id": f["id"], "title": f.get("title", f["id"]),
                         "checks": f.get("checks", []), "files": mapped[f["id"]],
                         "applies": (not eds) or edition in eds, "editions": eds})
    return {"base": base, "merge_base": merge_base, "sha": sha, "edition": edition,
            "files": files, "stat": stat, "features": selected, "docs_files": docs_files,
            "unmapped": unmapped, "docs_only": bool(files) and len(docs_files) == len(files)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="qa-diffmap: qué pruebas tocan para un SHA")
    ap.add_argument("sha"); ap.add_argument("--base", default="origin/main")
    ap.add_argument("--edition", default="niri"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = compute(a.sha, a.base, a.edition)
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False)); sys.exit(0)
    print(f"{a.base}...{a.sha} ({len(d['files'])} archivos, merge-base {d['merge_base'][:8]})")
    for f in d["features"]:
        tag = "" if f["applies"] else f"  [otra edición: {','.join(f['editions'])}]"
        print(f"  {f['id']}: {', '.join(f['checks'])}{tag}")
        for p in f["files"]:
            print(f"      {p}")
    print(f"  docs: {len(d['docs_files'])}  docs_only={d['docs_only']}")
    for p in d["unmapped"]:
        print(f"  UNMAPPED {p}")
