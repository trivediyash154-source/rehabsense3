"""Write docs/protocol/sensor_protocol_v2.schema.json from the pydantic models.

    cd backend && python -m scripts.export_protocol_schema

The models in app/hardware/protocol_v2.py are the one canonical definition;
this file is generated from them and a test fails if it is stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.hardware.protocol_v2 import json_schemas

OUT = Path(__file__).resolve().parents[2] / "docs" / "protocol" / "sensor_protocol_v2.schema.json"


def render() -> str:
    return json.dumps(json_schemas(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT}")
