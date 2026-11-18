"""Every text file the clipper reads or writes must say encoding="utf-8".

Without it Python uses the system's default, which on Windows is an old code page that can't
store emoji or most non-English letters, and saving a clip's chat crashed ('charmap' codec)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "clipper"


def calls_missing_encoding():
    bad = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg for k in node.keywords}
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in ("read_text", "write_text") and "encoding" not in kw:
                bad.append(f"{path.name}:{node.lineno} {name}()")
            if name == "open" and isinstance(f, ast.Name):   # builtin open(), text mode
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                mode = next((k.value.value for k in node.keywords if k.arg == "mode"), mode)
                if "b" not in mode and "encoding" not in kw:
                    bad.append(f"{path.name}:{node.lineno} open()")
    return bad


def test_all_text_files_use_utf8():
    assert calls_missing_encoding() == []
