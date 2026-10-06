"""Recording provenance: where the samples in a recording came from.

Decided once, at the handshake, from authentication -- never from the data
and never from what a device id looks like.

    SIMULATED              simulator (hello: simulated=true)
    PUBLIC_DATASET_REPLAY  public recordings re-sent in device format
                           (hello: simulated=true, data_source=PUBLIC_DATASET_REPLAY)
    PHYSICAL_UNVERIFIED    claims to be a physical device (not simulated) but is
                           not a registered device authenticated with its own key
    PHYSICAL_REGISTERED    registered device, authenticated with its own key

Only PHYSICAL_REGISTERED may contribute to hardware validation evidence,
hardware-specific training, pilot datasets, calibration baselines or
physical performance claims (`counts_as_physical_evidence`).
"""

from __future__ import annotations

SIMULATED = "SIMULATED"
PUBLIC_DATASET_REPLAY = "PUBLIC_DATASET_REPLAY"
PHYSICAL_UNVERIFIED = "PHYSICAL_UNVERIFIED"
PHYSICAL_REGISTERED = "PHYSICAL_REGISTERED"
ALL = (SIMULATED, PUBLIC_DATASET_REPLAY, PHYSICAL_UNVERIFIED, PHYSICAL_REGISTERED)

DESCRIPTION = {
    SIMULATED: "SIMULATED -- synthetic signals; engineering evidence only, never physical-device evidence",
    PUBLIC_DATASET_REPLAY: "PUBLIC DATASET REPLAY -- public recordings re-sent in device format; "
                           "engineering evidence only, never physical-device evidence",
    PHYSICAL_UNVERIFIED: "PHYSICAL_UNVERIFIED -- not declared simulated, but not a registered device "
                         "authenticated with its own key; not evidence of anything physical",
    PHYSICAL_REGISTERED: "PHYSICAL_REGISTERED -- registered RehabSense device, authenticated with its own key",
}


def counts_as_physical_evidence(provenance: str | None) -> bool:
    return provenance == PHYSICAL_REGISTERED


def session_mode_for(provenance: str) -> str:
    """The coarse SessionMode stored on the session row."""
    return {SIMULATED: "SIMULATED", PUBLIC_DATASET_REPLAY: "SIMULATED",
            PHYSICAL_REGISTERED: "LIVE"}.get(provenance, "UNVERIFIED")


def of_session(session) -> str:
    """Provenance of a stored session (explicit column, else from its mode)."""
    explicit = getattr(session, "provenance", None)
    if explicit in ALL:
        return explicit
    mode = getattr(getattr(session, "mode", None), "value", None)
    return {"SIMULATED": SIMULATED, "LIVE": PHYSICAL_REGISTERED}.get(mode, PHYSICAL_UNVERIFIED)
