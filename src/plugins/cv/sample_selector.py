"""CV sample selection strategy combining uncertainty and diversity.

Implements the SampleSelector protocol for computer vision tasks.
Uses greedy coreset selection to balance high uncertainty with
diversity in the selected batch.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


class UncertaintyDiversitySelector:
    """Select samples by combining uncertainty ranking with diversity.

    Greedy approach:
    1. Rank all candidates by uncertainty (descending).
    2. Take the most uncertain sample as seed.
    3. For remaining slots, pick the candidate that maximizes a weighted
       combination of uncertainty and minimum distance to already-selected
       samples (in uncertainty-score space).

    This prevents clustering of very similar uncertain samples when the
    budget is small relative to the pool.

    Args:
        diversity_weight: Weight for diversity term (0.0 = pure uncertainty,
            1.0 = pure diversity). Default 0.3.
    """

    def __init__(self, diversity_weight: float = 0.3) -> None:
        self._diversity_weight = max(0.0, min(1.0, diversity_weight))

    def select(self, uncertainties: list[float], budget: int) -> list[int]:
        """Select sample indices balancing uncertainty and diversity.

        Args:
            uncertainties: Uncertainty scores per sample (higher = more uncertain).
            budget: Maximum number of samples to select.

        Returns:
            Indices of selected samples, ordered by selection priority.
        """
        n = len(uncertainties)
        if n == 0:
            return []

        budget = min(budget, n)

        # Fast path: if budget covers all or diversity weight is zero,
        # just return top-K by uncertainty.
        if budget >= n or self._diversity_weight == 0.0:
            ranked = sorted(range(n), key=lambda i: uncertainties[i], reverse=True)
            return ranked[:budget]

        # Normalize uncertainties to [0, 1] for fair weighting
        u_min = min(uncertainties)
        u_max = max(uncertainties)
        u_range = u_max - u_min
        if u_range < 1e-12:
            # All uncertainties are identical — just return first budget indices
            return list(range(budget))

        norm_u = [(u - u_min) / u_range for u in uncertainties]

        # Greedy coreset selection
        selected: list[int] = []
        remaining = set(range(n))

        # Seed: most uncertain sample
        seed = max(remaining, key=lambda i: norm_u[i])
        selected.append(seed)
        remaining.discard(seed)

        w_u = 1.0 - self._diversity_weight
        w_d = self._diversity_weight

        for _ in range(budget - 1):
            if not remaining:
                break

            best_idx = -1
            best_score = -math.inf

            for candidate in remaining:
                # Minimum distance to any already-selected sample
                min_dist = min(abs(norm_u[candidate] - norm_u[s]) for s in selected)
                score = w_u * norm_u[candidate] + w_d * min_dist
                if score > best_score:
                    best_score = score
                    best_idx = candidate

            selected.append(best_idx)
            remaining.discard(best_idx)

        logger.info(
            "Selected %d/%d samples (diversity_weight=%.2f)",
            len(selected),
            n,
            self._diversity_weight,
        )
        return selected
