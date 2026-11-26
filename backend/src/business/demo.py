"""Deterministic mock readings from the studio's bridge and tape transport."""

from random import Random


CENTERS = {
    "9.5": (-0.10, -0.16, 7.0, 2.3, 0.15, -63.5),
    "19": (0.05, -0.05, 4.0, 1.1, 0.08, -67.5),
}
SIGNALS = ("left_gain", "right_gain", "phase", "treble_loss", "flutter", "noise")


def _readings(speed: str, gain: float, transport: float, rng: Random) -> dict:
    """Vary tape path and console gain together, then add measurement scatter."""
    shifts = (
        0.33 * gain - 0.10 * transport,
        0.29 * gain + 0.12 * transport,
        1.70 * transport + 0.42 * gain,
        0.33 * transport - 0.28 * gain,
        0.016 * transport + 0.006 * gain,
        1.45 * gain + 0.95 * transport,
    )
    spread = (0.055, 0.057, 0.33, 0.09, 0.004, 0.33)
    return {
        key: round(center + shift + rng.gauss(0, scatter), 4)
        for key, center, shift, scatter in zip(SIGNALS, CENTERS[speed], shifts, spread)
    }


def demo_rows() -> list[dict]:
    rng = Random(112503)
    rows = []
    for letter, speed in (("A", "9.5"), ("B", "19")):
        for index in range(40):
            reference = index < 28
            start = (index % 4) * 30 + 30
            rows.append(
                {
                    "sample_id": f"{'REF' if reference else 'CHK'}-{letter}{index + 1:02d}",
                    "reel": f"CAL-{letter}{index // 4 + 1:02d}",
                    "start_s": start,
                    "end_s": start + 20,
                    "speed": speed,
                    "cohort": "参考" if reference else "留出",
                    **_readings(speed, rng.uniform(-1.6, 1.6), rng.uniform(-1.6, 1.6), rng),
                }
            )
        for index, start in enumerate((40, 90, 150, 210, 270), 1):
            readings = dict(zip(SIGNALS, CENTERS[speed])) if index == 1 else _readings(
                speed, rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng
            )
            if letter == "A" and index == 4:
                readings["treble_loss"] = 5.7
            if letter == "B" and index == 4:
                readings["flutter"] = 0.62
            if letter == "B" and index == 5:
                readings["noise"] = -57.0
            rows.append(
                {
                    "sample_id": f"TR-{letter}{index:02d}",
                    "reel": "HS-064A" if letter == "A" else "HS-077B",
                    "start_s": start,
                    "end_s": start + 20,
                    "speed": speed,
                    "cohort": "待检",
                    **readings,
                }
            )
    return rows
