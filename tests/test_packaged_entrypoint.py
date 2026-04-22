import runpy
import sys
import types
from pathlib import Path


def test_packaged_entrypoint_uses_absolute_import(monkeypatch):
    called = {"value": False}

    fake_main_module = types.ModuleType("source.main")

    def fake_main():
        called["value"] = True

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "source.main", fake_main_module)

    entrypoint = Path(__file__).resolve().parents[1] / "source" / "__main__.py"
    runpy.run_path(str(entrypoint), run_name="__main__")

    assert called["value"] is True
