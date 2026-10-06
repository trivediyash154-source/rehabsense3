"""Hardware-v2 sensing pipeline: 1 ESP32, 2 MPU6050 (LEFT/RIGHT), N force channels.

Everything in this package is pure computation (numpy, no I/O), mirroring the
rule the v1 `processing` package follows, so every stage is unit-testable
without a socket or a database:

    channels      canonical channel layout and sample -> array conversion
    stream        timestamp ordering, duplicates, gaps, drift, latency
    calibration   the 8-step device calibration and its stored metadata
    orientation   mounting-independent 1-DoF tilt per IMU
    windowing     sliding windows and resampling
    features      versioned feature extraction (shared with ml/ training)
    bilateral     left/right comparison (research metric, not a diagnosis)
    force_motion  force/motion relationships
    repetitions   repetition segmentation, phases
    quality       RehabSense Movement Quality Index (research prototype)
    baseline      change from personal baseline
    inference     model bundle loading and activity inference
    processor     the per-session state machine tying it together
"""
