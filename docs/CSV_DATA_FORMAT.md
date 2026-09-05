# GreenShift — CSV Data Format Guide

This document specifies the expected CSV format for providing carbon intensity
and electricity tariff data to GreenShift.

Using CSV files is the **highest-priority** data source — it overrides both
the live API and the synthetic mock data. This is ideal when:
- You have historical Indian grid data
- You have regional carbon/solar resource data
- API keys are not yet configured
- You want reproducible test results

---

## Configuration

Set environment variables to point GreenShift at your CSV files:

```bash
# In .env or Kubernetes ConfigMap
CARBON_CSV_PATH=/data/carbon_intensity.csv
TARIFF_CSV_PATH=/data/electricity_tariff.csv

# Optional: INR to USD conversion rate (default: 0.012)
TARIFF_INR_TO_USD=0.012
```

---

## 1. Carbon Intensity CSV

### Required Columns

| Column | Description | Example |
|---|---|---|
| `timestamp` | UTC datetime of the measurement | `2026-08-18T00:00:00+05:30` |
| `region` | Grid zone code | `IN-WE` |
| `carbon_gco2_kwh` | Carbon intensity in gCO₂/kWh | `312.5` |

### Accepted Region Codes

| Code | Description |
|---|---|
| `IN-WE` | India Western Grid (Gujarat, Maharashtra) |
| `IN-SO` | India Southern Grid (Telangana, Karnataka, AP, TN) |
| `IN-EA` | India Eastern Grid (West Bengal, Bihar, Odisha) |
| `IN-NO` | India Northern Grid (Himachal Pradesh, Punjab, Delhi) |
| `IN-NE` | India North-Eastern Grid |
| `DE` | Germany (Test Fixture) |

> Any custom region code is accepted — the scheduler will match jobs to regions by code.

### Accepted Header Name Variations

GreenShift automatically detects any of these column names:

| Field | Accepted Names |
|---|---|
| Timestamp | `timestamp`, `datetime`, `time`, `date`, `ts` |
| Region | `region`, `zone`, `area`, `grid_zone`, `location` |
| Carbon | `carbon_gco2_kwh`, `intensity_gco2_kwh`, `carbon_intensity`, `gco2_kwh`, `co2_gkwh`, `carbon`, `intensity` |

### Example Carbon CSV

```csv
timestamp,region,carbon_gco2_kwh
2026-08-18T00:00:00+00:00,IN-WE,312.5
2026-08-18T01:00:00+00:00,IN-WE,298.1
2026-08-18T02:00:00+00:00,IN-WE,276.3
2026-08-18T03:00:00+00:00,IN-WE,265.0
2026-08-18T04:00:00+00:00,IN-WE,258.7
2026-08-18T05:00:00+00:00,IN-WE,255.2
2026-08-18T06:00:00+00:00,IN-WE,270.0
2026-08-18T07:00:00+00:00,IN-WE,310.4
2026-08-18T08:00:00+00:00,IN-WE,385.1
2026-08-18T09:00:00+00:00,IN-WE,420.3
2026-08-18T10:00:00+00:00,IN-WE,398.7
2026-08-18T11:00:00+00:00,IN-WE,375.2
2026-08-18T12:00:00+00:00,IN-WE,350.8
2026-08-18T13:00:00+00:00,IN-WE,342.1
2026-08-18T14:00:00+00:00,IN-WE,335.6
2026-08-18T15:00:00+00:00,IN-WE,328.9
2026-08-18T16:00:00+00:00,IN-WE,352.4
2026-08-18T17:00:00+00:00,IN-WE,390.0
2026-08-18T18:00:00+00:00,IN-WE,415.5
2026-08-18T19:00:00+00:00,IN-WE,408.2
2026-08-18T20:00:00+00:00,IN-WE,388.0
2026-08-18T21:00:00+00:00,IN-WE,360.4
2026-08-18T22:00:00+00:00,IN-WE,338.1
2026-08-18T23:00:00+00:00,IN-WE,318.7
```

### Multi-Region Example

```csv
timestamp,region,carbon_gco2_kwh
2026-08-18T00:00:00+00:00,IN-WE,312.5
2026-08-18T00:00:00+00:00,IN-SO,198.4
2026-08-18T00:00:00+00:00,IN-EA,425.1
2026-08-18T00:00:00+00:00,IN-NO,355.0
```

---

## 2. Master Regional Tariff Dataset

