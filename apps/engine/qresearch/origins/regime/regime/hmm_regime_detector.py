from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


@dataclass(slots=True)
class RegimeDetectionResult:
    """Outputs from the HMM regime detector."""

    states: pd.Series
    labeled_regimes: pd.Series
    state_probabilities: pd.DataFrame
    transition_matrix: pd.DataFrame
    state_statistics: pd.DataFrame


class HMMRegimeDetector:
    """Gaussian Hidden Markov Model for market regime inference."""

    def __init__(
        self,
        n_regimes: int = 3,
        covariance_type: str = "full",
        n_iter: int = 250,
        random_state: int = 42,
    ) -> None:
        self.n_regimes = n_regimes
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.model = GaussianHMM(
            n_components=n_regimes,
            covariance_type=covariance_type,
            n_iter=n_iter,
            random_state=random_state,
        )
        self.state_label_map_: dict[int, str] = {}
        self.transition_matrix_: pd.DataFrame | None = None

    def fit_predict(self, features: pd.DataFrame) -> RegimeDetectionResult:
        """Fit the HMM and return inferred states and labels."""
        validated_features = self._validate_features(features)
        scaled_features = self.scaler.fit_transform(validated_features)
        self.model.fit(scaled_features)

        states = pd.Series(
            self.model.predict(scaled_features),
            index=validated_features.index,
            name="state",
        )
        state_probabilities = pd.DataFrame(
            self.model.predict_proba(scaled_features),
            index=validated_features.index,
            columns=[f"state_{state}" for state in range(self.n_regimes)],
        )
        self.transition_matrix_ = pd.DataFrame(
            self.model.transmat_,
            index=[f"state_{state}" for state in range(self.n_regimes)],
            columns=[f"state_{state}" for state in range(self.n_regimes)],
        )

        state_statistics = self._compute_state_statistics(validated_features, states)
        self.state_label_map_ = self._label_states(state_statistics)
        labeled_regimes = states.map(self.state_label_map_).rename("regime")

        return RegimeDetectionResult(
            states=states,
            labeled_regimes=labeled_regimes,
            state_probabilities=state_probabilities,
            transition_matrix=self.transition_matrix_,
            state_statistics=state_statistics,
        )

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Predict hidden states for new observations using a fitted model."""
        validated_features = self._validate_features(features)
        scaled = self.scaler.transform(validated_features)
        states = self.model.predict(scaled)
        return pd.Series(states, index=validated_features.index, name="state")

    def state_labels(self) -> dict[int, str]:
        """Return the fitted state-to-regime label map."""
        if not self.state_label_map_:
            raise RuntimeError("The HMM must be fitted before reading state labels.")
        return dict(self.state_label_map_)

    def _validate_features(self, features: pd.DataFrame) -> pd.DataFrame:
        if features.empty:
            raise ValueError("Feature frame is empty.")

        validated = features.replace([np.inf, -np.inf], np.nan).dropna(how="any")
        if len(validated) <= self.n_regimes * 10:
            raise ValueError("Not enough observations to fit the requested HMM.")

        return validated

    @staticmethod
    def _compute_state_statistics(features: pd.DataFrame, states: pd.Series) -> pd.DataFrame:
        enriched = features.copy()
        enriched["state"] = states
        stats = enriched.groupby("state").agg(
            mean_return=("daily_return", "mean"),
            volatility=("rolling_volatility_20d", "mean"),
            ma_spread=("ma_spread_50_200", "mean"),
            momentum=("momentum_20d", "mean"),
            observations=("daily_return", "size"),
        )
        return stats.sort_index()

    def _label_states(self, state_statistics: pd.DataFrame) -> dict[int, str]:
        if state_statistics.empty:
            raise ValueError("State statistics are empty.")

        remaining_states = list(state_statistics.index)
        label_map: dict[int, str] = {}

        high_vol_state = int(state_statistics["volatility"].idxmax())
        label_map[high_vol_state] = "High Volatility"
        remaining_states.remove(high_vol_state)

        if remaining_states:
            bull_state = int(state_statistics.loc[remaining_states, "mean_return"].idxmax())
            label_map[bull_state] = "Bull"
            remaining_states.remove(bull_state)

        if remaining_states:
            bear_state = int(state_statistics.loc[remaining_states, "mean_return"].idxmin())
            label_map[bear_state] = "Bear"
            remaining_states.remove(bear_state)

        for state in remaining_states:
            label_map[int(state)] = f"Regime {state}"

        return label_map
