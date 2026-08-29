"""
End-to-end verification script for real data sources integration.
"""
from app.shared.database import init_db, SessionLocal
from app.ingest.service import load_csv_jobs_to_db, get_ingest_status
from app.ingest.jobs import get_job
from app.decide.service import schedule_and_store
from app.trust.ledger import verify_chain, get_job_audit

# Initialize database schema and run migrations first
init_db()

db = SessionLocal()

print("=== 1. BULK LOAD CSV ===")
count, errors = load_csv_jobs_to_db(db, "data/greenshift_workloads_final.csv")
print(f"Jobs Loaded: {count}, Errors: {len(errors)}")

print("\n=== 2. DATA SOURCE STATUS ===")
status = get_ingest_status(db)
print(f"Carbon Source: {status['carbon']['source']} (API Key configured: {status['carbon']['api_key_configured']})")
print(f"Tariff Source: {status['tariff']['source']} (Categories: {status['tariff']['categories_loaded']})")
print(f"Jobs in DB: {status['system']['jobs_in_database']}")

print("\n=== 3. SCHEDULE REAL WORKLOAD GS-JOB-000001 ===")
job = get_job(db, "GS-JOB-000001")
print(f"Found Job: {job.job_id} | Type: {job.job_type} | Team: {job.team_id} | Region: {job.region} | Energy: {job.energy_kwh} kWh | Deferrable: {job.deferrable}")
decision = schedule_and_store(db, job, record_audit=True)
print(f"Decision ID: {decision.job_id}")
print(f"Selected Start (UTC): {decision.selected_start}")
print(f"Selected End (UTC): {decision.selected_end}")
print(f"Carbon Intensity: {decision.carbon_intensity} gCO2/kWh")
print(f"Carbon Emission: {decision.carbon_emission:.6f} kg CO2")
print(f"Electricity Tariff: INR {decision.tariff_inr_per_kwh}/kWh ({decision.tariff_category.upper()})")
print(f"Electricity Cost: ${decision.electricity_cost:.4f} USD")
print(f"Carbon Avoided: {decision.carbon_avoided:.6f} kg CO2")
print(f"Cost Saved: ${decision.cost_difference:.4f} USD")
print(f"Reason: {decision.reason}")

print("\n=== 4. VERIFY SHA-256 AUDIT CHAIN ===")
audit_res = verify_chain(db)
print(f"Audit Chain Valid: {audit_res.valid} | Total Verified Records: {audit_res.event_count}")
events = get_job_audit(db, "GS-JOB-000001")
print(f"Job Events for GS-JOB-000001: {[e.event_type for e in events]}")

db.close()
