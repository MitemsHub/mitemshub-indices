"""Hidden Markov Model + CUSUM filter for proactive regime shift detection.

This module provides two complementary anomaly detection mechanisms:

1. **CUSUMFilter** — detects abrupt mean or variance shifts in streaming
   data using the Cumulative Sum algorithm.  Fast and lightweight.

2. **HiddenMarkovRegimeDetector** — a 3-state HMM (Low Volatility, Normal,
   High Volatility / Spike) that models regime transitions probabilistically.
   Provides soft state probabilities rather than hard labels.

3. **RegimeShiftDetector** — combines both into a unified detector that
   also controls position sizing: when an anomaly is detected, position
   size is automatically reduced.

No external HMM library is required — the implementation uses a
streaming forward algorithm with exponential moving average parameter
updates.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


class MarketState(IntEnum):
    """The three HMM states ordered by volatility level."""
    LOW_VOL = 0
    NORMAL = 1
    HIGH_VOL = 2


@dataclass
class AnomalyAlert:
    """A detected regime shift or anomaly event."""
    alert_type: str  # "cusum_shift" | "hmm_regime_change" | "variance_spike"
    state: MarketState | None
    confidence: float
    position_scale: float  # recommended position size multiplier (0-1)
    observation: float
    details: dict[str, Any] = field(default_factory=dict)


# ── CUSUM Filter ─────────────────────────────────────────────────


class CUSUMFilter:
    """Cumulative Sum algorithm for detecting abrupt shifts in streaming data.

    Monitors a signal (e.g., log-returns or rolling variance) and raises
    an alert when the cumulative deviation from a reference mean exceeds
    a threshold, indicating a structural break.

    Parameters
    ----------
    threshold : float
        Detection threshold (in standard deviations).  Higher = less
        sensitive.  Default 5.0.
    drift : float
        Allowable drift before accumulation starts.  Prevents false
        positives from normal noise.  Default 0.5.
    window_size : int
        Number of observations for computing reference mean and std.
        Default 100.
    cooldown : int
        Minimum observations between consecutive alerts.  Default 20.
    """

    def __init__(
        self,
        threshold: float = 5.0,
        drift: float = 0.5,
        window_size: int = 100,
        cooldown: int = 20,
        freeze_after_alert: int = 20,
    ) -> None:
        self.threshold = threshold
        self.drift = drift
        self.window_size = window_size
        self.cooldown = cooldown
        self.freeze_after_alert = freeze_after_alert

        self._buffer: list[float] = []
        self._ref_mean: float = 0.0
        self._ref_std: float = 1.0
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0
        self._observations: int = 0
        self._last_alert_at: int = -9999

    def update(self, value: float) -> AnomalyAlert | None:
        """Feed a new observation and check for a shift.

        Returns an AnomalyAlert if a shift is detected, else None.
        """
        self._observations += 1
        self._buffer.append(value)

        if len(self._buffer) > self.window_size:
            self._buffer.pop(0)

        # Need enough data for reference statistics
        if len(self._buffer) < 20:
            return None

        # Update reference mean and std (freeze briefly after an alert to avoid adaptation masking the shift)
        obs_since_alert = self._observations - self._last_alert_at
        if obs_since_alert > self.freeze_after_alert:
            self._ref_mean = sum(self._buffer) / len(self._buffer)
            variance = sum((x - self._ref_mean) ** 2 for x in self._buffer) / len(self._buffer)
            self._ref_std = max(math.sqrt(variance), 1e-10)

        # Standardize the observation
        z = (value - self._ref_mean) / self._ref_std

        # CUSUM accumulation
        self._cusum_pos = max(0.0, self._cusum_pos + z - self.drift)
        self._cusum_neg = max(0.0, self._cusum_neg - z - self.drift)

        # Check for detection
        if (
            (self._cusum_pos > self.threshold or self._cusum_neg > self.threshold)
            and (self._observations - self._last_alert_at) > self.cooldown
        ):
            self._last_alert_at = self._observations
            direction = "upward" if self._cusum_pos > self.threshold else "downward"
            self._cusum_pos = 0.0
            self._cusum_neg = 0.0
            return AnomalyAlert(
                alert_type="cusum_shift",
                state=None,
                confidence=min(abs(z) / self.threshold, 1.0),
                position_scale=0.5,  # reduce to 50% on any CUSUM shift
                observation=value,
                details={
                    "direction": direction,
                    "z_score": round(z, 3),
                    "ref_mean": round(self._ref_mean, 6),
                    "ref_std": round(self._ref_std, 6),
                },
            )

        return None

    def reset(self) -> None:
        """Reset the filter state."""
        self._buffer.clear()
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._observations = 0
        self._last_alert_at = -9999


# ── Hidden Markov Model (3-state) ────────────────────────────────


class HiddenMarkovRegimeDetector:
    """3-state Hidden Markov Model for volatility regime detection.

    States: LOW_VOL (0) → NORMAL (1) → HIGH_VOL (2)

    Uses a streaming forward algorithm with exponential moving average
    parameter updates — no full retraining required.

    Parameters
    ----------
    lookback : int
        Number of observations for initial parameter estimation. Default 200.
    ema_alpha : float
        Exponential moving average decay for parameter updates. Lower = more
        stable parameters. Default 0.02.
    min_confidence : float
        Minimum state probability to accept a regime label. Below this,
        the state is "uncertain". Default 0.45.
    """

    # Initial transition matrix (favors staying in same state)
    _INIT_TRANSITION = [
        [0.92, 0.06, 0.02],  # from LOW_VOL
        [0.04, 0.92, 0.04],  # from NORMAL
        [0.02, 0.06, 0.92],  # from HIGH_VOL
    ]

    def __init__(
        self,
        lookback: int = 200,
        ema_alpha: float = 0.02,
        min_confidence: float = 0.45,
    ) -> None:
        self.lookback = lookback
        self.ema_alpha = ema_alpha
        self.min_confidence = min_confidence

        # Transition matrix (3x3)
        self._transition = [row[:] for row in self._INIT_TRANSITION]

        # Emission parameters: mean and std for each state
        self._emission_mean = [0.001, 0.005, 0.02]  # LOW, NORMAL, HIGH
        self._emission_std = [0.003, 0.008, 0.025]

        # Initial state probabilities (uniform)
        self._state_probs = [1.0 / 3, 1.0 / 3, 1.0 / 3]

        # Observation buffer for parameter estimation
        self._observations: list[float] = []
        self._total_observations: int = 0
        self._last_state: MarketState = MarketState.NORMAL

    def update(self, observation: float) -> MarketState:
        """Feed a new observation (e.g., log-return) and return the most likely state."""
        self._observations.append(observation)
        self._total_observations += 1

        if len(self._observations) > self.lookback * 3:
            self._observations = self._observations[-self.lookback:]

        # Forward step: compute emission probabilities
        emission_probs = self._emission_probabilities(observation)

        # Forward algorithm (one step)
        new_probs = []
        for j in range(3):
            # Sum over all previous states i: P(prev=i) * T(i→j) * emit(j)
            total = 0.0
            for i in range(3):
                total += self._state_probs[i] * self._transition[i][j] * emission_probs[j]
            new_probs.append(total)

        # Normalize
        total_prob = sum(new_probs)
        if total_prob > 0:
            self._state_probs = [p / total_prob for p in new_probs]
        else:
            self._state_probs = [1.0 / 3, 1.0 / 3, 1.0 / 3]

        # Determine most likely state
        best_state = MarketState(max(range(3), key=lambda i: self._state_probs[i]))
        self._last_state = best_state

        # Online parameter updates (EMA)
        if self._total_observations > self.lookback:
            self._update_parameters(observation, best_state)

        return best_state

    def get_state_probabilities(self) -> dict[str, float]:
        """Get current soft state probabilities."""
        return {
            "low_vol": round(self._state_probs[0], 4),
            "normal": round(self._state_probs[1], 4),
            "high_vol": round(self._state_probs[2], 4),
        }

    def get_confidence(self) -> float:
        """Get confidence of current state assignment (max probability)."""
        return max(self._state_probs)

    @property
    def current_state(self) -> MarketState:
        return self._last_state

    def get_regime_label(self) -> str:
        """Human-readable regime label."""
        labels = {
            MarketState.LOW_VOL: "low_volatility",
            MarketState.NORMAL: "normal",
            MarketState.HIGH_VOL: "high_volatility",
        }
        return labels[self._last_state]

    # ── Internal Methods ──────────────────────────────────────────

    def _emission_probabilities(self, value: float) -> list[float]:
        """Compute Gaussian emission probability for each state."""
        probs = []
        for i in range(3):
            mean = self._emission_mean[i]
            std = self._emission_std[i]
            # Gaussian PDF (unnormalized is fine since we normalize later)
            z = (value - mean) / max(std, 1e-10)
            prob = math.exp(-0.5 * z * z) / (std * math.sqrt(2 * math.pi))
            probs.append(max(prob, 1e-20))
        return probs

    def _update_parameters(self, observation: float, state: MarketState) -> None:
        """Online EMA update of emission parameters and transition matrix."""
        alpha = self.ema_alpha

        # Update emission mean/std for the active state using EMA
        i = int(state)
        old_mean = self._emission_mean[i]
        new_mean = old_mean + alpha * (observation - old_mean)
        self._emission_mean[i] = new_mean

        # Update emission std (EMA of squared deviations)
        old_std = self._emission_std[i]
        deviation = abs(observation - new_mean)
        new_std = old_std + alpha * (deviation - old_std)
        self._emission_std[i] = max(new_std, 1e-6)

        # Update transition matrix (very slowly, soft targets to prevent collapse)
        # Soft targets: 0.96 for current state, 0.02 for each neighbor
        soft_targets = [0.02, 0.02, 0.02]
        soft_targets[i] = 0.96
        for j in range(3):
            self._transition[i][j] += alpha * 0.1 * (soft_targets[j] - self._transition[i][j])

        # Renormalize transition row
        row_sum = sum(self._transition[i])
        if row_sum > 0:
            self._transition[i] = [v / row_sum for v in self._transition[i]]


# ── Combined Regime Shift Detector ───────────────────────────────


@dataclass
class RegimeShiftState:
    """Current state of the combined regime shift detector."""
    regime: str
    regime_label: str
    hmm_probabilities: dict[str, float]
    confidence: float
    position_scale: float
    cusum_triggered: bool
    hmm_state: MarketState
    observations: int
    alerts_count: int


class RegimeShiftDetector:
    """Combines HMM and CUSUM for proactive regime shift detection.

    When either mechanism detects an anomaly, the detector:
    1. Logs the alert
    2. Reduces the recommended position scale
    3. Gradually restores position scale as the market stabilizes

    Parameters
    ----------
    cusum_threshold : float
        CUSUM detection threshold. Default 5.0.
    cusum_drift : float
        CUSUM drift allowance. Default 0.5.
    hmm_lookback : int
        HMM parameter estimation window. Default 200.
    restore_rate : float
        Rate at which position_scale recovers toward 1.0 after an alert
        (per observation). Default 0.005.
    spike_position_scale : float
        Position scale during high-volatility spikes. Default 0.3.
    """

    def __init__(
        self,
        cusum_threshold: float = 5.0,
        cusum_drift: float = 0.5,
        hmm_lookback: int = 200,
        restore_rate: float = 0.005,
        spike_position_scale: float = 0.3,
    ) -> None:
        self.cusum = CUSUMFilter(
            threshold=cusum_threshold,
            drift=cusum_drift,
        )
        self.hmm = HiddenMarkovRegimeDetector(lookback=hmm_lookback)
        self.restore_rate = restore_rate
        self.spike_position_scale = spike_position_scale

        self._position_scale: float = 1.0
        self._alerts: list[AnomalyAlert] = []
        self._variance_buffer: list[float] = []
        self._variance_window: int = 20

    def update(self, log_return: float) -> tuple[MarketState, float, list[AnomalyAlert]]:
        """Process a new log-return and return (state, position_scale, alerts).

        Parameters
        ----------
        log_return : float
            The log-return of the latest price tick/bar.

        Returns
        -------
        tuple[MarketState, float, list[AnomalyAlert]]
            - Current HMM state
            - Recommended position scale (0.0 to 1.0)
            - Any alerts raised this observation
        """
        alerts: list[AnomalyAlert] = []

        # 1. HMM update
        hmm_state = self.hmm.update(log_return)
        state_probs = self.hmm.get_state_probabilities()

        # 2. CUSUM update on log-returns
        cusum_alert = self.cusum.update(log_return)
        if cusum_alert is not None:
            alerts.append(cusum_alert)
            self._position_scale = min(self._position_scale, cusum_alert.position_scale)

        # 3. Variance spike detection
        self._variance_buffer.append(log_return ** 2)
        if len(self._variance_buffer) > self._variance_window:
            self._variance_buffer.pop(0)
        if len(self._variance_buffer) >= self._variance_window:
            current_var = self._variance_buffer[-1]
            avg_var = sum(self._variance_buffer) / len(self._variance_buffer)
            if avg_var > 0 and current_var > 4.0 * avg_var:
                spike_alert = AnomalyAlert(
                    alert_type="variance_spike",
                    state=hmm_state,
                    confidence=min(current_var / (4.0 * avg_var), 1.0),
                    position_scale=self.spike_position_scale,
                    observation=log_return,
                    details={
                        "current_variance": round(current_var, 8),
                        "average_variance": round(avg_var, 8),
                        "ratio": round(current_var / avg_var, 2) if avg_var > 0 else 0,
                    },
                )
                alerts.append(spike_alert)
                self._position_scale = min(self._position_scale, self.spike_position_scale)

        # 4. HMM regime change detection
        if self.hmm._total_observations > self.hmm.lookback:
            confidence = self.hmm.get_confidence()
            if hmm_state == MarketState.HIGH_VOL and confidence > 0.6:
                hmm_alert = AnomalyAlert(
                    alert_type="hmm_regime_change",
                    state=hmm_state,
                    confidence=confidence,
                    position_scale=self.spike_position_scale,
                    observation=log_return,
                    details={
                        "regime": self.hmm.get_regime_label(),
                        "probabilities": state_probs,
                    },
                )
                alerts.append(hmm_alert)
                self._position_scale = min(self._position_scale, self.spike_position_scale)

        # 5. Gradually restore position scale
        if not alerts:
            self._position_scale = min(1.0, self._position_scale + self.restore_rate)

        self._alerts.extend(alerts)

        return hmm_state, self._position_scale, alerts

    def get_state(self) -> RegimeShiftState:
        """Get current detector state for diagnostics."""
        return RegimeShiftState(
            regime=self.hmm.get_regime_label(),
            regime_label=self.hmm.get_regime_label(),
            hmm_probabilities=self.hmm.get_state_probabilities(),
            confidence=self.hmm.get_confidence(),
            position_scale=self._position_scale,
            cusum_triggered=self.cusum._cusum_pos > 0 or self.cusum._cusum_neg > 0,
            hmm_state=self.hmm.current_state,
            observations=self.hmm._total_observations,
            alerts_count=len(self._alerts),
        )

    @property
    def alerts(self) -> list[AnomalyAlert]:
        return list(self._alerts)

    @property
    def position_scale(self) -> float:
        return self._position_scale

    # ── Persistence ───────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist detector state to JSON."""
        data = {
            "cusum": {
                "threshold": self.cusum.threshold,
                "drift": self.cusum.drift,
                "buffer": self.cusum._buffer,
                "cusum_pos": self.cusum._cusum_pos,
                "cusum_neg": self.cusum._cusum_neg,
                "observations": self.cusum._observations,
                "last_alert_at": self.cusum._last_alert_at,
            },
            "hmm": {
                "transition": self.hmm._transition,
                "emission_mean": self.hmm._emission_mean,
                "emission_std": self.hmm._emission_std,
                "state_probs": self.hmm._state_probs,
                "observations": self.hmm._observations[-200:],
                "total_observations": self.hmm._total_observations,
            },
            "position_scale": self._position_scale,
            "variance_buffer": self._variance_buffer,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RegimeShiftDetector":
        """Restore detector state from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        detector = cls(
            cusum_threshold=data["cusum"]["threshold"],
            cusum_drift=data["cusum"]["drift"],
        )
        detector.cusum._buffer = data["cusum"]["buffer"]
        detector.cusum._cusum_pos = data["cusum"]["cusum_pos"]
        detector.cusum._cusum_neg = data["cusum"]["cusum_neg"]
        detector.cusum._observations = data["cusum"]["observations"]
        detector.cusum._last_alert_at = data["cusum"]["last_alert_at"]

        detector.hmm._transition = data["hmm"]["transition"]
        detector.hmm._emission_mean = data["hmm"]["emission_mean"]
        detector.hmm._emission_std = data["hmm"]["emission_std"]
        detector.hmm._state_probs = data["hmm"]["state_probs"]
        detector.hmm._observations = data["hmm"]["observations"]
        detector.hmm._total_observations = data["hmm"]["total_observations"]

        detector._position_scale = data["position_scale"]
        detector._variance_buffer = data["variance_buffer"]
        return detector
