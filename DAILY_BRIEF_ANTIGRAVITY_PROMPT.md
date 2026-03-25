# GOE Daily Brief — Antigravity (Option 2) Implementation Prompt

> **Purpose**: This is a complete, self-contained implementation specification for replacing the
> LLM-dependent `DailyBriefGenerator` and `ScenarioEngine` with a fully deterministic, graph-driven
> Antigravity intelligence system. No external LLM API key is required. All reasoning is performed
> through the knowledge graph, rule engine, and statistical scoring that already exists in this
> codebase.
>
> **Hand this file to your coding agent / IDE assistant as the complete task description.**

---

## 0. Read These Files First (Do Not Skip)

Before writing a single line of code, open and fully internalize every file listed below.
Understanding them is mandatory — the new system integrates deeply with each one.

```
apps/api/core/analyst/daily_brief.py          ← Current LLM-based brief generator (replace this)
apps/api/core/analyst/scenario_engine.py      ← Current LLM-based scenario engine (replace this)
apps/api/core/ontology/graph_engine.py        ← OntologyGraphEngine (Neo4j) — your data source
apps/api/core/ontology/relation_extractor.py  ← RelationExtractor — entity co-occurrence
apps/api/core/intelligence/engine.py          ← GOEIntelligenceEngine — signal pipeline
apps/api/core/intelligence/embedder.py        ← all-MiniLM-L6-v2 sentence embedder
apps/api/core/intelligence/brief_generator.py ← LLMClient + BriefGenerator (keep LLMClient as-is)
apps/api/core/intelligence/classifier.py      ← SignalClassifier with DOMAINS list
apps/api/core/intelligence/india_scorer.py    ← IndiaRelevanceScorer (INDIA_RE, NEIGHBORS, etc.)
apps/api/core/intelligence/vector_store.py    ← GOEVectorStore (ChromaDB)
apps/api/models/daily_brief.py                ← DailyBrief SQLAlchemy model
apps/api/models/intelligence.py               ← IntelligenceItem model
apps/api/models/signal.py                     ← RawSignal model
apps/api/routers/analyst.py                   ← /analyst/daily-brief and /analyst/scenario routes
apps/api/ingestion/base_connector.py          ← BaseConnector interface
apps/api/config.py                            ← Settings (all env vars)
docker-compose.yml                            ← Services: Redis, Postgres, Neo4j
```

---

## 1. Problem Statement

### What is broken today

`DailyBriefGenerator` (in `apps/api/core/analyst/daily_brief.py`) calls
`self.llm.complete(prompt, ...)` to produce the brief text. When `self.llm._mode == "none"` — which
is the case when neither Ollama is running locally nor an Anthropic API key is configured — the
method returns `None` and the brief is written as `"Brief generation failed."`. The same problem
applies to `ScenarioEngine.generate_scenario_tree()` which also delegates entirely to
`self._llm.complete(...)`.

### What we want instead

A graph-traversal + statistical reasoning pipeline that:

1. Reads recent `IntelligenceItem` rows from Postgres (already normalised and scored by the existing
   engine pipeline).
2. Queries the Neo4j `OntologyGraphEngine` for entity neighborhood data, co-occurrence weights, and
   tension escalation signals.
3. Queries the ChromaDB `GOEVectorStore` for semantically similar historical signals.
4. Applies deterministic rule chains (defined as Python dataclasses) to produce scenario branches
   with confidence scores — no LLM call required.
5. Assembles a fully structured `DailyBrief` object and scenario tree using only the data derived
   from steps 1–4.
6. Falls back gracefully to the LLM path if `llm._mode != "none"` — the LLM is an enhancement, not
   a requirement.

The brief must be **as informative as the LLM version** on a data-rich day and **clearly indicate
data sparsity** on a quiet day, rather than hallucinating content.

---

## 2. New File Structure

Create the following new files. Do not delete any existing files.

```
apps/api/core/analyst/
├── daily_brief.py               ← REPLACE (keep signature, add antigravity path)
├── scenario_engine.py           ← REPLACE (keep signature, add antigravity path)
├── goe_analyst.py               ← KEEP AS-IS
└── antigravity/
    ├── __init__.py
    ├── graph_reasoner.py        ← NEW: graph traversal + tension scoring
    ├── signal_aggregator.py     ← NEW: groups IntelligenceItems by domain/severity
    ├── rule_engine.py           ← NEW: deterministic scenario rule chains
    ├── brief_assembler.py       ← NEW: formats the structured brief dict/text
    └── scenario_builder.py      ← NEW: builds scenario trees from rule engine output
```

---

## 3. Component Specifications

### 3.1 `antigravity/graph_reasoner.py`

**Class**: `GraphReasoner`

**Constructor**:
```python
def __init__(self, graph_engine: OntologyGraphEngine, vector_store: GOEVectorStore):
    self.graph = graph_engine
    self.vector = vector_store
```

**Method**: `async def analyse_entity_tensions(self, entity_names: list[str]) -> list[TensionSignal]`

