"""Train the optional local logistic model from synthetic RevivePay cases.

Usage:
    python scripts/train_recovery_model.py

The command only reads the local synthetic database and writes a JSON artifact.
It never calls a payment provider, trains online, or transmits data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.container import get_clock  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.ml.local_logistic import save_artifact, train_logistic_model  # noqa: E402
from app.ml.synthetic_dataset import SyntheticRecoveryDatasetBuilder  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a local synthetic recovery model.")
    parser.add_argument("--limit", type=int, default=60, help="maximum synthetic cases")
    parser.add_argument("--artifact", type=str, default=None, help="output JSON artifact path")
    parser.add_argument("--steps", type=int, default=None, help="fixed gradient steps")
    args = parser.parse_args()

    settings = get_settings()
    artifact_path = args.artifact or settings.local_model_artifact_path
    steps = args.steps or settings.local_model_training_steps
    clock = get_clock(settings)
    with session_scope() as session:
        dataset = SyntheticRecoveryDatasetBuilder(session, clock, settings).build(limit=args.limit)
        artifact = train_logistic_model(
            dataset,
            seed=settings.simulation_seed,
            steps=steps,
            learning_rate=settings.local_model_learning_rate,
        )
    target = save_artifact(artifact, artifact_path)
    print(f"Trained {artifact.model_version} from {artifact.training_samples} synthetic examples.")
    print(f"Positive labels: {artifact.positive_samples}; artifact: {target}")
    print("Synthetic simulation only. No real payment transaction was attempted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
