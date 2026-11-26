"""PCA model trained only on approved tape-transfer reference segments."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Calibration:
    centers: np.ndarray
    scales: np.ndarray
    axes: np.ndarray
    axis_variances: np.ndarray
    average_residual: float
    explained_share: float

    @classmethod
    def fit(cls, reference: np.ndarray, speed: str) -> "Calibration":
        center = reference.mean(axis=0)
        scales = reference.std(axis=0)
        if np.any(scales <= 1e-8):
            raise ValueError(f"{speed} cm/s 参考段中存在固定读数，请补测后重试。")
        normalized = (reference - center) / scales
        _, singular_values, feature_axes = np.linalg.svd(normalized, full_matrices=False)
        axes = feature_axes[:2]
        projected = normalized @ axes.T
        reconstructed = projected @ axes
        average_residual = float(np.square(normalized - reconstructed).sum(axis=1).mean())
        denominator = max(len(reference) - 1, 1)
        axis_variances = np.square(singular_values[:2]) / denominator
        if average_residual <= 1e-8 or np.min(axis_variances) <= 1e-8:
            raise ValueError(f"{speed} cm/s 参考段变化过少，无法识别重构偏离。")
        explained_share = float(np.square(singular_values[:2]).sum() / np.square(singular_values).sum())
        return cls(center, scales, axes, axis_variances, average_residual, explained_share)

    def measure(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        normalized = (samples - self.centers) / self.scales
        projected = normalized @ self.axes.T
        reconstructed = projected @ self.axes
        return projected / np.sqrt(self.axis_variances), normalized - reconstructed, reconstructed

    def scores(self, coordinates: np.ndarray, residuals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        reconstruction_scores = np.square(residuals).sum(axis=1) / self.average_residual
        location_scores = np.square(coordinates).mean(axis=1)
        return reconstruction_scores, location_scores
