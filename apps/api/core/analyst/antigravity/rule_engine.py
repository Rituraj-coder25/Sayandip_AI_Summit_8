"""
RuleEngine — deterministic rule-chain evaluation for scenario generation.
This is the heart of the Antigravity system. No LLM calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ....models.intelligence import IntelligenceItem
from .graph_reasoner import TensionSignal

logger = logging.getLogger("goe.antigravity.rule_engine")


@dataclass
class RuleMatch:
    rule_id: str
    rule_name: str
    matched_entities: list[str]
    matched_signals: list[str]  # IntelligenceItem titles
    domain: str
    base_probability: float  # 0.0 – 1.0
    india_impact_score: int  # 0 – 100
    india_impact_label: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    scenario_label: str  # short branch name
    description: str  # 1–2 sentence scenario description
    recommended_response: str  # what India should do
    wildcard: bool = False  # True = low-prob/high-impact
    confidence_multiplier: float = 1.0  # adjusted by graph corroboration


@dataclass
class ScenarioCandidate:
    hypothesis: str
    branches: list[RuleMatch]
    india_net_assessment: str
    timeline_estimate: str
    generated_at: str


RULES = [
    # --- GEOPOLITICS ---
    {
        "id": "r_pak_border_escalation",
        "name": "Pakistan Border Escalation",
        "domain": "geopolitics",
        "trigger_entities": ["pakistan", "loc", "kashmir", "pla"],
        "trigger_keywords": ["troop", "border", "incursion", "ceasefire", "firing", "shelling"],
        "min_severity": 55,
        "base_probability": 0.35,
        "india_impact_score": 85,
        "india_impact_label": "CRITICAL",
        "scenario_label": "India-Pakistan border escalation",
        "description_template": "Signals indicate increased activity along the LoC involving {entity}. Historical pattern suggests short-duration flare-up with high media amplification.",
        "response_template": "Activate forward ISR assets along LoC sectors. Advance diplomatic back-channel with UAE and Saudi intermediaries.",
        "wildcard": False,
    },
    {
        "id": "r_china_ladakh_friction",
        "name": "China Ladakh Friction",
        "domain": "geopolitics",
        "trigger_entities": ["china", "pla", "lac", "ladakh", "depsang", "aksai chin"],
        "trigger_keywords": ["patrol", "standoff", "disengagement", "transgression", "positions"],
        "min_severity": 50,
        "base_probability": 0.30,
        "india_impact_score": 88,
        "india_impact_label": "CRITICAL",
        "scenario_label": "China LAC forward movement",
        "description_template": "Graph co-mention of {entity} with LAC friction keywords suggests patrol-level contact or infrastructure activity in eastern Ladakh sector.",
        "response_template": "Raise ITBP alert state in Depsang-Gogra sectors. Engage QUAD partners bilaterally on infrastructure observation data.",
        "wildcard": False,
    },
    # --- DEFENSE ---
    {
        "id": "r_iran_nuclear_anomaly",
        "name": "Iran Nuclear Test Anomaly",
        "domain": "defense",
        "trigger_entities": ["iran", "iaea", "natanz", "fordow", "arak"],
        "trigger_keywords": ["seismic", "earthquake", "nuclear", "enrichment", "test", "explosion", "underground"],
        "min_severity": 40,
        "base_probability": 0.08,
        "india_impact_score": 65,
        "india_impact_label": "HIGH",
        "scenario_label": "Iran covert nuclear test signature",
        "description_template": "Seismic anomaly co-occurring with IAEA/Iran signals in a historically low-tectonic zone is consistent with a contained underground detonation. Probability is low but impact on regional proliferation is extreme.",
        "response_template": "Request raw seismic data from CTBTO via MEA back-channel. Prepare diplomatic position on NPT compliance. Alert DAE and DRDO for technical assessment.",
        "wildcard": True,
    },
    {
        "id": "r_middle_east_escalation",
        "name": "Middle East Military Escalation",
        "domain": "defense",
        "trigger_entities": ["israel", "hamas", "hezbollah", "iran", "lebanon", "gaza", "west bank"],
        "trigger_keywords": ["strike", "missile", "rocket", "invasion", "ceasefire", "ground operation", "airstrike"],
        "min_severity": 60,
        "base_probability": 0.45,
        "india_impact_score": 60,
        "india_impact_label": "HIGH",
        "scenario_label": "Middle East active conflict escalation",
        "description_template": "Signals from {entity} indicate active military exchange. Indian diaspora in Gulf states (~9 million) and oil import routes face elevated operational risk.",
        "response_template": "Issue advisory for Indian nationals in Lebanon, Iraq, and Gaza border areas. Pre-position INS assets in the Arabian Sea. Coordinate with MEA on evacuation pre-planning.",
        "wildcard": False,
    },
    # --- TECHNOLOGY ---
    {
        "id": "r_us_china_tech_decoupling",
        "name": "US-China Tech Decoupling",
        "domain": "technology",
        "trigger_entities": ["united states", "china", "semiconductor", "taiwan", "tsmc", "huawei", "nvidia"],
        "trigger_keywords": ["export control", "chip ban", "sanction", "blacklist", "restriction", "decoupling"],
        "min_severity": 45,
        "base_probability": 0.55,
        "india_impact_score": 70,
        "india_impact_label": "HIGH",
        "scenario_label": "US-China semiconductor restriction tightening",
        "description_template": "Escalating export control signals involving {entity} suggest a new round of chip-supply restrictions. India's electronics manufacturing and defence procurement may face secondary effects.",
        "response_template": "Accelerate PLI scheme for domestic chip packaging. Engage ASML and Applied Materials for direct supply MoU outside China-linked channels.",
        "wildcard": False,
    },
    {
        "id": "r_cyber_critical_infra",
        "name": "Critical Infrastructure Cyberattack",
        "domain": "technology",
        "trigger_entities": ["india", "pakistan", "china", "apt", "ransomware"],
        "trigger_keywords": ["cyber attack", "ransomware", "grid", "power", "hospital", "water", "breach", "ioc", "c2"],
        "min_severity": 55,
        "base_probability": 0.25,
        "india_impact_score": 75,
        "india_impact_label": "HIGH",
        "scenario_label": "State-linked cyberattack on Indian infrastructure",
        "description_template": "IOC signals co-occurring with {entity} entity references suggest reconnaissance or active intrusion targeting Indian critical infrastructure sectors.",
        "response_template": "Issue CERT-In advisory for power grid SCADA operators. Cross-check IOC hashes with NIC and NTRO threat intelligence sharing platform.",
        "wildcard": False,
    },
    # --- ECONOMICS ---
    {
        "id": "r_oil_price_spike",
        "name": "Oil Supply Shock",
        "domain": "economics",
        "trigger_entities": ["opec", "saudi arabia", "iran", "russia", "uae", "brent", "wti"],
        "trigger_keywords": ["output cut", "supply disruption", "oil price", "barrel", "embargo", "strait", "hormuz"],
        "min_severity": 50,
        "base_probability": 0.40,
        "india_impact_score": 80,
        "india_impact_label": "CRITICAL",
        "scenario_label": "Crude oil supply disruption",
        "description_template": "Signal cluster around {entity} and oil supply keywords indicates elevated risk of Brent crude exceeding $95/bbl. India imports ~85% of crude, making this a tier-1 macroeconomic risk.",
        "response_template": "Activate Strategic Petroleum Reserve drawdown protocol. Fast-track rupee-denominated settlement with Russian Urals suppliers. RBI to review forex intervention thresholds.",
        "wildcard": False,
    },
    {
        "id": "r_russia_ukraine_energy",
        "name": "Russia-Ukraine Energy Cascade",
        "domain": "economics",
        "trigger_entities": ["russia", "ukraine", "nordstream", "gazprom", "europe"],
        "trigger_keywords": ["gas", "pipeline", "energy", "supply", "cut off", "winter", "lng"],
        "min_severity": 45,
        "base_probability": 0.35,
        "india_impact_score": 45,
        "india_impact_label": "MEDIUM",
        "scenario_label": "European energy squeeze — LNG rerouting",
        "description_template": "European energy stress signals around {entity} historically reroute LNG cargoes away from Asia, tightening global spot markets. India's LNG import price rises 15–25% in prior analogous episodes.",
        "response_template": "Lock in 6-month LNG forward contracts at current spot rates. Accelerate Kochi-Bangalore-Mangalore gas grid to reduce import dependency.",
        "wildcard": False,
    },
    {
        "id": "r_dollar_rupee_stress",
        "name": "Dollar-Rupee Stress",
        "domain": "economics",
        "trigger_entities": ["fed", "federal reserve", "dollar", "rbi", "rupee", "imf"],
        "trigger_keywords": ["rate hike", "rate cut", "devaluation", "capital flight", "forex", "current account", "fii outflow"],
        "min_severity": 45,
        "base_probability": 0.40,
        "india_impact_score": 72,
        "india_impact_label": "HIGH",
        "scenario_label": "Rupee depreciation pressure",
        "description_template": "Co-occurring signals from {entity} indicate elevated risk of capital outflows and rupee depreciation beyond ₹86/$. Historical analog: 2013 taper tantrum, 2022 Fed pivot.",
        "response_template": "RBI to maintain $580B+ forex reserves as active buffer. Pre-notify exporters of potential NDF market activity. Review oil import hedging positions.",
        "wildcard": False,
    },
    # --- CLIMATE ---
    {
        "id": "r_climate_disaster_supply",
        "name": "Climate Disaster Supply Chain",
        "domain": "climate",
        "trigger_entities": ["india", "bangladesh", "myanmar", "philippines", "vietnam", "thailand"],
        "trigger_keywords": ["flood", "cyclone", "earthquake", "drought", "crop failure", "food", "supply chain"],
        "min_severity": 50,
        "base_probability": 0.30,
        "india_impact_score": 55,
        "india_impact_label": "MEDIUM",
        "scenario_label": "Climate event — regional supply chain disruption",
        "description_template": "Significant climate event involving {entity} is generating supply-chain stress signals in agricultural commodities and manufacturing inputs relevant to Indian imports.",
        "response_template": "Review FCI buffer stock adequacy. Activate NDMA pre-positioning for affected neighboring countries. Monitor commodity futures for early panic signals.",
        "wildcard": False,
    },
    # --- WILDCARD ---
    {
        "id": "r_taiwan_strait_crisis",
        "name": "Taiwan Strait Military Crisis",
        "domain": "defense",
        "trigger_entities": ["taiwan", "pla", "china", "tsmc", "strait"],
        "trigger_keywords": ["blockade", "exercise", "strait", "invasion", "amphibious", "carrier"],
        "min_severity": 60,
        "base_probability": 0.06,
        "india_impact_score": 80,
        "india_impact_label": "CRITICAL",
        "scenario_label": "Taiwan Strait military action",
        "description_template": "Low-probability but structurally significant: PLA activity signals around {entity} indicate elevated risk of forced quarantine or live-fire exercise that closes the Taiwan Strait to shipping. 40% of India's container trade transits this corridor.",
        "response_template": "Activate India-US-Japan trilateral contingency communication channel. Pre-position strategic reserves of critical semiconductors and pharmaceuticals.",
        "wildcard": True,
    },
    {
        "id": "r_pak_nuclear_doctrinal_shift",
        "name": "Pakistan Nuclear Doctrinal Shift",
        "domain": "defense",
        "trigger_entities": ["pakistan", "nuclear", "army", "isi", "spd"],
        "trigger_keywords": ["nuclear", "doctrine", "first use", "tactical", "warhead", "delivery", "nasr"],
        "min_severity": 55,
        "base_probability": 0.05,
        "india_impact_score": 95,
        "india_impact_label": "CRITICAL",
        "scenario_label": "Pakistan tactical nuclear signal",
        "description_template": "Signals involving {entity} and nuclear doctrine/delivery keywords represent an extreme-low-probability but existential-risk scenario for Indian strategic planning.",
        "response_template": "Immediate escalation to NSA-level review. Brief PM and NSC. Activate DRDO/DAE technical assessment protocol. Issue no public statement.",
        "wildcard": True,
    },
]


class RuleEngine:
    def __init__(self):
        self._rules = RULES

    def evaluate(
        self, items: list[IntelligenceItem], tension_signals: list[TensionSignal]
    ) -> list[RuleMatch]:
        if not items and not tension_signals:
            return []

        fired: list[RuleMatch] = []

        for rule in self._rules:
            try:
                # 1. Collect matching items by keyword + severity
                matching_items: list[IntelligenceItem] = []
                for item in items:
                    combined = f"{item.title or ''} {item.summary or ''}".lower()
                    severity_ok = (item.severity or 0) >= rule["min_severity"]
                    keyword_ok = any(kw in combined for kw in rule["trigger_keywords"])
                    if severity_ok and keyword_ok:
                        matching_items.append(item)

                # 2. Collect matching entities from tension signals
                matching_tensions: list[TensionSignal] = []
                for t in tension_signals:
                    src_lower = t.source_entity.lower()
                    tgt_lower = t.target_entity.lower()
                    for te in rule["trigger_entities"]:
                        if te in src_lower or te in tgt_lower:
                            matching_tensions.append(t)
                            break

                # 3. Rule fires if: (items >= 1 AND entities >= 1) OR items >= 2
                fires = (
                    (len(matching_items) >= 1 and len(matching_tensions) >= 1)
                    or len(matching_items) >= 2
                )
                if not fires:
                    continue

                # 4. Compute adjusted probability
                corroboration = min(len(matching_items) / 3.0, 1.5)
                tension_boost = min(
                    sum(t.tension_score for t in matching_tensions) / 50.0, 0.2
                )
                adjusted_prob = min(
                    rule["base_probability"] * corroboration + tension_boost, 0.95
                )

                # 5. Determine primary entity for template substitution
                if matching_tensions:
                    primary_entity = matching_tensions[0].source_entity
                elif matching_items and matching_items[0].entities:
                    ents = matching_items[0].entities
                    if isinstance(ents, list) and ents:
                        first_ent = ents[0]
                        primary_entity = (
                            first_ent.get("text", "Unknown")
                            if isinstance(first_ent, dict)
                            else str(first_ent)
                        )
                    else:
                        primary_entity = "Unknown"
                else:
                    primary_entity = "Unknown"

                description = rule["description_template"].replace("{entity}", primary_entity)
                response = rule["response_template"].replace("{entity}", primary_entity)

                matched_entity_names = list(
                    {t.source_entity for t in matching_tensions}
                    | {t.target_entity for t in matching_tensions}
                )
                matched_signal_titles = [
                    (item.title or "")[:120] for item in matching_items[:5]
                ]

                match = RuleMatch(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    matched_entities=matched_entity_names,
                    matched_signals=matched_signal_titles,
                    domain=rule["domain"],
                    base_probability=adjusted_prob,
                    india_impact_score=rule["india_impact_score"],
                    india_impact_label=rule["india_impact_label"],
                    scenario_label=rule["scenario_label"],
                    description=description,
                    recommended_response=response,
                    wildcard=rule["wildcard"],
                    confidence_multiplier=corroboration,
                )
                fired.append(match)

            except Exception as exc:
                logger.warning("Rule '%s' evaluation failed: %s", rule.get("id", "?"), exc)
                continue

        fired.sort(key=lambda m: m.india_impact_score, reverse=True)
        return fired
