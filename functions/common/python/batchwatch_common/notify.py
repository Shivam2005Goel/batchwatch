"""Alert delivery.

In-app is the primary channel and always works. Email goes through SES when
BW_SES_FROM is configured; without it this is a no-op, which is the correct
behaviour for local development and for a sandbox account.

There is deliberately no SMS. Sending transactional SMS to Indian numbers
requires DLT registration with TRAI and a template approval cycle measured in
days, so it belongs on the roadmap, not in the build.
"""
from __future__ import annotations

import os

from .schema import advice_for

SES_FROM = os.environ.get("BW_SES_FROM", "")
SES_REGION = os.environ.get("BW_SES_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
APP_URL = os.environ.get("BW_APP_URL", "")


def enabled() -> bool:
    return bool(SES_FROM)


def _subject(alert: dict) -> str:
    severity = alert.get("severity", "")
    drug = alert.get("drug_name") or "A medicine on your shelf"
    if severity == "CRITICAL":
        return f"Stop taking {drug} - batch recalled"
    return f"A batch of {drug} on your shelf has been flagged"


def _body(alert: dict) -> str:
    lines = [
        "A medicine you saved to your BatchWatch shelf appears in a new "
        "regulator alert.",
        "",
        f"Medicine:     {alert.get('drug_name', '')}",
        f"Batch:        {alert.get('batch_raw') or alert.get('batch_norm', '')}",
        f"Manufacturer: {alert.get('manufacturer', '')}",
        f"Alert month:  {alert.get('alert_month', '')}",
        f"Reason:       {alert.get('failure_reason', '')}",
        "",
        f"What to do: {advice_for(alert.get('severity', 'LOW'))}",
    ]
    if alert.get("source_url"):
        lines += ["", f"Regulator notice: {alert['source_url']}"]
    if APP_URL:
        lines += [f"Your shelf: {APP_URL}"]
    lines += [
        "",
        "BatchWatch reflects published regulator alerts only. It is not a "
        "certification of authenticity and it is not medical advice.",
    ]
    return "\n".join(lines)


def _address_for(user_sub: str) -> str:
    """Find the email to notify.

    Anonymous device-id shelves have no address, and that is fine - they still
    get the in-app alert.
    """
    from .repo import get_store, pk_user

    profile = get_store().get(pk_user(user_sub), "PROFILE") or {}
    return (profile.get("email") or "").strip()


def send_alert_email(user_sub: str, alert: dict) -> bool:
    """Best-effort SES send. Returns False when nothing was sent."""
    if not enabled():
        return False
    to_address = _address_for(user_sub)
    if not to_address:
        return False

    import boto3

    client = boto3.client("ses", region_name=SES_REGION)
    client.send_email(
        Source=SES_FROM,
        Destination={"ToAddresses": [to_address]},
        Message={
            "Subject": {"Data": _subject(alert), "Charset": "UTF-8"},
            "Body": {"Text": {"Data": _body(alert), "Charset": "UTF-8"}},
        },
    )
    return True
