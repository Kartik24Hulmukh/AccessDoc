"""BOM lint: fail loudly if any tracked file starts with a UTF-8 BOM (EF BB BF).

Windows PowerShell 5.1 silently prepends a BOM when writing files with
Out-File, Set-Content, or > redirection.  Python tolerates it; strict JSON
parsers (Vercel's vercel.json pre-build validator, json.load) do not.

Run on every push on the Linux CI runner where the bash $'\\xef\\xbb\\xbf'
quoting quirk does not apply.
"""
import subprocess
import sys

files = (
    subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    .stdout.split()
)

bad = []
for f in files:
    try:
        with open(f, "rb") as fh:
            if fh.read(3) == b"\xef\xbb\xbf":
                bad.append(f)
    except OSError:
        pass

if bad:
    print(f"FAIL: UTF-8 BOM in {len(bad)} file(s):")
    for f in bad:
        print("  " + f)
    sys.exit(1)

print(f"ok: no UTF-8 BOM in {len(files)} tracked file(s)")
