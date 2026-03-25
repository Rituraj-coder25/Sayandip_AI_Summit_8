from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("goe.classifier")

DOMAINS = ["geopolitics", "economics", "defense", "technology", "climate", "society"]
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "domain_classifier"

TRAINING_EXAMPLES = {
    "geopolitics": [
        "Prime Minister holds bilateral summit with foreign counterpart",
        "United Nations Security Council votes on sanctions resolution",
        "NATO deploys additional troops along eastern flank",
        "Diplomatic expulsion follows spy allegations",
        "Border standoff as troops hold forward positions",
        "Ceasefire collapses after delegation walkout",
        "Election results disputed amid fraud allegations",
        "President signs executive order on immigration",
        "Foreign minister summoned over ambassador remarks",
        "Intelligence warns of credible infrastructure threat",
        "SCO summit concludes with joint communique",
        "Territorial dispute escalates after patrol incident",
        "New coalition government sworn into office",
        "Peace talks resume after two-year hiatus",
        "Refugee numbers surpass five million at border",
        "Sanctions imposed following nuclear programme expansion",
    ],
    "economics": [
        "Central bank raises interest rates to combat inflation",
        "GDP growth beats analyst expectations at seven percent",
        "Stock market closes at record high on earnings",
        "Unemployment falls to decade low after jobs report",
        "Trade deficit widens as imports outpace exports",
        "IMF revises growth forecast upward for emerging markets",
        "Currency devaluation triggers capital flight fears",
        "FDI inflows reach record in manufacturing sector",
        "Semiconductor shortage hits automotive production",
        "Oil prices surge after OPEC output cut announcement",
        "Inflation reaches four decade high despite rate rises",
        "Bond yields spike on debt sustainability concerns",
        "G20 backs global minimum corporate tax agreement",
        "Supply chain disruption causes consumer goods shortage",
        "Fintech startup raises billion dollar Series C",
        "Sovereign wealth fund takes strategic stake in tech firm",
    ],
    "defense": [
        "Military conducts live fire exercise near disputed border",
        "Ballistic missile test detected by satellite intelligence",
        "Aircraft carrier strike group repositioned amid tensions",
        "Defence budget raised to four percent of GDP",
        "Fighter jets scrambled after airspace incursion",
        "Special forces operation kills militant leader",
        "Nuclear submarine commissioned into active service",
        "Drone strike hits military facility behind front lines",
        "Arms embargo imposed over human rights violations",
        "Hypersonic missile test achieves full design range",
        "Rapid reaction force activated following border incident",
        "Cyber command confirms state-sponsored attack on networks",
        "Artillery exchange erupts on ceasefire line overnight",
        "Covert intelligence network exposed by counterpart agency",
        "Defence ministry approves fifth generation aircraft purchase",
        "Insurgent group seizes strategic border town",
    ],
    "technology": [
        "Artificial intelligence model achieves human level on benchmark",
        "Chipmaker announces new fabrication plant in partner country",
        "Cybersecurity breach exposes government personnel records",
        "Space agency successfully places communication satellite",
        "Quantum computing milestone reached by research consortium",
        "Tech giant faces antitrust probe by competition regulator",
        "Fifth generation network rollout accelerates in cities",
        "Autonomous vehicle law passed for public road testing",
        "Biometric surveillance deployed across capital transport",
        "Open source AI model challenges commercial alternatives",
        "Data localisation law forces foreign data storage",
        "Nuclear fusion experiment achieves net energy gain",
        "Internet blackout imposed during political unrest",
        "Ransomware attack shuts down hospital networks",
        "Electric vehicle share reaches third of new car sales",
        "Central bank launches digital currency pilot programme",
    ],
    "climate": [
        "Monsoon season delivers record rainfall causing widespread flooding",
        "Heatwave shatters temperature records across the continent",
        "Glacier retreat accelerates threatening freshwater supply",
        "Tropical cyclone makes landfall at category five strength",
        "Wildfire season burns millions of hectares",
        "Drought emergency declared as reservoir levels critical",
        "Carbon emissions reach new annual record despite pledges",
        "Sea level rise threatens permanent coastal flooding",
        "Earthquake of magnitude seven strikes densely populated area",
        "Volcanic eruption closes international airspace",
        "Mass coral bleaching event kills reef ecosystem",
        "Polar vortex collapse sends extreme cold south",
        "Flash floods kill hundreds after cloud burst in valley",
        "Dust storms ground flights across affected region",
        "El Nino declared affecting global agricultural output",
        "Landslide buries village after weeks of heavy rain",
    ],
    "society": [
        "Mass protest demands political reform in capital city",
        "Supreme court overturns longstanding civil rights ruling",
        "Pandemic declared as new pathogen spreads internationally",
        "Famine conditions confirmed in conflict affected region",
        "Human rights report documents systematic minority abuse",
        "Education reforms trigger nationwide teacher strike",
        "Census reveals demographic shift toward urban areas",
        "Religious tensions rise after desecration incident",
        "Universal income pilot shows positive social outcomes",
        "Immigration policy change sparks divisive national debate",
        "Journalist arrested under national security legislation",
        "Social media platform banned after disinformation campaign",
        "Healthcare overwhelmed by sudden patient surge",
        "Youth unemployment crisis fuels political radicalisation",
        "Civil society groups face new registration restrictions",
        "Cultural heritage site damaged in targeted attack",
    ],
}