For each entity name in `entity_names`:
- Call `self.graph.get_entity_neighborhood(entity_name, depth=2)` to get nodes + links.
- Iterate over returned links. For each link, compute a `tension_score` as:
  ```
  tension_score = link["strength"] * link["mentions"] * TENSION_MULTIPLIER.get(link["type"], 1.0)
  ```
  Where `TENSION_MULTIPLIER` is a module-level dict:
  ```python
  TENSION_MULTIPLIER = {
      "ATTACKED": 3.5,
      "SANCTIONED": 2.8,
      "THREATENED": 2.5,
      "DISPUTED": 2.2,
      "RELATED_TO": 1.0,
      "TRADES_WITH": 0.8,
      "ENGAGED": 0.9,
      "NEAR": 1.1,
  }
  ```
- Return a list of `TensionSignal` dataclass instances sorted by `tension_score` descending.

**Dataclass**:
```python
@dataclass
class TensionSignal:
    source_entity: str
    target_entity: str
    relation_type: str
    tension_score: float
    mention_count: int
    strength: float
    domain_hint: str = ""   # populated by classify_tension_domain()
```

**Method**: `def classify_tension_domain(self, tension: TensionSignal) -> str`

Use keyword matching on `source_entity + " " + target_entity + " " + tension.relation_type`
against the `DOMAIN_KEYWORDS` dict:
```python
DOMAIN_KEYWORDS = {
    "defense":     ["attack", "military", "missile", "troops", "army", "navy", "nuclear", "bomb",
                    "weapon", "drone", "airforce", "irgc", "nato", "pla", "isi"],
    "economics":   ["trade", "sanction", "tariff", "oil", "gas", "export", "import", "bank",
                    "inflation", "gdp", "currency", "market", "investment", "debt"],
    "geopolitics": ["border", "summit", "election", "president", "minister", "diplomacy",
                    "un", "treaty", "ceasefire", "coup", "protest", "referendum"],
    "technology":  ["cyber", "hack", "satellite", "ai", "chip", "semiconductor", "space",
                    "infrastructure", "grid", "telecom", "5g"],
    "climate":     ["earthquake", "flood", "fire", "hurricane", "drought", "tsunami",
                    "seismic", "climate", "storm", "volcano"],
}
```
Return the first matching domain, or `"geopolitics"` as default.

**Method**: `async def get_historical_analogs(self, query_text: str, domain: str, n: int = 3) -> list[dict]`

Call `self.vector.query(query_text, n_results=n, where={"domain": domain})` and return the results
as-is (list of dicts with `document`, `metadata`, `distance` keys — whatever ChromaDB returns).

**Method**: `async def compute_india_exposure(self, tension_signals: list[TensionSignal]) -> float`

Import `IndiaRelevanceScorer` from `...intelligence.india_scorer`.
For each tension signal, score `f"{tension.source_entity} {tension.target_entity}"` using
`scorer.score(text, entities=[])`. Return the mean of all scores, clamped to `[0, 100]`.
Return `0.0` if the list is empty.

---

### 3.2 `antigravity/signal_aggregator.py`

**Class**: `SignalAggregator`

**Constructor**:
```python
def __init__(self, db_session_factory):
    self._db_factory = db_session_factory
```

**Method**: `async def fetch_recent(self, hours: int = 24, limit: int = 100) -> list[IntelligenceItem]`

Open an async session from `self._db_factory`. Execute:
```python
cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
query = (
    select(IntelligenceItem)
    .where(IntelligenceItem.published_at >= cutoff)
    .order_by(desc(IntelligenceItem.severity))
    .limit(limit)
)
```
Return all results.

**Method**: `def group_by_domain(self, items: list[IntelligenceItem]) -> dict[str, list[IntelligenceItem]]`

Return a dict keyed by domain string, value is list of items for that domain, sorted by `severity`
descending within each group. Domains come from `classifier.DOMAINS`:
`["geopolitics", "economics", "defense", "technology", "climate", "society"]`.
Items whose `domain` field is missing or not in `DOMAINS` go into `"geopolitics"`.

**Method**: `def compute_domain_risk(self, items: list[IntelligenceItem]) -> dict[str, int]`

For each domain, compute:
```
domain_risk = min(100, int(
    mean(item.severity for item in domain_items) * 0.6
  + mean(item.india_score for item in domain_items) * 0.4
))
```
Where `mean` is `statistics.mean`. Return `0` for domains with no items.
Return a dict: `{"geopolitics": 72, "economics": 45, ...}`.

**Method**: `def top_entities(self, items: list[IntelligenceItem], n: int = 10) -> list[str]`

Flatten all `item.entities` fields (each is a list of dicts with `"text"` key — from the NER
pipeline stored in the IntelligenceItem JSON column). Count unique entity texts by frequency.
Return the top `n` most-mentioned entity strings. Skip entities shorter than 3 characters.

**Method**: `def top_items_per_domain(self, grouped: dict, n: int = 3) -> dict[str, list[IntelligenceItem]]`

Return the top `n` highest-severity items per domain from the already-grouped dict.

---

### 3.3 `antigravity/rule_engine.py`

This is the heart of the Antigravity system. It applies structured inference rules to produce
scenario candidates without any LLM.

