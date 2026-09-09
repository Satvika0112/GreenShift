import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PlusCircle,
  Sparkles,
  Zap,
  Leaf,
  Clock,
  HardDrive,
  Cpu,
  ArrowRight,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { workloadsApi, sustainabilityApi } from '../api/endpoints';
import { CreateJobInput, RegionInfo } from '../types/api';
import { useAuth } from '../context/AuthContext';

const PRESET_TEMPLATES = [
  {
    name: 'LLM 70B Benchmark Run',
    container_image: 'docker.io/library/ubuntu:22.04',
    job_type: 'SIMULATION',
    runtime_minutes: 180,
    power_kw: 3.8,
    cpu_request: '2000m',
    memory_request: '4096Mi',
    carbon_budget_kg: 25.0,
    priority: 'HIGH',
    region: 'IN-TG',
  },
  {
    name: 'Monte Carlo Financial Risk',
    container_image: 'docker.io/library/python:3.11-slim',
    job_type: 'BATCH',
    runtime_minutes: 90,
    power_kw: 2.2,
    cpu_request: '1000m',
    memory_request: '2048Mi',
    carbon_budget_kg: 10.0,
    priority: 'MEDIUM',
    region: 'IN-GJ',
  },
  {
    name: 'Genomic Alignment Pipeline',
    container_image: 'docker.io/library/alpine:latest',
    job_type: 'DATA_PROCESSING',
    runtime_minutes: 240,
    power_kw: 4.5,
    cpu_request: '2000m',
    memory_request: '8192Mi',
    carbon_budget_kg: 35.0,
    priority: 'HIGH',
    region: 'IN-WB',
  },
];

