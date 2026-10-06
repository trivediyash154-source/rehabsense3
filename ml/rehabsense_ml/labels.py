"""Harmonised activity taxonomy across the public datasets.

Classes are those the data actually supports for lower-limb sensors, not a
wish list. Activities whose leg motion is ambiguous or not represented in
rehabilitation (riding a moving elevator, household chores) are excluded
rather than forced into a class; that exclusion is listed per dataset so the
reported numbers are interpretable.

There is no "squat", "sit-to-stand" or "knee extension" class, because no
public dataset here contains them. Those exercise types are known from the
session configuration; recognising them from sensor data needs labelled
RehabSense recordings (see docs/HARDWARE_ML_ARCHITECTURE.md, stage 4).
"""

from __future__ import annotations

CLASSES = (
    "lying", "sitting", "standing", "walking", "stairs_up", "stairs_down",
    "running", "cycling", "other_exercise",
)

# Daily and Sports Activities (Barshan & Altun), a01..a19.
DAILY_SPORTS = {
    1: "sitting", 2: "standing", 3: "lying", 4: "lying",
    5: "stairs_up", 6: "stairs_down",
    7: "standing",            # standing still in an elevator
    # 8: moving around in an elevator -> excluded (ambiguous)
    9: "walking", 10: "walking", 11: "walking",
    12: "running",
    13: "other_exercise",     # stepper
    14: "other_exercise",     # cross trainer
    15: "cycling", 16: "cycling",
    17: "other_exercise",     # rowing
    18: "other_exercise",     # jumping
    19: "other_exercise",     # basketball
}
DAILY_SPORTS_EXCLUDED = {8: "moving around in an elevator"}

# PAMAP2 protocol activities.
PAMAP2 = {
    1: "lying", 2: "sitting", 3: "standing", 4: "walking", 5: "running",
    6: "cycling", 7: "walking",  # Nordic walking: leg motion is walking
    12: "stairs_up", 13: "stairs_down",
    20: "other_exercise",        # soccer
    24: "other_exercise",        # rope jumping
}
PAMAP2_EXCLUDED = {
    0: "transient", 9: "watching TV", 10: "computer work", 11: "car driving",
    16: "vacuum cleaning", 17: "ironing", 18: "folding laundry", 19: "house cleaning",
}

UCI_HAR = {
    "LAYING": "lying", "SITTING": "sitting", "STANDING": "standing",
    "WALKING": "walking", "WALKING_UPSTAIRS": "stairs_up",
    "WALKING_DOWNSTAIRS": "stairs_down",
}
