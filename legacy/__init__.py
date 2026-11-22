"""LEGACY (pre-GenLayer) local multi-agent pipeline — NOT part of the product.

Contains the old hard-coded rule "agents", the locally computed run_consensus()
and the Humanity Score blend. None of it is a validator consensus. It is kept
only for reference / historical comparison and is deliberately NOT importable
in normal operation. Set ETH_OS_ALLOW_LEGACY=1 to import it explicitly (the
internal imports are not maintained and will likely fail).
"""
import os

if os.environ.get("ETH_OS_ALLOW_LEGACY") != "1":
    raise ImportError(
        "legacy local-consensus code is disabled: it cannot produce an authoritative verdict. "
        "The only verdict source is contracts/eth_intelligence.py (GenLayer)."
    )
