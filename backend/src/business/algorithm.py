"""Route each trial segment to a same-speed comparison and retransfer decision."""

from math import isfinite

import numpy as np

from .calibration import Calibration


ACTION_BY_SIGNAL = {
    "left_gain": "检查左轨校准增益",
    "right_gain": "检查右轨校准增益",
    "phase": "校正双轨磁头方位角",
    "treble_loss": "清洁磁头并核对高频测试音",
    "flutter": "复测压带轮与带速稳定性",
    "noise": "检查接地与前级底噪",
}
LABELS_BY_SIGNAL = {
    "left_gain": "左轨电平差",
    "right_gain": "右轨电平差",
    "phase": "双轨相位差",
    "treble_loss": "高频相对损失",
    "flutter": "抖晃率",
    "noise": "静音底噪",
}
SIGNALS = tuple(ACTION_BY_SIGNAL)
SPEEDS = ("9.5", "19")
COHORTS = ("参考", "留出", "待检")


def _matrix(rows: list[dict]) -> np.ndarray:
    return np.asarray([[row[key] for key in SIGNALS] for row in rows], dtype=float)


def _validate(rows: list[dict], parameter: float) -> None:
    if not isfinite(parameter) or not 0.8 <= parameter <= 0.99:
        raise ValueError("留出合格分位必须在 0.80 到 0.99 之间。")
    identifiers = set()
    for row in rows:
        identifier = row["sample_id"]
        if identifier in identifiers:
            raise ValueError(f"试录段号 {identifier} 重复。")
        identifiers.add(identifier)
        if row["speed"] not in SPEEDS or row["cohort"] not in COHORTS:
            raise ValueError(f"{identifier} 的带速或样本用途无法识别。")
        if row["end_s"] <= row["start_s"]:
            raise ValueError(f"{identifier} 的结束时间必须晚于起始时间。")
        if not all(isfinite(row[key]) for key in SIGNALS):
            raise ValueError(f"{identifier} 的量测列需填写有限数值。")


def _score_speed(
    speed: str, samples: list[dict], quantile: float
) -> tuple[list[dict], int, str]:
    reference = [row for row in samples if row["cohort"] == "参考"]
    holdout = [row for row in samples if row["cohort"] == "留出"]
    trial = [row for row in samples if row["cohort"] == "待检"]
    if len(reference) < 12 or len(holdout) < 8:
        raise ValueError(f"{speed} cm/s 带速需要至少 12 条参考段和 8 条留出段。")
    model = Calibration.fit(_matrix(reference), speed)
    reference_positions, _, _ = model.measure(_matrix(reference))
    holdout_positions, holdout_residual, _ = model.measure(_matrix(holdout))
    threshold = float(np.quantile(np.maximum(*model.scores(holdout_positions, holdout_residual)), quantile))
    if threshold <= 1e-8:
        raise ValueError(f"{speed} cm/s 留出段边界接近零，请补测合格段。")

    positions, residual, projected_measurements = model.measure(_matrix(trial))
    by_residual, by_location = model.scores(positions, residual)
    score_ratios = np.maximum(by_residual, by_location) / threshold
    results = []
    retransfer_count = 0
    for row, position, error, reconstruction, q, location, ratio in zip(
        trial, positions, residual, projected_measurements, by_residual, by_location, score_ratios
    ):
        nearest = int(np.square(reference_positions - position).sum(axis=1).argmin())
        retransfer = bool(ratio > 1)
        retransfer_count += retransfer
        deviations = error if q >= location else reconstruction
        signal = SIGNALS[int(np.abs(deviations).argmax())]
        interpretation = "重构残差" if q >= location else "主成分偏移"
        results.append(
            {
                "sample_id": row["sample_id"],
                "reel": row["reel"],
                "interval": f'{row["start_s"]:g}–{row["end_s"]:g} 秒',
                "speed": f"{speed} cm/s",
                "score": round(float(ratio), 5),
                "evidence": f"{LABELS_BY_SIGNAL[signal]} · {interpretation}" if retransfer else "未越同速边界",
                "ref_segment": reference[nearest]["sample_id"],
                "decision": f"建议复录 · {ACTION_BY_SIGNAL[signal]}" if retransfer else "通过校准",
            }
        )
    note = (
        f"{speed} cm/s 使用 {len(reference)} 条参考段与 {len(holdout)} 条留出段。"
        f"前两主成分保留 {model.explained_share:.1%} 的参考方差，综合分门槛 {threshold:.3f}。"
    )
    return results, retransfer_count, note


def analyze(rows: list[dict], parameter: float) -> dict:
    _validate(rows, parameter)
    results = []
    retransfer_total = 0
    notes = []
    for speed in SPEEDS:
        samples = [row for row in rows if row["speed"] == speed]
        if not any(row["cohort"] == "待检" for row in samples):
            continue
        speed_results, retransfer_count, note = _score_speed(speed, samples, parameter)
        results.extend(speed_results)
        retransfer_total += retransfer_count
        notes.append(note)
    if not results:
        raise ValueError("测量表中至少需要一个待检段。")
    results.sort(key=lambda row: (-row["score"], row["sample_id"]))
    return {
        "summary": f"已比对 {len(results)} 条试录段，其中 {retransfer_total} 条进入复录交班。",
        "metrics": [
            {"label": "待检段", "value": len(results)},
            {"label": "建议复录", "value": retransfer_total},
            {"label": "通过校准", "value": len(results) - retransfer_total},
            {"label": "带速基线", "value": len(notes)},
        ],
        "rows": results,
        "notes": notes + ["相对分越过 1 时建议复录。参考段用于定位机台差异，复录后需复测同一时间区间。"],
    }