export const SubmitWorkloadPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [regions, setRegions] = useState<RegionInfo[]>([]);

  // Default deadline 24 hours from now in ISO string
  const defaultDeadline = new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 16);

  const [formData, setFormData] = useState({
    name: '',
    team_id: user?.team_id || 'engineering',
    region: 'IN-TG',
    deadline: defaultDeadline,
    runtime_minutes: 120,
    power_kw: 3.0,
    cpu_request: '500m',
    memory_request: '512Mi',
    container_image: 'docker.io/library/ubuntu:22.04',
    carbon_budget_kg: 20.0,
    priority: 'MEDIUM',
    job_type: 'DATA_PROCESSING',
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successJobId, setSuccessJobId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const loadRegions = async () => {
      try {
        const res = await sustainabilityApi.getRegions();
        if (Array.isArray(res) && res.length > 0) {
          setRegions(res);
        }
      } catch {
        // Fallback standard regions
        setRegions([
          { region_id: 'IN-TG', country: 'India', region_name: 'Telangana', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-SO', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
          { region_id: 'IN-GJ', country: 'India', region_name: 'Gujarat', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-WE', default_plan: 'HTP-I', supported_tariff_plans: [], aliases: [], is_active: true },
          { region_id: 'IN-WB', country: 'India', region_name: 'West Bengal', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-EA', default_plan: 'ToD', supported_tariff_plans: [], aliases: [], is_active: true },
          { region_id: 'IN-HP', country: 'India', region_name: 'Himachal Pradesh', timezone: 'Asia/Kolkata', currency: 'INR', electricity_maps_zone: 'IN-NO', default_plan: 'Flat', supported_tariff_plans: [], aliases: [], is_active: true },
          { region_id: 'SE', country: 'Sweden', region_name: 'Nordic Grid (SE-3)', timezone: 'Europe/Stockholm', currency: 'SEK', electricity_maps_zone: 'SE-3', default_plan: 'Spot', supported_tariff_plans: [], aliases: [], is_active: true },
        ]);
      }
    };
    loadRegions();
  }, []);

  const applyTemplate = (template: typeof PRESET_TEMPLATES[0]) => {
    setFormData((prev) => ({
      ...prev,
      ...template,
    }));
  };

  // Instant energy & carbon estimation
  const estimatedKwh = (formData.power_kw * (formData.runtime_minutes / 60)).toFixed(2);
  const estimatedBaselineCarbonKg = (parseFloat(estimatedKwh) * 0.40).toFixed(2);
  const estimatedGreenCarbonKg = (parseFloat(estimatedKwh) * 0.12).toFixed(2);
  const estimatedCarbonSavingsPct = Math.round((1 - parseFloat(estimatedGreenCarbonKg) / parseFloat(estimatedBaselineCarbonKg)) * 100);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) {
      setErrorMsg('Workload name is required');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      // Build ISO UTC string for deadline
      const deadlineDate = new Date(formData.deadline);
      if (isNaN(deadlineDate.getTime()) || deadlineDate.getTime() <= Date.now()) {
        setErrorMsg('Deadline must be a valid future timestamp.');
        setIsSubmitting(false);
        return;
      }

      const input: CreateJobInput = {
        name: formData.name.trim(),
        team_id: user?.team_id || formData.team_id || 'engineering',
        region: formData.region,
        deadline: deadlineDate.toISOString(),
        runtime_minutes: Number(formData.runtime_minutes),
        power_kw: Number(formData.power_kw),
        container_image: formData.container_image.trim(),
        cpu_request: formData.cpu_request.trim(),
        memory_request: formData.memory_request.trim(),
        carbon_budget_kg: formData.carbon_budget_kg ? Number(formData.carbon_budget_kg) : undefined,
        priority: formData.priority,
        job_type: formData.job_type,
      };

      const created = await workloadsApi.createJob(input, false);
      const newId = created.job_id;
      setSuccessJobId(newId);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        // Pydantic validation error array
        const errorMessages = detail.map((d: any) => `${d.loc?.slice(-1)?.[0] || 'field'}: ${d.msg}`).join('; ');
        setErrorMsg(`Validation error: ${errorMessages}`);
      } else if (typeof detail === 'string') {
        setErrorMsg(detail);
      } else {
        setErrorMsg('Failed to submit workload. Verify connection to backend.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem', maxWidth: '1000px', margin: '0 auto' }}>
      <PageHeader
        title="Submit New Workload"
        subtitle="Register containerized batch compute with carbon budgets, execution constraints, and SLA deadlines"
      />

      {/* Preset Quick-Fill Templates */}
      <GlassCard title="Quick Templates (1-Click Fill)">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.85rem' }}>
          {PRESET_TEMPLATES.map((tmpl) => (
            <button
              key={tmpl.name}
              type="button"
              className="btn btn-secondary"
              onClick={() => applyTemplate(tmpl)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                padding: '0.85rem 1rem',
                gap: '0.25rem',
                textAlign: 'left',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 700, fontSize: '0.84rem' }}>{tmpl.name}</span>
                <Sparkles size={14} color="#10b981" />
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {tmpl.region} • {tmpl.runtime_minutes}m • {tmpl.power_kw}kW • {tmpl.cpu_request} CPU / {tmpl.memory_request}
              </span>
            </button>
          ))}
        </div>
      </GlassCard>

      {/* Success Banner */}
      {successJobId && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(6, 182, 212, 0.1))',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-md)',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <CheckCircle2 size={24} color="#10b981" />
            <div>
              <h3 style={{ color: '#ffffff' }}>Workload Ingested Successfully!</h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Job ID <strong style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>{successJobId}</strong> has been stored in the database under team <strong>{user?.team_id || formData.team_id}</strong>.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button
              className="btn btn-primary"
              onClick={() => navigate(`/scheduling?jobId=${successJobId}`)}
            >
              <Cpu size={15} />
              <span>Optimize Schedule Now</span>
              <ArrowRight size={14} />
            </button>
            <button className="btn btn-secondary" onClick={() => navigate('/workloads')}>
              View Workloads Table
            </button>
          </div>
        </div>
      )}

      {/* Main Submission Form */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <GlassCard title="Workload Configuration">
          {errorMsg && (
            <div
              style={{
                padding: '0.75rem 1rem',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid #ef4444',
                color: '#ef4444',
                borderRadius: 'var(--radius-sm)',
                marginBottom: '1rem',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <AlertCircle size={16} />
              <span>{errorMsg}</span>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
            <div className="form-group">
              <label className="form-label">Workload Name *</label>
              <input
                type="text"
                className="input"
                placeholder="e.g. llm-eval-benchmark-70b"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Container Image URI *</label>
              <input
                type="text"
                className="input"
                placeholder="docker.io/library/ubuntu:22.04"
                value={formData.container_image}
                onChange={(e) => setFormData({ ...formData, container_image: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Target Grid Region *</label>
              <select
                className="select"
                value={formData.region}
                onChange={(e) => setFormData({ ...formData, region: e.target.value })}
              >
                {regions.map((r) => (
                  <option key={r.region_id} value={r.region_id}>
                    {r.region_name} ({r.region_id}) • {r.country}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">SLA Deadline (Local/UTC) *</label>
              <input
                type="datetime-local"
                className="input"
                value={formData.deadline}
                onChange={(e) => setFormData({ ...formData, deadline: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Runtime Estimate (Minutes) *</label>
              <input
                type="number"
                min="1"
                max="10080"
                className="input"
                value={formData.runtime_minutes}
                onChange={(e) => setFormData({ ...formData, runtime_minutes: parseInt(e.target.value, 10) || 60 })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Average Power Draw (kW) *</label>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="100000"
                className="input"
                value={formData.power_kw}
                onChange={(e) => setFormData({ ...formData, power_kw: parseFloat(e.target.value) || 1.0 })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">CPU Request (e.g. 500m, 2000m, 4) *</label>
              <input
                type="text"
                className="input"
                placeholder="500m"
                value={formData.cpu_request}
                onChange={(e) => setFormData({ ...formData, cpu_request: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Memory Request (e.g. 512Mi, 4Gi) *</label>
              <input
                type="text"
                className="input"
                placeholder="512Mi"
                value={formData.memory_request}
                onChange={(e) => setFormData({ ...formData, memory_request: e.target.value })}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Carbon Budget Cap (kg CO₂e)</label>
              <input
                type="number"
                step="0.5"
                min="0"
                className="input"
                placeholder="e.g. 20.0 (Leave empty for unconstrained)"
                value={formData.carbon_budget_kg || ''}
                onChange={(e) => setFormData({ ...formData, carbon_budget_kg: parseFloat(e.target.value) || 0 })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Priority Policy</label>
              <select
                className="select"
                value={formData.priority}
                onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
              >
                <option value="CRITICAL">CRITICAL (Immediate SLA Priority)</option>
                <option value="HIGH">HIGH (Constrained Shiftability)</option>
                <option value="MEDIUM">MEDIUM (Standard Deferrable Workload)</option>
                <option value="LOW">LOW (Highly Deferrable Opportunistic)</option>
              </select>
            </div>
          </div>
        </GlassCard>

        {/* Live Estimation Card */}
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem 1.5rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <Zap size={20} color="#38bdf8" />
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Estimated Energy Consumption</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#ffffff' }}>
                {estimatedKwh} kWh
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Baseline Carbon Projection</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#ef4444' }}>
                ~{estimatedBaselineCarbonKg} kg CO₂
              </div>
            </div>

            <div style={{ width: '1px', height: '24px', background: 'var(--border-default)' }} />

            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>GreenShift Target Reduction</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#10b981' }}>
                ▼ ~{estimatedCarbonSavingsPct}% Avoidance
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
            <PlusCircle size={16} className={isSubmitting ? 'animate-spin' : ''} />
            <span>{isSubmitting ? 'Ingesting Workload...' : 'Submit Workload'}</span>
          </button>
        </div>
      </form>
    </div>
  );
};
