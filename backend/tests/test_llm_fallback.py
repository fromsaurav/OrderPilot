"""Verify the single LLM call site's hard fallback guard (Decision #3) without a real key.

We inject a fake `google.generativeai` module to simulate: disabled, raising, malformed, and
success — and assert classify_message never raises and degrades to the rules classifier on any
failure. This is what guarantees the demo is deterministic with no/broken API key.
"""
import sys
import types
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.agent import llm  # noqa: E402


class _Settings:
    def __init__(self, active, key="k", model="m"):
        self.llm_active = active
        self.gemini_api_key = key
        self.gemini_model = model


def _install_fake_genai(behavior):
    """behavior: 'raise' | 'malformed' | 'ok:<label>'."""
    mod = types.ModuleType("google.generativeai")

    class _Model:
        def __init__(self, *a, **k):
            pass

        def generate_content(self, *a, **k):
            if behavior == "raise":
                raise RuntimeError("rate limit")
            text = "not-a-label" if behavior == "malformed" else behavior.split(":", 1)[1]
            return types.SimpleNamespace(text=text)

    mod.configure = lambda **k: None
    mod.GenerativeModel = _Model
    google_pkg = types.ModuleType("google")
    google_pkg.generativeai = mod
    sys.modules["google"] = google_pkg
    sys.modules["google.generativeai"] = mod


def run():
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ok   {name}")
        else:
            failed += 1
            print(f"  FAIL {name}")

    # 1. Disabled -> rules path, never touches the SDK.
    llm.get_settings = lambda: _Settings(False)
    r = llm.classify_message("I want a refund")
    check("disabled -> source=rules", r["source"] == "rules" and r["label"] == "refund")

    # 2. Enabled but SDK raises -> fallback to rules.
    llm.get_settings = lambda: _Settings(True)
    _install_fake_genai("raise")
    r = llm.classify_message("this is the worst, I'm furious")
    check("raise -> source=fallback", r["source"] == "fallback" and r["label"] == "complaint")

    # 3. Enabled but malformed label -> fallback to rules.
    _install_fake_genai("malformed")
    r = llm.classify_message("can you tell me when it ships?")
    check("malformed -> source=fallback", r["source"] == "fallback" and r["label"] == "question")

    # 4. Enabled + valid label -> uses LLM.
    _install_fake_genai("ok:escalation")
    r = llm.classify_message("get me a manager")
    check("valid -> source=llm", r["source"] == "llm" and r["label"] == "escalation")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
