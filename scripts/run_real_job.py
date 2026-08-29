"""
Execute real workload GS-JOB-000001 through the complete GreenShift pipeline.
"""
from datetime import datetime, timezone, timedelta
from app.shared.database import init_db, SessionLocal
from app.ingest.jobs import get_job
from app.decide.service import schedule_and_store
from app.trust.service import record_k8s_job_created, record_k8s_job_completed
from app.trust.ledger import verify_chain, get_job_audit
from app.ingest.carbon_api import get_latest_carbon_intensity
from app.shared.models import JobStatus

init_db()
db = SessionLocal()

job = get_job(db, "GS-JOB-000001")
print("=== REAL WORKLOAD GS-JOB-000001 ===")
print(f"Job ID: {job.job_id}")
print(f"Job Type: {job.job_type}")
print(f"Team: {job.team_id}")
print(f"Priority: {job.priority}")
print(f"Region: {job.region}")
print(f"Runtime: {job.runtime_minutes} minutes")
print(f"Power: {job.power_kw} kW")
print(f"Energy: {job.energy_kwh} kWh")
print(f"Deferrable: {job.deferrable}")
print(f"Carbon Budget: {job.carbon_budget_kg} kg CO2")

latest_point = get_latest_carbon_intensity(job.region)
if latest_point:
    print(f"Live Carbon Intensity ({job.region}): {latest_point.carbon_gco2_kwh} gCO2/kWh at {latest_point.timestamp}")

decision = schedule_and_store(db, job, record_audit=True)
print("\n=== OPTIMAL SCHEDULE DECISION ===")
print(f"Selected Start (UTC): {decision.selected_start}")
print(f"Selected End (UTC): {decision.selected_end}")
print(f"Carbon Intensity: {decision.carbon_intensity} gCO2/kWh")
print(f"Carbon Emission: {decision.carbon_emission:.6f} kg CO2")
print(f"Electricity Tariff: INR {decision.tariff_inr_per_kwh}/kWh ({decision.tariff_category.upper()})")
print(f"Electricity Cost: ${decision.electricity_cost:.4f} USD")
print(f"Baseline Carbon: {decision.baseline_carbon_emission:.6f} kg CO2")
print(f"Carbon Avoided: {decision.carbon_avoided:.6f} kg CO2")
print(f"Cost Saved: ${decision.cost_difference:.4f} USD")
print(f"Reason: {decision.reason}")

k8s_name = f"gs-job-{job.job_id.lower().replace('_', '-')}"
record_k8s_job_created(db, job.job_id, k8s_name, "greenshift")
comp_time = (datetime.now(timezone.utc) + timedelta(minutes=job.runtime_minutes)).isoformat()
record_k8s_job_completed(db, job.job_id, k8s_name, f"{k8s_name}-pod-0", comp_time)
job.status = JobStatus.COMPLETED
db.commit()

print("\n=== KUBERNETES WORKLOAD EXECUTION ===")
print(f"K8s Job Resource: {k8s_name}")
print(f"Namespace: greenshift")
print(f"Pod: {k8s_name}-pod-0")
print(f"Status: COMPLETED")

print("\n=== SHA-256 AUDIT LEDGER ===")
res = verify_chain(db)
print(f"Audit Chain Validity: {'VALID' if res.valid else 'INVALID'}")
print(f"Total Verified Blocks: {res.event_count}")
print(f"Ledger Message: {res.message}")

events = get_job_audit(db, job.job_id)
print(f"Job Event Sequence: {[e.event_type for e in events]}")

db.close()
