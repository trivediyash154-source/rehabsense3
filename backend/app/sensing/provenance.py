"""Recording provenance: where the samples in a recording came from.

Decided once, at the handshake, from authentication -- never from the data
and never from what a device id looks like.

    SIMULATED              simulator (hello: simulated=true)
    PUBLIC_DATASET_REPLAY  public recordings re-sent in device format
                           (hello: simulated=true, data_source=PUBLIC_DATASET_REPLAY)
    SYNTHETIC_DEMONSTRATION
                           the synthetic demonstration cohort: generated movement
                           streamed through the real pipeline to populate a demo
                           workspace (hello: simulated=true,
                           data_source=SYNTHETIC_DEMONSTRATION). Not patient data.
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
SYNTHETIC_DEMONSTRATION = "SYNTHETIC_DEMONSTRATION"
ALL = (SIMULATED, PUBLIC_DATASET_REPLAY, SYNTHETIC_DEMONSTRATION, PHYSICAL_UNVERIFIED,
       PHYSICAL_REGISTERED)
# Sent by the sender, never inferred: generated or replayed, not a body on a sensor.
NON_PHYSICAL = (SIMULATED, PUBLIC_DATASET_REPLAY, SYNTHETIC_DEMONSTRATION)

DESCRIPTION = {
    SIMULATED: "SIMULATED -- synthetic signals; engineering evidence only, never physical-device evidence",
    PUBLIC_DATASET_REPLAY: "PUBLIC DATASET REPLAY -- public recordings re-sent in device format; "
                           "engineering evidence only, never physical-device evidence",
    SYNTHETIC_DEMONSTRATION: "SYNTHETIC DEMONSTRATION DATA -- generated movement streamed through the "
                             "real pipeline for demonstration; not patient data, not physical-device "
                             "evidence, not clinical evidence",
    PHYSICAL_UNVERIFIED: "PHYSICAL_UNVERIFIED -- not declared simulated, but not a registered device "
                         "authenticated with its own key; not evidence of anything physical",
    PHYSICAL_REGISTERED: "PHYSICAL_REGISTERED -- registered RehabSense device, authenticated with its own key",
}


def counts_as_physical_evidence(provenance: str | None) -> bool:
    return provenance == PHYSICAL_REGISTERED


def is_non_physical(provenance: str | None) -> bool:
    """Generated or replayed: never a person wearing a RehabSense device."""
    return provenance in NON_PHYSICAL


def session_mode_for(provenance: str) -> str:
    """The coarse SessionMode stored on the session row."""
    return {SIMULATED: "SIMULATED", PUBLIC_DATASET_REPLAY: "SIMULATED",
            SYNTHETIC_DEMONSTRATION: "SIMULATED",
            PHYSICAL_REGISTERED: "LIVE"}.get(provenance, "UNVERIFIED")


def of_session(session) -> str:
    """Provenance of a stored session (explicit column, else from its mode)."""
    explicit = getattr(session, "provenance", None)
    if explicit in ALL:
        return explicit
    mode = getattr(getattr(session, "mode", None), "value", None)
    return {"SIMULATED": SIMULATED, "LIVE": PHYSICAL_REGISTERED}.get(mode, PHYSICAL_UNVERIFIED)