HIGH_SEVERITY = [
    "nuclear",
    "missile launch",
    "war declared",
    "invasion",
    "coup",
    "pandemic",
    "magnitude 7",
    "magnitude 8",
    "magnitude 9",
    "mass casualty",
    "chemical weapon",
    "assassination",
    "genocide",
    "emergency declared",
    "martial law",
]
MEDIUM_SEVERITY = [
    "conflict",
    "explosion",
    "airstrike",
    "protest",
    "arrested",
    "sanctions",
    "floods",
    "earthquake",
    "drought",
    "recession",
    "cyber attack",
    "data breach",
    "crash",
    "collapse",
    "resignation",
    "hostage",
]
DOMAIN_BASE = {"defense": 8, "geopolitics": 5, "economics": 3, "climate": 5, "technology": 2, "society": 1}

_KEYWORD_FALLBACK = {
    "defense": ["missile", "border", "airstrike", "military", "troops", "navy", "army", "drone"],
    "economics": ["inflation", "bank", "gdp", "market", "tariff", "trade", "currency", "oil"],
    "technology": ["ai", "cyber", "chip", "satellite", "quantum", "network", "digital"],
    "climate": ["earthquake", "cyclone", "flood", "wildfire", "drought", "heatwave", "storm"],
    "society": ["protest", "rights", "pandemic", "strike", "education", "journalist", "minority"],
    "geopolitics": ["summit", "sanctions", "diplomat", "election", "ceasefire", "refugee", "coalition"],
}

_model = None


@dataclass
class ClassificationResult:
    domain: str
    severity: int


class SignalClassifier:
    def __init__(self, llm):
        self._llm = llm
        self._model = _get_model()

    async def classify_domain(self, text: str) -> str:
        if self._model:
            loop = asyncio.get_event_loop()
            preds = await loop.run_in_executor(None, self._model.predict, [text[:512]])
            pred = preds[0]
            if isinstance(pred, str) and pred in DOMAINS:
                return pred
            try:
                return DOMAINS[int(pred)]
            except Exception:
                pass
        return await self._claude_classify(text)

    async def score_severity(self, text: str, domain: str, entities: list) -> int:
        lowered = (text or "").lower()
        score = 18
        for keyword in HIGH_SEVERITY:
            if keyword in lowered:
                score = max(score, 75)
                break
        for keyword in MEDIUM_SEVERITY:
            if keyword in lowered:
                score = max(score, 42)
                break
        score += DOMAIN_BASE.get(domain, 0)
        score += min(15, len(entities) * 3)
        return min(100, score)

    async def _claude_classify(self, text: str) -> str:
        if self._llm is not None:
            result = await self._llm.complete(
                (
                    "Classify into exactly one: geopolitics, economics, defense, technology, climate, society.\n"
                    "Reply with the single word only.\n\n"
                    f"Text: {text[:300]}"
                ),
                max_tokens=5,
                prefer_fast=True,
            )
            value = (result or "").strip().lower()
            if value in DOMAINS:
                return value
        return _heuristic_domain(text)


class KeywordDomainClassifier:
    """Backward-compatible sync wrapper used by existing unit tests."""

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir

    def classify(self, text: str) -> ClassificationResult:
        domain = _heuristic_domain(text)
        lowered = (text or "").lower()
        score = 18
        if any(keyword in lowered for keyword in HIGH_SEVERITY):
            score = max(score, 75)
        if any(keyword in lowered for keyword in MEDIUM_SEVERITY):
            score = max(score, 42)
        score += DOMAIN_BASE.get(domain, 0)
        score += min(15, len(re.findall(r"\b[A-Z][a-z]+\b", text or "")) * 3)
        return ClassificationResult(domain=domain, severity=min(100, score))


def _get_model():
    global _model
    if _model is None and MODEL_DIR.exists():
        try:
            from setfit import SetFitModel

            _model = SetFitModel.from_pretrained(str(MODEL_DIR))
            logger.info("SetFit domain classifier loaded")
        except Exception as exc:
            logger.warning("Could not load SetFit model: %s", exc)
    return _model


def train_classifier():
    from datasets import Dataset
    from setfit import SetFitModel, SetFitTrainer

    texts, labels = [], []
    for index, (domain, examples) in enumerate(TRAINING_EXAMPLES.items()):
        for example in examples:
            texts.append(example)
            labels.append(index)

    dataset = Dataset.from_dict({"text": texts, "label": labels})
    model = SetFitModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2", labels=DOMAINS)
    trainer = SetFitTrainer(
        model=model,
        train_dataset=dataset,
        eval_dataset=dataset,
        metric="accuracy",
        batch_size=16,
        num_iterations=20,
        num_epochs=1,
    )
    trainer.train()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(MODEL_DIR))
    logger.info("Classifier saved to %s", MODEL_DIR)
    return model


def _heuristic_domain(text: str) -> str:
    lowered = (text or "").lower()
    scores = {domain: 0 for domain in DOMAINS}
    for domain, keywords in _KEYWORD_FALLBACK.items():
        scores[domain] = sum(_keyword_hits(lowered, keyword) for keyword in keywords)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "geopolitics"


def _keyword_hits(text: str, keyword: str) -> int:
    if " " in keyword:
        return text.count(keyword)
    return len(re.findall(rf"\b{re.escape(keyword)}\b", text))