**Dataclasses**:
```python
@dataclass
class RuleMatch:
    rule_id: str
    rule_name: str
    matched_entities: list[str]
    matched_signals: list[str]          # IntelligenceItem titles
    domain: str
    base_probability: float             # 0.0 – 1.0
    india_impact_score: int             # 0 – 100
    india_impact_label: str             # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    scenario_label: str                 # short branch name
    description: str                    # 1–2 sentence scenario description
    recommended_response: str           # what India should do
    wildcard: bool = False              # True = low-prob/high-impact
    confidence_multiplier: float = 1.0  # adjusted by graph corroboration

@dataclass
class ScenarioCandidate:
    hypothesis: str
    branches: list[RuleMatch]
    india_net_assessment: str
    timeline_estimate: str
    generated_at: str
```

**Class**: `RuleEngine`

**Constructor**:
```python
def __init__(self):
    self._rules = self._build_rules()
```

**Method**: `def _build_rules(self) -> list[dict]`

Return a list of rule definition dicts. Each rule has these keys:

| Key | Type | Meaning |
|-----|------|---------|
| `id` | str | unique snake_case identifier |
| `name` | str | human-readable name |
| `domain` | str | one of DOMAINS |
| `trigger_entities` | list[str] | entity substrings that must appear (case-insensitive) |
| `trigger_keywords` | list[str] | keywords that must appear in combined signal text |
| `min_severity` | int | minimum severity of at least one matching signal |
| `base_probability` | float | prior probability if rule fires |
| `india_impact_score` | int | base India impact |
| `india_impact_label` | str | "CRITICAL" / "HIGH" / "MEDIUM" / "LOW" |
| `scenario_label` | str | short branch name (≤ 8 words) |
| `description_template` | str | 1-2 sentence template with `{entity}` placeholders |
| `response_template` | str | recommended India response template |
| `wildcard` | bool | marks low-prob/high-impact scenarios |

**Mandatory rules to implement** (implement ALL of these):

```python
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
    # Wildcard scenarios
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
```

**Method**: `def evaluate(self, items: list[IntelligenceItem], tension_signals: list[TensionSignal]) -> list[RuleMatch]`

For each rule in `self._rules`:

1. Collect `matching_items`: items whose `title + " " + (item.summary or "")` contains ANY of
   `trigger_keywords` (case-insensitive) AND whose `severity >= min_severity`.

2. Collect `matching_entities`: from `tension_signals`, find signals where
   `source_entity.lower()` or `target_entity.lower()` contains ANY of `trigger_entities`.

3. A rule **fires** if: `len(matching_items) >= 1` AND `len(matching_entities) >= 1`.
   OR if `len(matching_items) >= 2` (entity match not required if two strong signals appear).

4. If the rule fires, compute adjusted probability:
   ```python
   corroboration = min(len(matching_items) / 3.0, 1.5)   # cap at 1.5x boost
   tension_boost = min(sum(t.tension_score for t in matching_entities) / 50.0, 0.2)
   adjusted_prob = min(rule["base_probability"] * corroboration + tension_boost, 0.95)
   ```

