"""The single LLM call site (Decision #3).

Exactly one place in the whole system calls an LLM: classifying a `customer_message_received`
text into a label the rules engine routes on. It lives behind a hard fallback — on ANY failure
(no key, rate limit, timeout, malformed response) it returns the deterministic keyword
classification instead, tagged ``source="fallback"`` so the caller logs the degradation. The
system therefore passes the full demo with no API key present.

This module is imported only by the decide *activity* (activity side, outside the workflow
sandbox), never by workflow code.
"""
from __future__ import annotations

from ..config import get_settings

VALID_LABELS = {"complaint", "refund", "escalation", "question", "neutral"}

_PROMPT = (
    "You classify a single customer message about an e-commerce order into exactly one label "
    "from this set: complaint, refund, escalation, question, neutral. "
    "Reply with ONLY the label, lowercase, no punctuation.\n\nMessage: {text}\nLabel:"
)


def rules_classify(text: str) -> str:
    """Deterministic keyword classifier — the fallback and the LLM-disabled path."""
    t = (text or "").lower()
    if any(w in t for w in ("refund", "money back", "return my")):
        return "refund"
    if any(w in t for w in ("angry", "terrible", "awful", "unacceptable", "worst", "furious",
                            "complaint", "disappointed")):
        return "complaint"
    if any(w in t for w in ("manager", "escalate", "lawyer", "legal", "cancel everything")):
        return "escalation"
    if "?" in t or any(w in t for w in ("when", "where", "how", "what", "can i", "could you")):
        return "question"
    return "neutral"


def classify_message(text: str) -> dict:
    """Return {"label": <str>, "source": "rules"|"llm"|"fallback", ...}.

    Never raises — the fallback guard catches everything so the workflow stays deterministic.
    """
    settings = get_settings()
    if not settings.llm_active:
        return {"label": rules_classify(text), "source": "rules"}

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        resp = model.generate_content(
            _PROMPT.format(text=text[:2000]),
            request_options={"timeout": 8},
        )
        label = (resp.text or "").strip().lower().split()[0] if resp.text else ""
        if label not in VALID_LABELS:
            raise ValueError(f"malformed label from model: {label!r}")
        return {"label": label, "source": "llm"}
    except Exception as exc:  # noqa: BLE001 — hard fallback guard is intentional
        return {"label": rules_classify(text), "source": "fallback", "error": str(exc)[:200]}