GreenShift uses a single master regional tariff dataset containing tariff information across 10 canonical global regions (`data/master_tod_tariff_all_regions.csv`).

### Master Dataset Schema

| Column | Description | Example |
|---|---|---|
| `Time` | Hourly time block | `00:00-01:00` |
| `Time_of_day` | Time-of-Day block indicator | `Night`, `Normal`, `Solar`, `Peak`, `Off-Peak`, `Flat (No ToD)` |
| `Base_charge` | Base energy charge (in regional currency) | `7.65`, `4.00`, `0.18`, `0.35` |
| `Adder_charge` | ToD surcharge or rebate (in regional currency) | `0.0`, `-0.5`, `0.45`, `0.10` |
| `Effective_price`| Effective electricity rate (in regional currency) | `7.15`, `7.65`, `0.28`, `0.45` |
| `Region` | Regional grid identifier | `IN-TG`, `IN-GJ`, `IN-WB`, `IN-PB`, `US-CA`, `US-NY`, `US-TX`, `SE`, `AU-SA-Large`, `AU-SA-Small` |
| `Currency` | Currency denomination | `INR`, `USD`, `SEK`, `AUD` |
| `Tariff_type` | Tariff model | `ToD`, `Flat` |
| `Season` | Tariff applicability period | `All-Year`, `Summer`, `Winter` |

### Supported Regions

1. **Telangana (`IN-TG`)**: Time-of-Day tariff with Night rebate, Solar hours, and Evening Peak (INR).
2. **Gujarat (`IN-GJ`)**: Time-of-Day tariff with Morning/Evening Peak and Solar rebate (INR).
3. **West Bengal (`IN-WB`)**: Time-of-Day tariff with Off-Peak night rebate, Normal daytime, and Evening Peak (INR).
4. **Punjab (`IN-PB`)**: Time-of-Day tariff with Off-Peak and Peak rates (INR).
5. **California (`US-CA`)**: Seasonal Time-of-Day tariff with Summer/Winter Peak and Off-Peak (USD).
6. **New York (`US-NY`)**: Time-of-Day tariff with Peak and Off-Peak pricing (USD).
7. **Texas (`US-TX`)**: Dynamic/Time-of-Day tariff (USD).
8. **Sweden (`SE`)**: Nord Pool Time-of-Day pricing (SEK).
9. **South Australia Large (`AU-SA-Large`)**: Time-of-Day tariff for large commercial/industrial loads (AUD).
10. **South Australia Small (`AU-SA-Small`)**: Time-of-Day tariff for small/medium loads (AUD).

---

## 3. Solar / Renewable Resource CSV (Optional)

If your CSV includes renewable generation data, GreenShift can use it to
provide richer carbon intensity context. Supported additional columns:

| Column | Description |
|---|---|
| `solar_mw` | Solar generation in MW |
| `wind_mw` | Wind generation in MW |
| `solar_fraction` | Solar share of generation (0.0–1.0) |
| `wind_fraction` | Wind share of generation (0.0–1.0) |
| `renewable_fraction` | Total renewable share (0.0–1.0) |

Example combined CSV:
```csv
timestamp,region,carbon_gco2_kwh,solar_mw,wind_mw,renewable_fraction
2026-08-18T12:00:00+00:00,IN-WE,198.4,4500.0,1200.0,0.62
2026-08-18T13:00:00+00:00,IN-WE,185.2,4800.0,1100.0,0.65
```

---

## 4. Timezone Handling

- All timestamps are stored internally as UTC.
- If your CSV uses IST (UTC+05:30), include the timezone offset:
  `2026-08-18T08:30:00+05:30`
- If timestamps have no timezone info, they are treated as **UTC**.

---

## 5. Data Coverage Recommendation

For best scheduling results, provide at least **48 hours** of hourly data
ahead of job deadlines. The scheduler evaluates all hourly slots between
now and the job deadline, so more future coverage = better optimization.

---

## 6. Verifying CSV Integration

After placing your CSV files and setting env vars, check the data source status:

```bash
curl http://localhost:8000/api/v1/data-sources/status
```

Expected response when CSV is active:
```json
{
  "carbon": {
    "source": "csv",
    "csv_path": "/data/carbon_intensity.csv",
    "api_key_set": false
  },
  "tariff": {
    "source": "csv",
    "csv_path": "/data/electricity_tariff.csv",
    "api_key_set": false
  }
}
```

---

*Last updated: 2026-08-18*