5. Build a `RuleMatch` by filling the template: replace `{entity}` in `description_template`
   and `response_template` with the primary matched entity name (first `matching_entities[0].source_entity`
   if available, else first entity from first matching item's `.entities` list).

6. Return all fired `RuleMatch` instances sorted by `india_impact_score` descending.

---

### 3.4 `antigravity/scenario_builder.py`

**Class**: `ScenarioBuilder`

**Constructor**:
```python
def __init__(self, graph_reasoner: GraphReasoner, rule_engine: RuleEngine):
    self.reasoner = graph_reasoner
    self.rules = rule_engine
```

**Method**: `async def build_scenario_tree(self, hypothesis: str, items: list[IntelligenceItem], tension_signals: list[TensionSignal]) -> dict`

This is the main scenario generation path, called in place of the LLM.

Steps:

1. Filter `items` and `tension_signals` to only those relevant to `hypothesis` using keyword
   overlap: split `hypothesis` into tokens ≥ 4 chars, keep signals/tensions where at least 1 token
   appears in the combined text.

2. Run `rule_matches = self.rules.evaluate(filtered_items, filtered_tensions)`.

3. If `len(rule_matches) == 0`, create a single fallback branch:
   ```python
   fallback = RuleMatch(
       rule_id="r_fallback",
       rule_name="Insufficient Signal",
       matched_entities=[],
       matched_signals=[],
       domain="geopolitics",
       base_probability=0.5,
       india_impact_score=30,
       india_impact_label="LOW",
       scenario_label="Situation remains ambiguous",
       description="Insufficient corroborating signals in the knowledge graph to generate a high-confidence scenario tree for this hypothesis. Monitor for 24–48 hours.",
       recommended_response="Maintain current monitoring posture. No immediate action recommended.",
       wildcard=False,
       confidence_multiplier=0.3,
   )
   rule_matches = [fallback]
   ```

4. Separate into `main_branches` (non-wildcard, sorted by `india_impact_score` desc, take top 3)
   and `wildcard_branches` (wildcard=True, take up to 2).

5. Normalize probabilities across `main_branches` so they sum to 100 (convert to int percentages).
   Wildcard branches get their own probability displayed separately (not normalized).

6. Compute `india_net_assessment` using this deterministic formula:
   ```python
   top_domain = main_branches[0].domain if main_branches else "geopolitics"
   top_score = main_branches[0].india_impact_score if main_branches else 30
   label = main_branches[0].india_impact_label if main_branches else "LOW"
   assessment = (
       f"The most likely scenario involves {top_domain}-domain risk with {label} India impact "
       f"(score: {top_score}/100). "
       f"{len(rule_matches)} rule-based branches identified from {len(filtered_items)} active signals "
       f"and {len(tension_signals)} graph tension edges."
   )
   ```

7. Estimate `timeline_estimate` based on highest `min_severity` matched rule — crude heuristic:
   - `severity >= 70` → `"24–72 hours"`
   - `severity >= 50` → `"3–7 days"`
   - default → `"1–3 weeks"`

8. Return a dict matching the existing `ScenarioEngine` output schema exactly:
   ```python
   {
       "hypothesis": hypothesis,
       "timeline": timeline_estimate,
       "confidence": int(main_branches[0].base_probability * 100) if main_branches else 30,
       "branches": [
           {
               "id": f"branch_{chr(ord('a') + i)}",
               "label": f"Branch {chr(ord('A') + i)} — {m.scenario_label}",
               "probability": normalized_prob,
               "india_impact_score": m.india_impact_score,
               "india_impact": m.india_impact_label,
               "india_effects": [m.description],
               "timeline": timeline_estimate,
               "key_actors": m.matched_entities[:5],
               "recommended_response": m.recommended_response,
               "historical_analog": await self._get_analog(m),
               "sub_branches": [],
               "wildcard": False,
               "antigravity": True,
               "rule_id": m.rule_id,
               "corroborating_signals": m.matched_signals[:3],
           }
           for i, m in enumerate(main_branches)
       ] + [
           {
               "id": f"wildcard_{i}",
               "label": f"Wildcard — {w.scenario_label}",
               "probability": int(w.base_probability * 100),
               "india_impact_score": w.india_impact_score,
               "india_impact": w.india_impact_label,
               "india_effects": [w.description],
               "timeline": "Indeterminate",
               "key_actors": w.matched_entities[:3],
               "recommended_response": w.recommended_response,
               "historical_analog": await self._get_analog(w),
               "sub_branches": [],
               "wildcard": True,
               "antigravity": True,
               "rule_id": w.rule_id,
           }
           for i, w in enumerate(wildcard_branches)
       ],
       "india_net_assessment": india_net_assessment,
       "generated_at": datetime.now(timezone.utc).isoformat(),
       "id": str(uuid.uuid4()),
       "source": "antigravity",
       "signal_count": len(filtered_items),
       "tension_edge_count": len(tension_signals),
   }
   ```

**Method**: `async def _get_analog(self, match: RuleMatch) -> str`

Query `self.reasoner.vector.query(" ".join(match.matched_signals[:2] or [match.scenario_label]), n_results=1)`.
If a result is returned, return `f"Similar to: {result[0]['document'][:80]}"`.
Otherwise return `f"Rule: {match.rule_name} (no historical analog found)"`.

---

### 3.5 `antigravity/brief_assembler.py`

**Class**: `BriefAssembler`

This class converts the raw data (grouped items, tension signals, domain risks, scenario branches)
into the final `DailyBrief` text and sections dict.

**Constructor**:
```python
def __init__(self):
    pass
```

**Method**: `def assemble(self, context: BriefContext) -> tuple[str, dict]`

Returns `(brief_text: str, sections: dict)`.

`BriefContext` is a dataclass defined in this file:
```python
@dataclass
class BriefContext:
    date_str: str
    india_risk: dict                              # {"score": int, "label": str, "color": str}
    market: dict                                  # {"USDINR": str, ...} from Redis
    domain_groups: dict[str, list[IntelligenceItem]]
    domain_risks: dict[str, int]
    tension_signals: list[TensionSignal]
    top_entities: list[str]
    scenario_branches: list[dict]                 # from ScenarioBuilder output
    total_signal_count: int
    india_exposure: float
```

**Brief text format** — assemble as a Python f-string following this EXACT template. Do NOT use
any LLM. All values come from `context`:

```
--- GOE DAILY STRATEGIC INTELLIGENCE BRIEF (ANTIGRAVITY) ---
Date: {full_date}
Classification: FOR AUTHORISED PERSONNEL ONLY
India Risk Score: {india_risk_score}/100 — {india_risk_label}
Signal Sources: {total_signal_count} active signals | Graph Edges: {tension_edge_count}
Engine: Antigravity Rule Engine v1.0 (no LLM)

EXECUTIVE SUMMARY
{executive_summary}

INDIA STRATEGIC UPDATE
- Risk trend: {risk_trend}
- Priority action item: {priority_action}
- Key opportunity: {key_opportunity}

[GEOPOLITICS]
{geopolitics_section}

[ECONOMICS]
{economics_section}

[DEFENSE]
{defense_section}

[TECHNOLOGY]
{technology_section}

[CLIMATE]
{climate_section}

THREAT MATRIX
Domain       | Risk Level | India Impact | Trend
Geopolitics  | {geo_risk_label}  | {geo_india}/100 | {geo_trend}
Economics    | {eco_risk_label}  | {eco_india}/100 | {eco_trend}
Defense      | {def_risk_label}  | {def_india}/100 | {def_trend}
Technology   | {tec_risk_label}  | {tec_india}/100 | {tec_trend}
Climate      | {cli_risk_label}  | {cli_india}/100 | {cli_trend}

SCENARIO BRANCHES (from knowledge graph)
{scenario_text}

STRATEGIC PRIORITIES FOR INDIA (Next 7 days)
{priorities}

ENTITIES TO WATCH
{entities_to_watch}

--- END OF BRIEF ---
Generated: {generated_at} | GOE Antigravity v1.0
```

**How to populate each section**:

- `executive_summary`: Take the top 3 items by severity across all domains. Construct:
  `"Key developments: [title1]. [title2]. [title3]. India exposure score: {india_exposure:.0f}/100."`

- `risk_trend`: Compare `india_risk["score"]` against the constant `RISK_BASELINE = 50`.
  `score > 65` → `"ESCALATING — {top_domain} domain driving risk elevation"`.
  `score > 45` → `"STABLE — monitor {top_domain} for directional change"`.
  Default → `"DE-ESCALATING — signal volume below baseline"`.

- `priority_action`: Use the `recommended_response` from the highest `india_impact_score` branch.
  If no branches, use `"Maintain standard monitoring posture across all domains."`.

- `key_opportunity`: If India exposure > 60, use `"Diplomatic positioning window open around {top_entity} developments."`.
  If top domain is `"economics"`, use `"Potential energy import arbitrage as {top_entity} supply signals shift."`.
  Default: `"No high-confidence opportunity identified in current signal window."`.

- Domain sections: For each of the 5 domains, take the top 2 items from `domain_groups[domain]`
  (or fewer if not available). Format each item as:
  ```
  [{source_name} | Sev:{severity} | India:{india_score}] {title}
    → {summary[:200]}
  ```
  If no items for a domain, write `"No significant signals in this domain in the past 24 hours."`.

- `risk_label` helper: `score >= 70` → `"HIGH"`, `score >= 40` → `"MED"`, default → `"LOW"`.

- Trend per domain: Compare current `domain_risks[domain]` against `50`.
  `> 60` → `"UP"`, `40–60` → `"FLAT"`, `< 40` → `"DOWN"`.

- `scenario_text`: For each branch in `scenario_branches[:3]`:
  ```
  Branch {letter} ({prob}%) — {label}
    India impact: {impact_label} ({impact_score}/100)
    {description}
    Response: {recommended_response}
  ```

- `priorities`: Take `recommended_response` from the top 3 unique-domain branches. Number them 1–3.
  If fewer than 3 branches, fill remaining slots with generic monitoring directives:
  `"Monitor {domain} domain signals for directional change over the next 72 hours."`

- `entities_to_watch`: Format the top 5 entities from `top_entities` as:
  `"- {entity_name}: Appearing in {count} signals across {domain} domain. Monitor for escalation."`
  (You will need to pass entity counts into `BriefContext` — add `entity_counts: dict[str, int]`
  to the dataclass.)

**Method**: `def _build_sections_dict(self, context: BriefContext) -> dict`

Return a structured JSON-serializable dict for the `DailyBrief.sections` column:
```python
{
    "engine": "antigravity_v1",
    "domain_risks": context.domain_risks,
    "top_entities": context.top_entities[:10],
    "tension_edge_count": len(context.tension_signals),
    "scenario_count": len(context.scenario_branches),
    "signal_count": context.total_signal_count,
    "india_exposure": context.india_exposure,
}
```

---

### 3.6 Replace `apps/api/core/analyst/daily_brief.py`

Replace the entire file. Keep the `DailyBriefGenerator` class name and the `generate(db)` method
signature intact so the router does not need to change.

**New constructor**:
```python
class DailyBriefGenerator:
    def __init__(self, redis_client, llm, neo4j_driver=None, vector_store=None, db_factory=None):
        self.redis = redis_client
        self.llm = llm
        self._neo4j = neo4j_driver
        self._vector = vector_store
        self._db_factory = db_factory
```

**New `generate` method** — pseudocode, implement in full:

```python
async def generate(self, db: AsyncSession) -> DailyBrief:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check for existing brief
    existing = await db.execute(select(DailyBrief).where(DailyBrief.date == today))
    brief = existing.scalar_one_or_none()

    # --- ANTIGRAVITY PATH (no LLM required) ---
    if self._neo4j is not None and self._vector is not None:
        content, sections, india_score = await self._generate_antigravity(db, today)
        model_used = "antigravity_v1"

    # --- LLM FALLBACK (existing behaviour, unchanged) ---
    elif self.llm and self.llm._mode != "none":
        content, sections, india_score = await self._generate_llm(db, today)
        model_used = self.llm._mode

    # --- LAST RESORT ---
    else:
        content = "Brief generation unavailable: no knowledge graph and no LLM configured."
        sections = {}
        india_score = 50
        model_used = "none"

    # Persist (same logic as before)
    if brief is None:
        brief = DailyBrief(
            id=str(uuid.uuid4()),
            date=today,
            content=content,
            sections=sections,
            india_score=india_score,
            model_used=model_used,
        )
        db.add(brief)
    else:
        brief.content = content
        brief.sections = sections
        brief.india_score = india_score
        brief.model_used = model_used

    await db.flush()

    # Redis pub/sub (identical to original)
    await self.redis.setex(
        "goe:latest_daily_brief",
        86400,
        json.dumps({"id": brief.id, "date": today, "content": content}),
    )
    await self.redis.publish(
        "goe:daily_brief_ready",
        json.dumps({"type": "DAILY_BRIEF_READY", "date": today, "brief_id": brief.id}),
    )
    return brief
```

**Private `_generate_antigravity` method**:

```python
async def _generate_antigravity(self, db, today: str) -> tuple[str, dict, int]:
    from .antigravity.graph_reasoner import GraphReasoner
    from .antigravity.signal_aggregator import SignalAggregator
    from .antigravity.rule_engine import RuleEngine
    from .antigravity.scenario_builder import ScenarioBuilder
    from .antigravity.brief_assembler import BriefAssembler, BriefContext

    # 1. Fetch and group recent signals
    aggregator = SignalAggregator(self._db_factory)
    items = await aggregator.fetch_recent(hours=24, limit=100)
    grouped = aggregator.group_by_domain(items)
    domain_risks = aggregator.compute_domain_risk(items)
    top_entities_list = aggregator.top_entities(items, n=10)

    # 2. Graph reasoning
    reasoner = GraphReasoner(
        graph_engine=OntologyGraphEngine(self._neo4j),
        vector_store=self._vector,
    )
    tension_signals = await reasoner.analyse_entity_tensions(top_entities_list[:8])
    india_exposure = await reasoner.compute_india_exposure(tension_signals)

    # 3. Rule evaluation
    rule_engine = RuleEngine()
    rule_matches = rule_engine.evaluate(items, tension_signals)

    # 4. Scenario building
    builder = ScenarioBuilder(reasoner, rule_engine)
    # Build a scenario tree for the top hypothesis (derived from top tension signal)
    hypothesis = (
        f"{tension_signals[0].source_entity} — {tension_signals[0].relation_type} — "
        f"{tension_signals[0].target_entity}"
        if tension_signals else "Global risk assessment"
    )
    tree = await builder.build_scenario_tree(hypothesis, items, tension_signals)
    scenario_branches = tree.get("branches", [])

    # 5. Redis context (same as original)
    risk_raw = await self.redis.get("goe:india_risk_score_full")
    risk = json.loads(risk_raw) if risk_raw else {"score": int(india_exposure), "color": "amber", "label": "MODERATE"}
    market_raw = await self.redis.get("goe:market_snapshot")
    market = json.loads(market_raw) if market_raw else {}

    # 6. Assemble brief
    entity_counts = {}  # count mentions across items
    for item in items:
        for ent in (item.entities or []):
            name = ent.get("text", "")
            if name:
                entity_counts[name] = entity_counts.get(name, 0) + 1

    ctx = BriefContext(
        date_str=today,
        india_risk=risk,
        market=market,
        domain_groups=grouped,
        domain_risks=domain_risks,
        tension_signals=tension_signals,
        top_entities=top_entities_list,
        entity_counts=entity_counts,
        scenario_branches=scenario_branches,
        total_signal_count=len(items),
        india_exposure=india_exposure,
    )
    assembler = BriefAssembler()
    content, sections = assembler.assemble(ctx)

    return content, sections, risk["score"]
```

**Private `_generate_llm` method**:

Extract the existing `generate()` logic verbatim into this private method. Return
`(content, {}, india_score)`.

---

### 3.7 Replace `apps/api/core/analyst/scenario_engine.py`

Keep the `ScenarioEngine` class name and `generate_scenario_tree(hypothesis, depth)` signature.

**New constructor**:
```python
class ScenarioEngine:
    def __init__(self, llm, redis_client, vector_store, neo4j_driver=None, db_factory=None):
        self._llm = llm
        self._redis = redis_client
        self._vector = vector_store
        self._neo4j = neo4j_driver
        self._db_factory = db_factory
```

**New `generate_scenario_tree` method**:
```python
async def generate_scenario_tree(self, hypothesis: str, depth: int = 3) -> dict:
    # Try Antigravity path first
    if self._neo4j is not None and self._db_factory is not None:
        return await self._antigravity_tree(hypothesis)

    # Fall back to LLM path (existing code)
    if self._llm and self._llm._mode != "none":
        return await self._llm_tree(hypothesis)

    return self._fallback_tree(hypothesis)
```

**`_antigravity_tree` method**:
```python
async def _antigravity_tree(self, hypothesis: str) -> dict:
    from .antigravity.graph_reasoner import GraphReasoner
    from .antigravity.signal_aggregator import SignalAggregator
    from .antigravity.rule_engine import RuleEngine
    from .antigravity.scenario_builder import ScenarioBuilder
    from ..ontology.graph_engine import OntologyGraphEngine

    aggregator = SignalAggregator(self._db_factory)
    items = await aggregator.fetch_recent(hours=72, limit=150)

    reasoner = GraphReasoner(OntologyGraphEngine(self._neo4j), self._vector)
    entities = [word for word in hypothesis.lower().split() if len(word) > 3]
    tensions = await reasoner.analyse_entity_tensions(entities[:6])

    rule_engine = RuleEngine()
    builder = ScenarioBuilder(reasoner, rule_engine)
    return await builder.build_scenario_tree(hypothesis, items, tensions)
```

Move the existing LLM logic from the original `generate_scenario_tree` into `_llm_tree`. Keep
`_fallback_tree` exactly as-is.

---

### 3.8 Wire the New Dependencies — `apps/api/main.py`

Find where `DailyBriefGenerator` and `ScenarioEngine` are instantiated (likely in the
`lifespan` context manager or `startup` event). Update the instantiation calls to pass the
`neo4j_driver`, `vector_store`, and `db_factory` that are already attached to `app.state`.

For `DailyBriefGenerator`, the router in `routers/analyst.py` instantiates it inline:
```python
generator = DailyBriefGenerator(request.app.state.redis, request.app.state.engine._llm)
```

Update this line to:
```python
generator = DailyBriefGenerator(
    redis_client=request.app.state.redis,
    llm=request.app.state.engine._llm,
    neo4j_driver=request.app.state.neo4j,   # already on app.state
    vector_store=request.app.state.vector,   # already on app.state
    db_factory=request.app.state.db_factory, # already on app.state (or AsyncSessionLocal)
)
```

For `ScenarioEngine`, it is instantiated inline in the `/analyst/scenario` route:
```python
engine = ScenarioEngine(
    llm=request.app.state.engine._llm,
    redis_client=request.app.state.redis,
    vector_store=request.app.state.vector,
    neo4j_driver=request.app.state.neo4j,
    db_factory=request.app.state.db_factory,
)
```

Check `main.py` to confirm the attribute names for `neo4j` and `db_factory` on `app.state`. Use
whatever names are already set there — do not rename them.

---

## 4. Database Schema Check

The `DailyBrief` model already has a `sections` JSON column. No schema migration is needed for the
Antigravity output — all new fields go into `sections`. The `model_used` column will contain
`"antigravity_v1"` so you can distinguish brief sources in the UI.

No new tables or migrations are required.

---

## 5. Redis Keys Used

All new Redis keys follow existing project naming conventions:

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `goe:latest_daily_brief` | string (JSON) | 86400s | Same as before |
| `goe:daily_brief_ready` | pub/sub channel | — | Same as before |
| `goe:antigravity:domain_risks:{date}` | string (JSON) | 3600s | Domain risk cache |
| `goe:antigravity:tensions:{date}` | string (JSON) | 1800s | Top tension signals |

Cache the `domain_risks` and `tensions` results in Redis to avoid re-querying Neo4j and Postgres
on every call. Write them at the end of `_generate_antigravity`. On subsequent calls within TTL,
deserialize and skip the computation.

---

## 6. Error Handling Rules

Follow the same pattern as the rest of this codebase:

- Never swallow exceptions in core logic methods. Let them bubble.
- `DailyBriefGenerator.generate()` wraps `_generate_antigravity` in a try/except that logs the
  error and falls through to the LLM path:
  ```python
  try:
      content, sections, india_score = await self._generate_antigravity(db, today)
      model_used = "antigravity_v1"
  except Exception as exc:
      logger.error("Antigravity brief generation failed, falling back to LLM: %s", exc)
      # fall through to LLM path
  ```
- If `get_entity_neighborhood` raises (Neo4j unavailable), `GraphReasoner.analyse_entity_tensions`
  should catch only `Exception`, log a warning, and return `[]` so the pipeline continues.
- `RuleEngine.evaluate` must not raise under any circumstance — wrap the per-rule loop in a
  try/except that logs and skips the failing rule.

---

## 7. Dependencies

The Antigravity system uses only packages already present in `requirements.txt`:

- `sqlalchemy[asyncio]` — already used
- `neo4j` — already used (for `OntologyGraphEngine`)
- `chromadb` — already used (for `GOEVectorStore`)
- `sentence-transformers` — already used (for `embedder.py`)
- `redis` — already used

No new pip installs required.

---

## 8. Implementation Order

Work in this exact order to avoid import errors:

1. Create `apps/api/core/analyst/antigravity/__init__.py` (empty).
2. Implement `antigravity/graph_reasoner.py` — imports `OntologyGraphEngine` and `GOEVectorStore`.
3. Implement `antigravity/signal_aggregator.py` — imports `IntelligenceItem`, `DOMAINS`.
4. Implement `antigravity/rule_engine.py` — imports `IntelligenceItem`, `TensionSignal`.
5. Implement `antigravity/scenario_builder.py` — imports `GraphReasoner`, `RuleEngine`.
6. Implement `antigravity/brief_assembler.py` — imports `TensionSignal`, `IntelligenceItem`.
7. Replace `apps/api/core/analyst/daily_brief.py`.
8. Replace `apps/api/core/analyst/scenario_engine.py`.
9. Update `apps/api/routers/analyst.py` (two constructor call sites).
10. Verify compilation: `python -m py_compile apps/api/core/analyst/antigravity/*.py`
11. Verify compilation: `python -m py_compile apps/api/core/analyst/daily_brief.py apps/api/core/analyst/scenario_engine.py`
12. Run: `python -m pytest apps/api/tests/ -x -q` (existing tests must still pass).

---

## 9. Verification Checklist

After implementation, verify each item:

- [ ] `DailyBriefGenerator` instantiates without error when `neo4j_driver=None` (fallback mode works)
- [ ] `DailyBriefGenerator` instantiates without error when `llm._mode == "none"` (antigravity-only mode works)
- [ ] `ScenarioEngine.generate_scenario_tree("Iran earthquake nuclear test signal")` returns a dict
      with `"source": "antigravity"` and at least one branch with `rule_id == "r_iran_nuclear_anomaly"`
      when Iran-related signals are in the DB
- [ ] `POST /analyst/daily-brief` returns HTTP 200 with `content` field containing
      `"--- GOE DAILY STRATEGIC INTELLIGENCE BRIEF (ANTIGRAVITY) ---"` when Neo4j is available
- [ ] `POST /analyst/scenario` with `{"hypothesis": "Pakistan border escalation"}` returns HTTP 200
      with a tree that has `"source": "antigravity"` and branches
- [ ] The `model_used` column in the `daily_briefs` table contains `"antigravity_v1"` for new briefs
- [ ] `brief.sections["engine"]` equals `"antigravity_v1"` for new briefs
- [ ] Existing tests in `apps/api/tests/test_api.py` and `test_engine.py` pass without modification
- [ ] `RuleEngine.evaluate([], [])` returns `[]` without raising
- [ ] `GraphReasoner.analyse_entity_tensions([])` returns `[]` without raising
- [ ] `BriefAssembler.assemble(ctx)` returns a non-empty string and dict even when all signal lists
      are empty
- [ ] All 12 rules in `RULES` fire correctly on synthetic test data (write a quick unit test)
- [ ] The `r_iran_nuclear_anomaly` wildcard rule is present in scenario branches when its trigger
      keywords appear in signal data

---

## 10. Example: Iran Nuclear Anomaly Flow

This is the exact scenario from the project brief. Trace the full execution:

1. USGS connector posts a seismic event in western Iran (Semnan province — historically low
   tectonic zone) with `domain="climate"`, `severity=55`.
2. IAEA connector posts an update on Iran enrichment (`domain="defense"`, `severity=60`).
3. `GOEIntelligenceEngine.process_signal()` runs NER on both. Entities extracted: `["Iran", "IAEA",
   "Semnan", "nuclear", "enrichment"]`.
4. `OntologyGraphEngine.upsert_from_signal()` creates/updates nodes for `Iran`, `IAEA`, and a
   `RELATED_TO` edge with incrementing `mention_count` and `strength_score`.
5. At brief generation time:
   - `SignalAggregator.fetch_recent()` returns both items.
   - `GraphReasoner.analyse_entity_tensions(["Iran", "IAEA", "Semnan"])` traverses the graph,
     returns a `TensionSignal` with `source_entity="Iran"`, `target_entity="IAEA"`,
     `relation_type="RELATED_TO"`, `tension_score` computed from strength × mentions.
   - `RuleEngine.evaluate(items, tensions)` tests all rules. Rule `r_iran_nuclear_anomaly` fires:
     - `trigger_entities`: `"iran"` matches entity `"Iran"` ✓
     - `trigger_keywords`: `"seismic"` and `"nuclear"` both appear in combined signal text ✓
     - `min_severity = 40` ≤ `55` ✓
   - `ScenarioBuilder.build_scenario_tree()` includes this as a wildcard branch.
   - `BriefAssembler.assemble()` places it in the SCENARIO BRANCHES section with
     `"Wildcard — Iran covert nuclear test signature"` label.
6. The output brief contains the scenario even though zero LLM calls were made.

---

## 11. Do Not Do These Things

- **Do not** modify `BaseConnector`, `GOEIntelligenceEngine`, `LLMClient`, `IndiaRelevanceScorer`,
  `OntologyGraphEngine`, or any connector file.
- **Do not** add any new database tables or Alembic migrations.
- **Do not** change the `/analyst/daily-brief` or `/analyst/scenario` route paths or their
  response schemas — the frontend depends on these exactly.
- **Do not** call `self.llm.complete()` anywhere inside the Antigravity module. The entire point
  is that it works without the LLM.
- **Do not** use `requests` (synchronous). All Neo4j and ChromaDB calls are already async-safe
  through the existing drivers.
- **Do not** hardcode dates, entity names, or probabilities outside the `RULES` list and
  `TENSION_MULTIPLIER` dict. Everything else must be derived from live data.
- **Do not** change `DailyBrief` SQLAlchemy model columns.
- **Do not** remove the `_generate_llm` fallback path. The system must still work when
  Ollama/Anthropic is available.

---

*End of specification. All technical details needed to implement this feature are contained above.*
*No additional context is required beyond the source files listed in Section 0.*
