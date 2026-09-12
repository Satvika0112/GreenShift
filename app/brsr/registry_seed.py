"""
GreenShift — BRSR Metric/Question Registry Seed Data.

This is a real, representative subset of the official SEBI BRSR question
bank (Section A general disclosures beyond the static company profile,
Section B management/process, all 9 Section C principles, and all 9 BRSR
Core attributes) — not the complete ~250-question form. The registry
architecture (app.shared.models.BrsrMetricDefinitionORM/BrsrMetricValueORM)
is what makes this extensible: adding a real BRSR question, or an entire
future framework version, is a new row here, never a schema or UI change.
See docs/greenshift_brsr_implementation_status_*.md for what is and isn't
covered.

`greenshift_derivable=True` is set ONLY for the metrics GreenShift's
existing operational data can genuinely support: Scope 2 electricity
emissions, total energy consumption, and the energy/emission intensity
figures derived from those two, from GreenShift-executed workloads (8
metric rows total — a CORE_* and P6_* pair for each of the 4 underlying
calculations; see app/brsr/calculations.py for the exact methodology and
its stated limitations). Every other metric — including Scope 1, Scope 3,
water, waste, renewable-energy share, and all social/governance fields —
is COMPANY_PROVIDED by necessity — nothing here is invented to make the
registry look more automated than it is.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

FRAMEWORK_VERSION = "BRSR-2023"

_EFFECTIVE_FROM = datetime(2023, 4, 1, tzinfo=timezone.utc)


def _m(
    code: str,
    name: str,
    section: str,
    data_type: str = "NUMERIC",
    principle: "int | None" = None,
    brsr_core_attribute: "str | None" = None,
    unit: "str | None" = None,
    required: bool = False,
    calculation_method: "str | None" = None,
    description: "str | None" = None,
    greenshift_derivable: bool = False,
) -> Dict[str, Any]:
    return {
        "metric_code": code,
        "metric_name": name,
        "principle": principle,
        "section": section,
        "brsr_core_attribute": brsr_core_attribute,
        "unit": unit,
        "data_type": data_type,
        "required": required,
        "calculation_method": calculation_method,
        "framework_version": FRAMEWORK_VERSION,
        "effective_from": _EFFECTIVE_FROM,
        "effective_to": None,
        "description": description,
        "greenshift_derivable": greenshift_derivable,
    }


BRSR_METRIC_DEFINITIONS: List[Dict[str, Any]] = [
    # ── SECTION A — General Disclosures (beyond the static company profile) ──
    _m("SEC_A_CSR_APPLICABLE", "CSR applicability (Companies Act, 2013)", "SECTION_A",
       data_type="BOOLEAN", required=True,
       description="Whether Section 135 of the Companies Act, 2013 applies to the company."),
    _m("SEC_A_CSR_AMOUNT_SPENT", "CSR amount spent", "SECTION_A",
       unit="currency", description="Total CSR amount spent in the reporting period."),
    _m("SEC_A_TURNOVER_RATE_EMPLOYEES", "Employee turnover rate", "SECTION_A",
       data_type="PERCENTAGE", unit="%"),
    _m("SEC_A_TURNOVER_RATE_WORKERS", "Worker turnover rate", "SECTION_A",
       data_type="PERCENTAGE", unit="%"),
    _m("SEC_A_DIFFERENTLY_ABLED_PCT", "Differently-abled employees/workers", "SECTION_A",
       data_type="PERCENTAGE", unit="%",
       description="Percentage of the workforce that is differently-abled — a standard BRSR Section A workforce-composition disclosure."),

    # ── SECTION B — Management & Process (governance) ──
    _m("SEC_B_BOARD_COMPOSITION", "Board composition", "SECTION_B",
       data_type="TEXT", required=True,
       description="Board size, composition (executive/non-executive), and independent-director representation — distinct from ESG-specific responsibility below."),
    _m("SEC_B_BOARD_ESG_RESPONSIBILITY", "Board-level ESG responsibility", "SECTION_B",
       data_type="TEXT", required=True,
       description="Whether the Board has a director/committee responsible for ESG oversight, and who."),
    _m("SEC_B_SUSTAINABILITY_COMMITTEE", "Sustainability committee", "SECTION_B", data_type="TEXT"),
    _m("SEC_B_ETHICS_POLICY", "Anti-corruption/ethics policy in place", "SECTION_B", data_type="BOOLEAN"),
    _m("SEC_B_WHISTLEBLOWER_MECHANISM", "Whistleblower mechanism in place", "SECTION_B", data_type="BOOLEAN"),
    _m("SEC_B_RELATED_PARTY_TRANSACTIONS", "Related-party transaction disclosures", "SECTION_B", data_type="TEXT"),
    _m("SEC_B_FINES_NON_COMPLIANCE", "Fines/penalties for non-compliance", "SECTION_B", unit="currency"),
    _m("SEC_B_ESG_RISKS", "Material ESG risks identified", "SECTION_B", data_type="TEXT"),
    _m("SEC_B_ESG_TARGETS", "ESG targets and goals", "SECTION_B", data_type="TEXT"),

    # ── PRINCIPLE 1 — Ethical, transparent, accountable ──
    _m("P1_ANTI_CORRUPTION_POLICY", "Anti-corruption policy communicated to value chain", "SECTION_C",
       principle=1, data_type="BOOLEAN"),
    _m("P1_ANTI_CORRUPTION_COMPLAINTS", "Corruption/bribery complaints received", "SECTION_C",
       principle=1, unit="count"),

    # ── PRINCIPLE 2 — Sustainable & safe goods/services ──
    _m("P2_RD_SPEND_PCT", "R&D spend on sustainability", "SECTION_C",
       principle=2, data_type="PERCENTAGE", unit="%"),
    _m("P2_SUSTAINABLE_SOURCING_PCT", "Inputs sourced sustainably", "SECTION_C",
       principle=2, data_type="PERCENTAGE", unit="%"),

    # ── PRINCIPLE 3 — Employee well-being ──
    _m("P3_HEALTH_INSURANCE_COVERAGE_PCT", "Employees covered by health insurance", "SECTION_C",
       principle=3, data_type="PERCENTAGE", unit="%"),
    _m("P3_SAFETY_INCIDENTS_COUNT", "Safety incidents (LTIFR-relevant)", "SECTION_C",
       principle=3, unit="count"),
    _m("P3_TRAINING_HOURS_AVG", "Average training hours per employee", "SECTION_C",
       principle=3, unit="hours/employee"),
    _m("P3_SOCIAL_SECURITY_COVERAGE_PCT", "Employees/workers covered by social security benefits", "SECTION_C",
       principle=3, data_type="PERCENTAGE", unit="%",
       description="Coverage under statutory social security benefits (e.g. PF, ESI, gratuity)."),

    # ── PRINCIPLE 4 — Stakeholder responsiveness ──
    _m("P4_GRIEVANCES_RECEIVED", "Stakeholder grievances received", "SECTION_C",
       principle=4, unit="count"),
    _m("P4_GRIEVANCES_RESOLVED_PCT", "Grievances resolved", "SECTION_C",
       principle=4, data_type="PERCENTAGE", unit="%"),

    # ── PRINCIPLE 5 — Human rights ──
    _m("P5_HUMAN_RIGHTS_TRAINING_PCT", "Employees trained on human rights", "SECTION_C",
       principle=5, data_type="PERCENTAGE", unit="%"),
    _m("P5_HUMAN_RIGHTS_COMPLAINTS", "Human rights complaints received", "SECTION_C",
       principle=5, unit="count",
       description="Complaints filed relating to human rights (e.g. forced/child labour, discrimination) — distinct from the training-coverage metric above."),
    _m("P5_MINIMUM_WAGE_COMPLIANCE_PCT", "Employees/workers paid at least minimum wage", "SECTION_C",
       principle=5, data_type="PERCENTAGE", unit="%"),
    _m("P5_GENDER_PAY_PARITY_PCT", "Gender pay parity (median remuneration ratio)", "SECTION_C",
       principle=5, data_type="PERCENTAGE", unit="%",
       description="Median remuneration of women as a percentage of median remuneration of men."),

    # ── PRINCIPLE 6 — Environment ──
    _m("P6_SCOPE1_EMISSIONS", "Scope 1 GHG emissions", "SECTION_C",
       principle=6, unit="tCO2e",
       description="Direct emissions from owned/controlled sources. GreenShift has no fuel-combustion/fleet data — company-provided only."),
    _m("P6_SCOPE2_EMISSIONS", "Scope 2 GHG emissions", "SECTION_C",
       principle=6, unit="tCO2e", greenshift_derivable=True,
       calculation_method=(
           "Sum of ScheduleDecisionORM.carbon_emission (kg CO2) for the tenant's "
           "GreenShift-executed workloads within the reporting period, converted "
           "to tCO2e. This is electricity-related emissions from GreenShift-managed "
           "workload execution only — it is NOT the company's complete Scope 2 "
           "footprint unless all of the company's relevant electricity consumption "
           "runs through GreenShift-scheduled workloads."
       )),
    _m("P6_SCOPE3_EMISSIONS", "Scope 3 GHG emissions (value chain)", "SECTION_C",
       principle=6, unit="tCO2e",
       description="Indirect value-chain emissions (upstream/downstream). GreenShift has no visibility into supplier or customer emissions — company-provided only."),
    _m("P6_TOTAL_ENERGY_CONSUMPTION", "Total energy consumption", "SECTION_C",
       principle=6, unit="kWh", greenshift_derivable=True,
       calculation_method="Sum of JobORM.energy_kwh for the tenant's GreenShift-executed workloads within the reporting period."),
    _m("P6_ENERGY_INTENSITY", "Energy intensity", "SECTION_C",
       principle=6, unit="kWh/job", greenshift_derivable=True,
       calculation_method="Total GreenShift-executed energy_kwh in the reporting period ÷ GreenShift job count in the same period — an operational efficiency proxy, not a per-unit-of-revenue intensity."),
    _m("P6_EMISSION_INTENSITY", "Emission intensity", "SECTION_C",
       principle=6, unit="kgCO2/kWh", greenshift_derivable=True,
       calculation_method="Total GreenShift-executed carbon_emission (kg) ÷ total energy_kwh in the reporting period — the effective average grid carbon intensity encountered by GreenShift-scheduled workloads."),
    _m("P6_RENEWABLE_ENERGY_PCT", "Renewable energy share", "SECTION_C",
       principle=6, data_type="PERCENTAGE", unit="%",
       description="GreenShift tracks grid average carbon intensity, not a renewable/non-renewable source split — company-provided only."),
    _m("P6_WATER_CONSUMPTION", "Water consumption", "SECTION_C", principle=6, unit="kilolitres"),
    _m("P6_WASTE_GENERATED", "Waste generated", "SECTION_C", principle=6, unit="tonnes"),
    _m("P6_AIR_EMISSIONS", "Significant air emissions", "SECTION_C", principle=6, unit="tonnes",
       description="Significant air emissions (e.g. NOx, SOx, particulate matter) from operations — company-provided only, GreenShift has no emissions-monitoring data."),
    _m("P6_BIODIVERSITY_SENSITIVE_AREAS", "Operations in/near ecologically sensitive areas", "SECTION_C",
       principle=6, data_type="TEXT",
       description="Whether any operations are located in or near ecologically sensitive/protected areas, and any biodiversity impact assessment undertaken."),

    # ── PRINCIPLE 7 — Public policy advocacy ──
    _m("P7_TRADE_ASSOCIATIONS_COUNT", "Trade/industry associations engaged", "SECTION_C",
       principle=7, unit="count"),

    # ── PRINCIPLE 8 — Inclusive growth ──
    _m("P8_CSR_PROJECTS_COUNT", "CSR projects undertaken", "SECTION_C", principle=8, unit="count"),
    _m("P8_VULNERABLE_GROUPS_BENEFITED", "Vulnerable/marginalised groups benefited", "SECTION_C",
       principle=8, unit="count"),

    # ── PRINCIPLE 9 — Consumer value & engagement ──
    _m("P9_CONSUMER_COMPLAINTS_COUNT", "Consumer complaints received", "SECTION_C", principle=9, unit="count"),
    _m("P9_DATA_PRIVACY_BREACHES", "Data privacy breaches", "SECTION_C", principle=9, unit="count"),

    # ── BRSR CORE — 9 national priority indicators ──
    _m("CORE_GHG_SCOPE1", "BRSR Core: Scope 1 emissions", "CORE",
       principle=6, brsr_core_attribute="GHG_FOOTPRINT", unit="tCO2e"),
    _m("CORE_GHG_SCOPE2", "BRSR Core: Scope 2 emissions", "CORE",
       principle=6, brsr_core_attribute="GHG_FOOTPRINT", unit="tCO2e", greenshift_derivable=True,
       calculation_method="Same methodology as P6_SCOPE2_EMISSIONS — see that definition for the full caveat."),
    _m("CORE_WATER_CONSUMPTION", "BRSR Core: Water consumption", "CORE",
       principle=6, brsr_core_attribute="WATER_FOOTPRINT", unit="kilolitres"),
    _m("CORE_ENERGY_CONSUMPTION", "BRSR Core: Energy consumption", "CORE",
       principle=6, brsr_core_attribute="ENERGY_FOOTPRINT", unit="kWh", greenshift_derivable=True,
       calculation_method="Same methodology as P6_TOTAL_ENERGY_CONSUMPTION."),
    _m("CORE_ENERGY_INTENSITY", "BRSR Core: Energy intensity", "CORE",
       principle=6, brsr_core_attribute="ENERGY_FOOTPRINT", unit="kWh/job", greenshift_derivable=True,
       calculation_method="Same methodology as P6_ENERGY_INTENSITY."),
    _m("CORE_EMISSION_INTENSITY", "BRSR Core: Emission intensity", "CORE",
       principle=6, brsr_core_attribute="GHG_FOOTPRINT", unit="kgCO2/kWh", greenshift_derivable=True,
       calculation_method="Same methodology as P6_EMISSION_INTENSITY."),
    _m("CORE_RENEWABLE_ENERGY_PCT", "BRSR Core: Renewable energy share", "CORE",
       principle=6, brsr_core_attribute="ENERGY_FOOTPRINT", data_type="PERCENTAGE", unit="%"),
    _m("CORE_WASTE_RECYCLED_PCT", "BRSR Core: Waste recycled/reused", "CORE",
       principle=6, brsr_core_attribute="EMISSIONS_WASTE_CIRCULARITY", data_type="PERCENTAGE", unit="%"),
    _m("CORE_EMPLOYEE_WELLBEING_SPEND_PCT", "BRSR Core: Employee well-being spend", "CORE",
       principle=3, brsr_core_attribute="EMPLOYEE_WELLBEING", data_type="PERCENTAGE", unit="%"),
    _m("CORE_WOMEN_EMPLOYEES_PCT", "BRSR Core: Women employees", "CORE",
       principle=5, brsr_core_attribute="GENDER_DIVERSITY", data_type="PERCENTAGE", unit="%"),
    _m("CORE_WOMEN_BOARD_PCT", "BRSR Core: Women on Board", "CORE",
       principle=5, brsr_core_attribute="GENDER_DIVERSITY", data_type="PERCENTAGE", unit="%"),
    _m("CORE_INCLUSIVE_DEV_SPEND_PCT", "BRSR Core: Inclusive development spend", "CORE",
       principle=8, brsr_core_attribute="INCLUSIVE_DEVELOPMENT", data_type="PERCENTAGE", unit="%"),
    _m("CORE_VALUE_CHAIN_MSME_PCT", "BRSR Core: Value chain — MSME/local sourcing", "CORE",
       principle=9, brsr_core_attribute="VALUE_CHAIN_FAIRNESS", data_type="PERCENTAGE", unit="%"),
    _m("CORE_TOP10_SUPPLIER_CONCENTRATION_PCT", "BRSR Core: Openness — top-10 supplier concentration", "CORE",
       principle=9, brsr_core_attribute="OPENNESS_OF_BUSINESS", data_type="PERCENTAGE", unit="%"),
]


GREENSHIFT_DERIVABLE_METRIC_CODES = {m["metric_code"] for m in BRSR_METRIC_DEFINITIONS if m["greenshift_derivable"]}
