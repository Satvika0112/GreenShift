-- GreenShift PostgreSQL Schema Sync Migration
-- Ensures all tables have all expected columns from models.py

-- Jobs table
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS workload_name VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS timezone VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_type VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS earliest_start_time TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS energy_kwh DOUBLE PRECISION;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS "deferrable" BOOLEAN;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tariff_plan VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_by VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tenant_id VARCHAR;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS submitted_by_user_id INTEGER;

-- Schedule decisions table
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS optimization_score DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS tariff_inr_per_kwh DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS tariff_category VARCHAR;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS region_id VARCHAR;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS tariff_plan VARCHAR;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS currency VARCHAR;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS native_cost DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS baseline_native_cost DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS baseline_end TIMESTAMP WITH TIME ZONE;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS carbon_reduction_pct DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS cost_reduction_pct DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS scheduling_delay_hours DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS sla_met BOOLEAN;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS scheduling_method VARCHAR;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS slot_utilization_pct DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS demand_predicted DOUBLE PRECISION;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS spilled_from_preferred BOOLEAN;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS ml_advisor_used BOOLEAN;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS candidates_json TEXT;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS rejected_candidates_json TEXT;
ALTER TABLE schedule_decisions ADD COLUMN IF NOT EXISTS recommended_candidate_json TEXT;

-- Regional tariffs table
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS tod_block VARCHAR;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS base_energy_rate DOUBLE PRECISION;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS tod_adder DOUBLE PRECISION;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS is_peak_hour BOOLEAN;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS is_solar_hour BOOLEAN;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS is_night_hour BOOLEAN;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS category VARCHAR;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS voltage VARCHAR;
ALTER TABLE regional_tariffs ADD COLUMN IF NOT EXISTS tariff_year VARCHAR;

-- Carbon data table
ALTER TABLE carbon_data ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE carbon_data ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE carbon_data ADD COLUMN IF NOT EXISTS em_zone VARCHAR;
ALTER TABLE carbon_data ADD COLUMN IF NOT EXISTS confidence_status VARCHAR;
ALTER TABLE carbon_data ADD COLUMN IF NOT EXISTS is_fallback BOOLEAN;

-- Users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status VARCHAR;
