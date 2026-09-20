"""Shared BatchWatch logic, deployed as a Lambda layer.

Every module here must import cleanly with no third-party dependency so that
tests, the local dev server and the Lambda runtime all behave identically.
Optional accelerators (rapidfuzz, boto3) are imported defensively.
"""
__version__ = "1.0.0"
