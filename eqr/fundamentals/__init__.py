"""Institutional fundamental metrics (Wave 3, Layer 1). Pure functions over point-in-time
inputs; every metric carries a status (OK / UNKNOWN / NA) and provenance. No LLM, no I/O
outside `base.load_inputs` and `build.build_metrics`."""
