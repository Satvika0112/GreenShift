"""
Slot capacity tracking and enforcement for contention-aware scheduling.
Provides hourly capacity bounds for CPU, Memory, and GPU to prevent multi-job piling.

Two-Level Capacity Architecture:
1. Per-Job Feasibility (Spatial): Enforced by `ClusterResourceSnapshot.is_resource_feasible()`,
   verifying that an individual job can fit on at least one single Ready Kubernetes node.
2. Slot-Level Throughput (Temporal): Enforced here by `SlotCapacityRegistry`, tracking the aggregate
   consumption across multiple concurrent/overlapping jobs in each 1-hour window to avoid cluster
   saturation and resource contention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional, Any, List

from app.dispatch.k8s_state_collector import ClusterResourceSnapshot


@dataclass
class SlotCapacity:
    """Represents aggregate resource capacity and allocations for a single 1-hour window.
    
    Tracks cumulative multi-job allocation against cluster throughput limits.
    Note: Single-job node-level fit is validated separately via is_resource_feasible().
    """
    slot_start: datetime
    max_cpu: float
    max_memory_mib: float
    max_gpus: int
    allocated_cpu: float = 0.0
    allocated_memory_mib: float = 0.0
    allocated_gpus: int = 0
    job_count: int = 0

    @property
    def remaining_cpu(self) -> float:
        return max(0.0, self.max_cpu - self.allocated_cpu)

    @property
    def remaining_memory_mib(self) -> float:
        return max(0.0, self.max_memory_mib - self.allocated_memory_mib)

    @property
    def remaining_gpus(self) -> int:
        return max(0, self.max_gpus - self.allocated_gpus)

    @property
    def utilization_pct(self) -> float:
        if self.max_cpu <= 0:
            return 100.0
        return min(100.0, (self.allocated_cpu / self.max_cpu) * 100.0)

    def can_fit(self, cpu: float, mem_mib: float, gpus: int = 0) -> bool:
        """Check if requested resources fit within remaining capacity (with small float tolerance)."""
        eps = 1e-6
        if (self.allocated_cpu + cpu) > (self.max_cpu + eps):
            return False
        if (self.allocated_memory_mib + mem_mib) > (self.max_memory_mib + eps):
            return False
        if (self.allocated_gpus + gpus) > self.max_gpus:
            return False
        return True

    def allocate(self, cpu: float, mem_mib: float, gpus: int = 0) -> bool:
        """Allocate resources to this slot. Returns True if allocated, False if it cannot fit."""
        if not self.can_fit(cpu, mem_mib, gpus):
            return False
        self.allocated_cpu += cpu
        self.allocated_memory_mib += mem_mib
        self.allocated_gpus += gpus
        self.job_count += 1
        return True


class SlotCapacityRegistry:
    """
    Registry tracking SlotCapacity across regions and 1-hour time slots.
    Initializes from ClusterResourceSnapshot or explicit defaults.
    """

    def __init__(
        self,
        default_snapshot: Optional[ClusterResourceSnapshot] = None,
        default_max_cpu: float = 17.5,
        default_max_mem_mib: float = 71680.0,
        default_max_gpus: int = 3,
    ):
        if default_snapshot is not None:
            self.default_max_cpu = float(default_snapshot.free_cpu_cores)
            self.default_max_mem_mib = float(default_snapshot.free_memory_mib)
            self.default_max_gpus = int(default_snapshot.free_gpus)
        else:
            self.default_max_cpu = default_max_cpu
            self.default_max_mem_mib = default_max_mem_mib
            self.default_max_gpus = default_max_gpus

        # Key: (region_id, normalized_slot_start_utc)
        self.slots: Dict[Tuple[str, datetime], SlotCapacity] = {}

    @staticmethod
    def normalize_time(dt: datetime) -> datetime:
        """Truncate timestamp to top of hour in UTC."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.replace(minute=0, second=0, microsecond=0)

    def get_or_create_slot(self, region_id: str, dt: datetime) -> SlotCapacity:
        norm_dt = self.normalize_time(dt)
        key = (region_id, norm_dt)
        if key not in self.slots:
            self.slots[key] = SlotCapacity(
                slot_start=norm_dt,
                max_cpu=self.default_max_cpu,
                max_memory_mib=self.default_max_mem_mib,
                max_gpus=self.default_max_gpus,
            )
        return self.slots[key]

    def _get_span_hours(self, duration_hours: float) -> int:
        """Calculate number of 1-hour slots spanned by duration (minimum 1)."""
        return max(1, math.ceil(duration_hours))

    def can_fit(
        self,
        region_id: str,
        start_time: datetime,
        duration_hours: float,
        cpu: float,
        mem_mib: float,
        gpus: int = 0,
    ) -> bool:
        """Check if the job fits across all hourly slots it spans without creating empty slots."""
        norm_start = self.normalize_time(start_time)
        hours = self._get_span_hours(duration_hours)
        for i in range(hours):
            slot_dt = norm_start + timedelta(hours=i)
            key = (region_id, slot_dt)
            slot = self.slots.get(key)
            if slot is not None:
                if not slot.can_fit(cpu, mem_mib, gpus):
                    return False
            else:
                if (cpu > self.default_max_cpu + 1e-6) or (mem_mib > self.default_max_mem_mib + 1e-6) or (gpus > self.default_max_gpus):
                    return False
        return True

    def allocate(
        self,
        region_id: str,
        start_time: datetime,
        duration_hours: float,
        cpu: float,
        mem_mib: float,
        gpus: int = 0,
    ) -> bool:
        """Allocate resources across all hourly slots spanned. Atomic: rollback if any slot fails."""
        if not self.can_fit(region_id, start_time, duration_hours, cpu, mem_mib, gpus):
            return False

        norm_start = self.normalize_time(start_time)
        hours = self._get_span_hours(duration_hours)
        for i in range(hours):
            slot_dt = norm_start + timedelta(hours=i)
            slot = self.get_or_create_slot(region_id, slot_dt)
            slot.allocate(cpu, mem_mib, gpus)
        return True

    def utilization_at(self, region_id: str, dt: datetime) -> float:
        """Return utilization percentage for the slot covering dt."""
        norm_dt = self.normalize_time(dt)
        key = (region_id, norm_dt)
        if key in self.slots:
            return self.slots[key].utilization_pct
        return 0.0

    def get_contention_map(self) -> Dict[str, Any]:
        """Return serializable map of slot allocations and utilization."""
        result = []
        for (region, dt), slot in sorted(self.slots.items(), key=lambda x: (x[0][0], x[0][1])):
            result.append({
                "region_id": region,
                "slot_start": dt.isoformat(),
                "max_cpu": slot.max_cpu,
                "allocated_cpu": round(slot.allocated_cpu, 2),
                "remaining_cpu": round(slot.remaining_cpu, 2),
                "max_memory_mib": slot.max_memory_mib,
                "allocated_memory_mib": round(slot.allocated_memory_mib, 2),
                "max_gpus": slot.max_gpus,
                "allocated_gpus": slot.allocated_gpus,
                "job_count": slot.job_count,
                "utilization_pct": round(slot.utilization_pct, 1),
            })
        return {"total_slots": len(result), "slots": result}

    def get_summary(self) -> Dict[str, Any]:
        """Summary statistics across all tracked slots."""
        if not self.slots:
            return {
                "total_slots": 0,
                "max_utilization_pct": 0.0,
                "avg_utilization_pct": 0.0,
                "total_jobs_allocated": 0,
                "congested_slots_count": 0,
            }
        utils = [s.utilization_pct for s in self.slots.values()]
        jobs = sum(s.job_count for s in self.slots.values())
        congested = sum(1 for u in utils if u >= 80.0)
        return {
            "total_slots": len(self.slots),
            "max_utilization_pct": round(max(utils), 1),
            "avg_utilization_pct": round(sum(utils) / len(utils), 1),
            "total_jobs_allocated": jobs,
            "congested_slots_count": congested,
        }
