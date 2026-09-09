"""
ML Demand Forecaster (Layer 2 Optional Advisor).
Predicts future job arrival demand to gently nudge non-urgent jobs away from peak contention hours.

CAUSAL INVARIANT:
- This forecaster MUST NEVER train on ScheduleDecisionORM.selected_start.
- It ONLY trains on JobORM.submitted_at (workload arrival timestamps).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sqlalchemy.orm import Session

from app.shared.models import JobORM


# Supported regions encoding mapping
REGION_MAP = {
    "us-east-1": 0,
    "us-west-2": 1,
    "eu-west-1": 2,
    "ap-southeast-1": 3,
    "southindia": 4,
}


def build_arrival_training_data(db: Session) -> pd.DataFrame:
    """
    Extract arrival timestamps (JobORM.submitted_at) and aggregate into
    hourly arrival counts by (hour_of_day, day_of_week, region_id).

    STRICT CAUSAL INVARIANT:
    No ScheduleDecisionORM or selected_start data is accessed here.
    """
    jobs = db.query(JobORM.submitted_at, JobORM.region).all()
    if not jobs:
        return pd.DataFrame(columns=["hour_of_day", "day_of_week", "region_code", "arrival_count"])

    records = []
    for submitted_at, region_id in jobs:
        if submitted_at is None:
            continue
        # Normalize to UTC
        if submitted_at.tzinfo is None:
            dt_utc = submitted_at.replace(tzinfo=timezone.utc)
        else:
            dt_utc = submitted_at.astimezone(timezone.utc)

        reg_code = REGION_MAP.get(region_id, 0)
        records.append({
            "hour_of_day": dt_utc.hour,
            "day_of_week": dt_utc.weekday(),
            "region_code": reg_code,
        })

    if not records:
        return pd.DataFrame(columns=["hour_of_day", "day_of_week", "region_code", "arrival_count"])

    df = pd.DataFrame(records)
    # Group by features to get count of arrivals per hour/day/region pattern
    aggregated = df.groupby(["hour_of_day", "day_of_week", "region_code"]).size().reset_index(name="arrival_count")
    return aggregated


class DemandForecaster:
    """
    Gradient Boosting Regressor predicting arrival demand pressure.
    Normalizes predicted arrival count into a [0.0, 1.0] pressure score.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "models",
            "demand_forecaster.joblib"
        )
        self.model: Optional[GradientBoostingRegressor] = None
        self.max_arrival_val: float = 10.0  # Normalization denominator
        self.is_trained: bool = False
        self.training_sample_count: int = 0
        self.last_trained_at: Optional[datetime] = None

        # Attempt to load pre-existing model if available
        if os.path.exists(self.model_path):
            try:
                self.load(self.model_path)
            except Exception:
                self.model = None
                self.is_trained = False

    def train(self, db: Session) -> Dict[str, Any]:
        """
        Train GradientBoostingRegressor on historical job arrivals.
        Strictly obeys causal invariant: JobORM.submitted_at only.
        """
        df = build_arrival_training_data(db)

        if len(df) < 5:
            # Synthetic bootstrap so the forecaster works even with minimal or fresh DB
            bootstrap_data = []
            for h in range(24):
                for d in range(7):
                    for r_code in REGION_MAP.values():
                        # Realistic diurnal pattern: higher daytime, lower off-peak
                        base_val = 4.0 if 9 <= h <= 18 else 1.0
                        bootstrap_data.append({
                            "hour_of_day": h,
                            "day_of_week": d,
                            "region_code": r_code,
                            "arrival_count": base_val,
                        })
            df = pd.DataFrame(bootstrap_data)

        X = df[["hour_of_day", "day_of_week", "region_code"]]
        y = df["arrival_count"]

        reg = GradientBoostingRegressor(
            n_estimators=50,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        reg.fit(X, y)

        self.model = reg
        self.max_arrival_val = max(float(y.max()), 1.0)
        self.is_trained = True
        self.training_sample_count = len(df)
        self.last_trained_at = datetime.now(timezone.utc)

        # Save model
        self.save()

        return {
            "status": "success",
            "samples_trained": self.training_sample_count,
            "max_arrival_val": round(self.max_arrival_val, 2),
            "last_trained_at": self.last_trained_at.isoformat(),
        }

    def predict_demand_pressure(self, slot_start: datetime, region_id: str) -> float:
        """
        Predict demand pressure for a specific slot and region.
        Returns bounded float in [0.0, 1.0].
        If model is untrained, gracefully degrades to 0.0 (neutral).
        """
        if not self.is_trained or self.model is None:
            return 0.0

        if slot_start.tzinfo is None:
            dt_utc = slot_start.replace(tzinfo=timezone.utc)
        else:
            dt_utc = slot_start.astimezone(timezone.utc)

        r_code = REGION_MAP.get(region_id, 0)
        df_feat = pd.DataFrame(
            [{"hour_of_day": dt_utc.hour, "day_of_week": dt_utc.weekday(), "region_code": r_code}]
        )

        try:
            pred = float(self.model.predict(df_feat)[0])
            norm_pred = max(0.0, min(1.0, pred / self.max_arrival_val))
            return round(norm_pred, 4)
        except Exception:
            return 0.0

    def predict_batch(self, items: List[Tuple[datetime, str]]) -> List[float]:
        """Batch predict demand pressure for list of (slot_start, region_id)."""
        if not items:
            return []
        if not self.is_trained or self.model is None:
            return [0.0] * len(items)

        features = []
        for slot_start, region_id in items:
            if slot_start.tzinfo is None:
                dt_utc = slot_start.replace(tzinfo=timezone.utc)
            else:
                dt_utc = slot_start.astimezone(timezone.utc)
            r_code = REGION_MAP.get(region_id, 0)
            features.append({
                "hour_of_day": dt_utc.hour,
                "day_of_week": dt_utc.weekday(),
                "region_code": r_code,
            })

        try:
            df_feats = pd.DataFrame(features)
            preds = self.model.predict(df_feats)
            return [round(max(0.0, min(1.0, float(p) / self.max_arrival_val)), 4) for p in preds]
        except Exception:
            return [0.0] * len(items)

    def save(self, path: Optional[str] = None) -> None:
        target_path = path or self.model_path
        Path(os.path.dirname(target_path)).mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "max_arrival_val": self.max_arrival_val,
            "is_trained": self.is_trained,
            "training_sample_count": self.training_sample_count,
            "last_trained_at": self.last_trained_at,
        }, target_path)

    def load(self, path: Optional[str] = None) -> bool:
        target_path = path or self.model_path
        if not os.path.exists(target_path):
            return False
        try:
            data = joblib.load(target_path)
            self.model = data.get("model")
            self.max_arrival_val = data.get("max_arrival_val", 10.0)
            self.is_trained = data.get("is_trained", False)
            self.training_sample_count = data.get("training_sample_count", 0)
            self.last_trained_at = data.get("last_trained_at")
            return bool(self.is_trained and self.model is not None)
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_trained": self.is_trained,
            "samples_trained": self.training_sample_count,
            "max_arrival_val": round(self.max_arrival_val, 2),
            "last_trained_at": self.last_trained_at.isoformat() if self.last_trained_at else None,
            "model_path": self.model_path,
        }


# Global singleton forecaster instance
_global_forecaster: Optional[DemandForecaster] = None

def get_demand_forecaster() -> DemandForecaster:
    global _global_forecaster
    if _global_forecaster is None:
        _global_forecaster = DemandForecaster()
    return _global_forecaster
