"""
Time Consistency Hardening Pass — manual workload scheduling time flow.

Traces and verifies the invariants required for manual workload scheduling:
  A. A future earliest_start_time is always respected as a lower bound.
  B. selected_end never exceeds the requested deadline.
  C. now earlier than requested start -> scheduler never starts early.
  D. now later than requested start (a past earliest_start_time) -> the
     scheduler clamps its effective start bound up to `now` (nothing can be
     dispatched into the past) — a deliberate, tested, logged decision, not
     a silent substitution of a still-valid future request.
  E. Exact boundary window (earliest + runtime == deadline) is feasible.
  F. A window shorter than the requested runtime is rejected at submission
     time with a clear validation error, not a generic infeasibility later.
  G. Timezone normalization: a naive local wall-clock time entered for a
     given execution region resolves to the correct UTC instant, and
     displays back correctly in that region's timezone.
  I. ASAP/immediate mode (non-deferrable, no earliest_start_time) uses `now`
     only because the user explicitly chose non-deferrable execution with no
     lower bound — never for a job that specified a real earliest_start_time.
  J. The /schedule/{job_id} API response exposes requested_earliest_start /
     requested_deadline consistently alongside selected_start/selected_end.

Root cause fixed: app.decide.scheduler._execute_schedule_job used
`earliest_start_time` directly as the candidate-generation lower bound with
no floor at the real current time, so a job whose earliest_start_time had
already passed while it sat in the queue could be scheduled to start in the
past. The fix clamps the *effective* scheduler bound to
`max(now, earliest_start_time)` while leaving the *requested* value (as
persisted on JobORM, and as validated at submission) completely untouched.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.decide.scheduler import schedule_job, _generate_candidate_slots
from app.shared.models import (
    CarbonDataPoint,
    JobSubmitRequest,
    TariffDataPoint,
    UserApprovalStatus,
    UserORM,
    UserRole,
)
from app.shared.auth import create_access_token, hash_password
from app.shared.timezone import normalize_to_utc, utc_to_region_time


@pytest.fixture()
def now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _flat_curves(now, hours=24, region="IN-TG", carbon=200.0, price=0.05):
    """Flat carbon/tariff curves — removes carbon/cost as a ranking factor
    so the deterministic earliest-start tie-break decides selected_start,
    making these tests about *time*, not about the optimization objective."""
    carbon_curve = [
        CarbonDataPoint(timestamp=now + timedelta(hours=i), region=region, carbon_gco2_kwh=carbon)
        for i in range(hours)
    ]
    tariff_curve = [
        TariffDataPoint(timestamp=now + timedelta(hours=i), region=region, price_per_kwh=price)
        for i in range(hours)
    ]
    return carbon_curve, tariff_curve


class TestFutureEarliestStartIsRespected:
    """A. selected_start must never be earlier than a future earliest_start_time."""

    def test_selected_start_never_before_requested_earliest_start(self, now):
        earliest = now + timedelta(hours=3)
        deadline = now + timedelta(hours=10)
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-A-001", team_id="team-a", deadline=deadline,
            runtime_minutes=60, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=earliest,
        )
        assert decision.selected_start >= earliest


class TestDeadlineNeverExceeded:
    """B. selected_end must never exceed the requested deadline."""

    def test_selected_end_never_after_requested_deadline(self, now):
        earliest = now + timedelta(hours=1)
        deadline = now + timedelta(hours=6)
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-B-001", team_id="team-a", deadline=deadline,
            runtime_minutes=90, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=earliest,
        )
        assert decision.selected_end <= deadline


class TestFutureRequestNeverStartsEarly:
    """C. now earlier than requested start -> never starts before it."""

    def test_scheduler_never_starts_before_a_future_requested_start(self, now):
        earliest = now + timedelta(hours=5)  # comfortably in the future
        deadline = now + timedelta(hours=20)
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-C-001", team_id="team-a", deadline=deadline,
            runtime_minutes=60, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=earliest, deferrable=True,
        )
        assert decision.selected_start >= earliest


class TestPastEarliestStartClampsToNow:
    """D. now later than requested start -> defined, tested clamp to now,
    never a literal past selected_start."""

    def test_past_earliest_start_time_does_not_produce_a_past_selected_start(self, now):
        past_earliest = now - timedelta(hours=5)
        deadline = now + timedelta(hours=10)
        carbon_curve, tariff_curve = _flat_curves(now - timedelta(hours=6), hours=30)

        decision = schedule_job(
            job_id="JOB-TIME-D-001", team_id="team-a", deadline=deadline,
            runtime_minutes=60, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=past_earliest, deferrable=True,
        )
        # The requested earliest_start_time (5h in the past) must never be
        # the effective start — real "now" (>= the floored `now` fixture)
        # is the binding floor instead.
        assert decision.selected_start >= now
        assert decision.selected_start != past_earliest

    def test_non_deferrable_past_earliest_start_pins_to_now_not_the_past(self, now):
        past_earliest = now - timedelta(hours=3)
        deadline = now + timedelta(hours=10)
        carbon_curve, tariff_curve = _flat_curves(now - timedelta(hours=4), hours=20)

        decision = schedule_job(
            job_id="JOB-TIME-D-002", team_id="team-a", deadline=deadline,
            runtime_minutes=30, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=past_earliest, deferrable=False,
        )
        assert decision.selected_start >= now


class TestExactBoundaryWindow:
    """E. earliest + runtime == deadline is a valid, feasible window."""

    def test_exact_fit_window_is_feasible(self, now):
        earliest = now + timedelta(hours=2)
        runtime_minutes = 120
        deadline = earliest + timedelta(minutes=runtime_minutes)  # exact fit
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-E-001", team_id="team-a", deadline=deadline,
            runtime_minutes=runtime_minutes, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=earliest, deferrable=False,
        )
        assert decision.selected_start == earliest
        assert decision.selected_end == deadline

    def test_window_generates_a_single_candidate_when_exact(self, now):
        earliest = now + timedelta(hours=2)
        deadline = earliest + timedelta(hours=2)
        slots = _generate_candidate_slots(earliest, deadline, runtime_minutes=120, deferrable=False)
        assert slots == [earliest]


class TestTooShortWindowRejectedAtSubmission:
    """F. Window shorter than runtime -> rejected with a clear validation
    error at submission time, not a generic scheduler infeasibility later."""

    def test_window_shorter_than_runtime_is_rejected(self, now):
        earliest = now + timedelta(hours=1)
        deadline = earliest + timedelta(minutes=30)  # only 30 minutes available
        with pytest.raises(ValidationError, match="Requested window is too short"):
            JobSubmitRequest(
                team_id="team-a", deadline=deadline, runtime_minutes=60,
                power_kw=1.0, region="IN-TG", container_image="python:3.10-slim",
                earliest_start_time=earliest,
            )

    def test_deadline_before_earliest_start_is_rejected(self, now):
        earliest = now + timedelta(hours=5)
        deadline = now + timedelta(hours=1)  # before earliest
        with pytest.raises(ValidationError, match="earliest_start_time must be before deadline"):
            JobSubmitRequest(
                team_id="team-a", deadline=deadline, runtime_minutes=30,
                power_kw=1.0, region="IN-TG", container_image="python:3.10-slim",
                earliest_start_time=earliest,
            )

    def test_valid_window_is_accepted(self, now):
        earliest = now + timedelta(hours=1)
        deadline = earliest + timedelta(hours=2)
        req = JobSubmitRequest(
            team_id="team-a", deadline=deadline, runtime_minutes=60,
            power_kw=1.0, region="IN-TG", container_image="python:3.10-slim",
            earliest_start_time=earliest,
        )
        assert req.earliest_start_time == earliest

    def test_no_feasible_candidate_raises_at_scheduling_time(self, now):
        """A window that IS internally valid (passes submission validation)
        can still be infeasible once real carbon/resource data is applied —
        that remains a scheduling-time ValueError, unchanged by this pass."""
        earliest = now + timedelta(hours=1)
        deadline = earliest + timedelta(minutes=90)
        # No carbon data at all for the window -> CARBON_DATA_UNAVAILABLE on every candidate.
        with pytest.raises(ValueError, match="Carbon data is unavailable"):
            schedule_job(
                job_id="JOB-TIME-F-002", team_id="team-a", deadline=deadline,
                runtime_minutes=60, power_kw=5.0, region="IN-TG",
                carbon_curve=[], tariff_curve=[],
                earliest_start_time=earliest,
            )


class TestTimezoneConversion:
    """G. A naive local wall-clock time for a region resolves to the correct
    UTC instant, and converts back to the same local wall-clock time."""

    def test_india_local_time_resolves_to_correct_utc_instant(self):
        # 2026-01-15 is outside any DST ambiguity for India (no DST observed).
        india_local = datetime(2026, 1, 15, 10, 0, 0)  # naive, IST wall-clock
        utc_instant = normalize_to_utc(india_local, region="IN-TG")
        # IST = UTC+5:30 -> 10:00 IST = 04:30 UTC
        assert utc_instant == datetime(2026, 1, 15, 4, 30, 0, tzinfo=timezone.utc)

        local_again, tz_abbr = utc_to_region_time(utc_instant, region="IN-TG")
        assert local_again.hour == 10 and local_again.minute == 0
        assert tz_abbr == "IST"

    def test_california_local_time_resolves_to_correct_utc_instant(self):
        # 2026-01-15 is standard time (PST, UTC-8) in California — no DST.
        ca_local = datetime(2026, 1, 15, 9, 0, 0)  # naive, PST wall-clock
        utc_instant = normalize_to_utc(ca_local, region="US-CA")
        assert utc_instant == datetime(2026, 1, 15, 17, 0, 0, tzinfo=timezone.utc)

        local_again, tz_abbr = utc_to_region_time(utc_instant, region="US-CA")
        assert local_again.hour == 9 and local_again.minute == 0
        assert tz_abbr == "PST"

    def test_naive_datetime_without_region_or_timezone_is_rejected(self):
        with pytest.raises(ValueError):
            normalize_to_utc(datetime(2026, 1, 15, 10, 0, 0))

    def test_browser_timezone_never_used_an_aware_utc_input_passes_through_unchanged(self):
        """An already-aware timestamp (as if it were, e.g., a browser's own
        local zone) is converted to its UTC equivalent directly — region is
        never consulted to reinterpret an already-unambiguous instant."""
        aware = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        result = normalize_to_utc(aware, region="IN-TG")  # region must be ignored here
        assert result == datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)


class TestAsapModeOnlyUsesNowWhenExplicit:
    """I. `now` is used as the scheduling floor only when no earliest_start_time
    was requested at all (the closest existing equivalent of an explicit
    "ASAP" selection: non-deferrable + no lower bound) — never when a real
    earliest_start_time was supplied."""

    def test_no_earliest_start_and_non_deferrable_schedules_at_now(self, now):
        deadline = now + timedelta(hours=6)
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-I-001", team_id="team-a", deadline=deadline,
            runtime_minutes=30, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=None, deferrable=False,
        )
        real_now = datetime.now(timezone.utc)
        # selected_start must be "now-ish" (within a couple minutes of the
        # real current time captured just after scheduling), never a
        # fabricated future or past value.
        assert abs((decision.selected_start - real_now).total_seconds()) < 120

    def test_explicit_future_earliest_start_is_never_overridden_by_now(self, now):
        earliest = now + timedelta(hours=8)
        deadline = now + timedelta(hours=20)
        carbon_curve, tariff_curve = _flat_curves(now)

        decision = schedule_job(
            job_id="JOB-TIME-I-002", team_id="team-a", deadline=deadline,
            runtime_minutes=30, power_kw=5.0, region="IN-TG",
            carbon_curve=carbon_curve, tariff_curve=tariff_curve,
            earliest_start_time=earliest, deferrable=False,
        )
        assert decision.selected_start == earliest


class TestApiResponseRequestedVsSelected:
    """J. POST /schedule/{job_id} exposes requested_earliest_start /
    requested_deadline consistently alongside selected_start/selected_end."""

    def test_schedule_response_includes_consistent_requested_and_selected_windows(self, db, now):
        from fastapi.testclient import TestClient
        from app.api.main import app
        from app.shared.database import get_db

        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        try:
            user = UserORM(
                username="time_consistency_user", email="tcu@greenshift.io",
                hashed_password=hash_password("Pass123!"), role=UserRole.COMPANY_USER,
                tenant_id=None, team_id="team-time-consistency",
                approval_status=UserApprovalStatus.APPROVED.value, is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            token = create_access_token(user_id=user.id, username=user.username, role="COMPANY_USER", team_id=user.team_id)
            headers = {"Authorization": f"Bearer {token}"}

            earliest = now + timedelta(hours=1)
            deadline = now + timedelta(hours=10)
            resp = client.post("/api/v1/jobs", json={
                "job_id": "JOB-TIME-J-001",
                "team_id": "team-time-consistency",
                "deadline": deadline.isoformat(),
                "earliest_start_time": earliest.isoformat(),
                "runtime_minutes": 60,
                "power_kw": 2.0,
                "region": "IN-TG",
                "container_image": "python:3.10-slim",
            }, headers=headers)
            assert resp.status_code == 201, resp.text

            sched_resp = client.post("/api/v1/schedule/JOB-TIME-J-001", headers=headers)
            assert sched_resp.status_code == 200, sched_resp.text
            body = sched_resp.json()

            # Every serialized timestamp must carry an explicit UTC offset —
            # never a bare "naive-looking" string a browser's `new Date(...)`
            # would silently reinterpret in its own local timezone. This is
            # the regression proof for app.shared.timezone.ensure_utc: SQLite
            # (this test's DB) silently drops tzinfo on read, so without
            # ensure_utc() at the serialization boundary this assertion fails.
            for field in ("requested_earliest_start", "requested_deadline", "selected_start", "selected_end"):
                raw = body[field]
                assert raw is not None
                assert raw.endswith("+00:00") or raw.endswith("Z"), (
                    f"{field}={raw!r} has no explicit UTC offset — a browser would "
                    f"misinterpret it in its own local timezone"
                )

            def _aware(iso_str):
                # SQLite's DateTime(timezone=True) silently drops tzinfo on
                # read (a known, already-worked-around characteristic of this
                # project's SQLite test/dev DB — see the `if x.tzinfo is
                # None: x = x.replace(tzinfo=timezone.utc)` guards throughout
                # app/decide/scheduler.py and app/decide/service.py); a naive
                # value stored via normalize_to_utc is UTC by convention.
                dt = datetime.fromisoformat(iso_str)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

            assert body["requested_earliest_start"] is not None
            assert body["requested_deadline"] is not None
            requested_earliest = _aware(body["requested_earliest_start"])
            requested_deadline = _aware(body["requested_deadline"])
            selected_start = _aware(body["selected_start"])
            selected_end = _aware(body["selected_end"])

            assert selected_start >= requested_earliest
            assert selected_end <= requested_deadline
        finally:
            app.dependency_overrides.pop(get_db, None)
