"""Turning a match into something you can say to a person.

One code path, used by the scan endpoint, the shelf re-check and the pharmacy
bulk check, so the same medicine cannot get three different answers.
"""
from __future__ import annotations

from . import bedrock
from .match import FLAGGED, NO_MATCH, UNCERTAIN, NSQIndex, match
from .normalise import is_expired
from .schema import ADVICE, advice_for

DISCLAIMER = (
    "BatchWatch reflects published regulator alerts only. It is not a "
    "certification of authenticity and it is not medical advice. A result of "
    "'not flagged' means this batch is absent from the alerts we hold - not "
    "that the medicine is safe."
)

HEADLINE = {
    FLAGGED: "This batch has been flagged",
    UNCERTAIN: "We could not read this clearly",
    NO_MATCH: "This batch has not been flagged",
}

# What the colour means, stated so the UI and the copy cannot drift apart.
TONE = {FLAGGED: "red", UNCERTAIN: "amber", NO_MATCH: "green"}


def _uncertain_payload(reason: str) -> dict:
    return {
        "severity": "UNKNOWN",
        "advice": {
            lang: "Check the batch number by hand against the regulator alert, "
            "or ask your pharmacist."
            for lang in ADVICE["LOW"]
        },
        "reason": reason,
    }


def build_verdict(
    query: dict,
    index: NSQIndex,
    image_b64: str = "",
    media_type: str = "image/jpeg",
    allow_adjudication: bool = True,
) -> dict:
    """Match, optionally adjudicate the middle band, and phrase the result.

    Adjudication can move a result in either direction, with one asymmetry: it
    may never turn an amber into a green on its own. Clearing a medicine is the
    one call worth being slow and cautious about.
    """
    result = match(query, index)
    adjudication: dict | None = None

    if (
        allow_adjudication
        and result.verdict == UNCERTAIN
        and result.candidates
        and bedrock.available()
    ):
        adjudication = bedrock.adjudicate(
            query,
            [c.row for c in result.candidates],
            image_b64=image_b64,
            media_type=media_type,
        )
        if adjudication:
            decision = adjudication.get("decision")
            idx = adjudication.get("candidate_index", -1)
            if decision == "match" and 0 <= idx < len(result.candidates):
                result.verdict = FLAGGED
                result.best = result.candidates[idx].row
                result.adjudicated = True
                result.reason = adjudication.get("reason") or result.reason
            elif decision == "no_match":
                # Deliberately NOT downgraded to NO_MATCH: the model ruling out
                # these particular candidates is not evidence that the medicine
                # is fine, so the honest answer stays amber.
                result.adjudicated = True
                result.reason = adjudication.get("reason") or result.reason
            else:
                result.adjudicated = True
                result.reason = adjudication.get("reason") or result.reason

    row = result.best or {}
    verdict = result.verdict

    if verdict == FLAGGED:
        severity = row.get("severity") or "LOW"
        advice = {lang: advice_for(severity, lang) for lang in ADVICE["LOW"]}
        reason = result.reason
    elif verdict == UNCERTAIN:
        payload = _uncertain_payload(result.reason)
        severity, advice, reason = payload["severity"], payload["advice"], payload["reason"]
    else:
        severity = "NONE"
        advice = {
            "en": "Nothing to do. Keep the strip until the course is finished.",
            "hi": "कुछ करने की जरूरत नहीं। कोर्स पूरा होने तक स्ट्रिप रखें।",
            "ta": "எதுவும் செய்ய தேவையில்லை. சிகிச்சை முடியும் வரை ச்டிரிப்பை வைத்திருங்கள்.",
        }
        reason = result.reason

    expired = is_expired(query.get("exp_date") or "")

    return {
        "verdict": verdict,
        "tone": TONE[verdict],
        "headline": HEADLINE[verdict],
        "score": round(result.score, 4),
        "severity": severity,
        "advice": advice,
        "reason": reason,
        "adjudicated": result.adjudicated,
        "adjudication": adjudication,
        "match": row or None,
        "candidates": [
            {"score": round(c.score, 4), "signals": c.signals, "batch": c.row.get("batch_norm", ""),
             "drug_name": c.row.get("drug_name", ""), "alert_month": c.row.get("alert_month", "")}
            for c in result.candidates[:3]
        ],
        "expired": expired,
        "expiry_note": "This medicine is past its printed expiry date." if expired else "",
        "disclaimer": DISCLAIMER,
    }
