"""Mutation sanity check for the CLIENT and UI tests (tests/unit). Run from the repo root in the venv: python scripts/mutate_client.py"""
import os, shutil, subprocess, sys
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = [
 ("client/gl_client.py", "C1 finality limited only by the final tx", "            final.finality = weakest\n", "            pass\n"),
 ("client/gl_client.py", "C2 weakest becomes strongest", "return min(vals, key=lambda f: _FIN_RANK.get(f, 0))", "return max(vals, key=lambda f: _FIN_RANK.get(f, 0))"),
 ("client/gl_client.py", "C3 any dry-run failure blocks submit", "            if \"[EXPECTED]\" in str(exc):", "            if True:"),
 ("client/gl_client.py", "C4 contract rejection ignored", "            if \"[EXPECTED]\" in str(exc):", "            if False:"),
 ("client/gl_client.py", "C5 earlier-run layers counted as final", "        fins = {k: \"UNKNOWN\" for k, v in preview.get(\"layers\", {}).items()", "        fins = {k: \"FINAL\" for k, v in preview.get(\"layers\", {}).items()"),
 ("client/gl_client.py", "C6 guessing a new id", "        for i in range(before, min(total, before + 50)):", "        return self._read(\"get_ids_page\", 0, 1)[0] if total else None\n        for i in range(before, min(total, before + 50)):"),
 ("app.py", "C7 no password nor local flag still unlocks", "    else:\n        authed = False\n", "    else:\n        authed = True\n"),
 ("app.py", "C8 password check always true", "authed = hmac.compare_digest(typed.encode(), pw_env.encode())", "authed = True"),
 ("app.py", "C9 pinned-address mismatch ignored", "addr_ok = st.checkbox(\"I know this is NOT the pinned contract (ETH_INTEL_CONTRACT)\")", "addr_ok = True"),
 ("app.py", "C10 provisional shown as final", "        elif o.finality == \"PROVISIONAL\":\n            st.warning(", "        elif False:\n            st.warning("),
 ("app.py", "C11 unresolved warning removed", "            if sc[\"unresolved\"]:", "            if False:"),
]
bad = []
for f, name, old, new in M:
    d = "/tmp/_mutc"; shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    p = os.path.join(d, f); t = open(p).read()
    if old not in t: print(f"{name:55s} -> PATTERN NOT FOUND"); bad.append(name); continue
    open(p, "w").write(t.replace(old, new, 1))
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "-q", "-x", "-p", "no:cacheprovider"], cwd=d, capture_output=True, text=True)
    k = r.returncode != 0
    print(f"{name:55s} -> {'KILLED' if k else 'SURVIVED'}")
    if not k: bad.append(name)
print("SURVIVORS:", bad or "none")
