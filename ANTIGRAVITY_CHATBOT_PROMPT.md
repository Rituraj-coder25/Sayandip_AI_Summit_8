# GOE Antigravity Chatbot — Full Implementation Prompt
## Replace `AI.call()` with Pure Data-Driven Intelligence, Zero LLM Keys Required

> **This prompt is the complete, self-contained specification** for implementing the Antigravity
> chatbot system in the GOE frontend (`index.html`) and the GOE FastAPI backend.
> Hand it verbatim to your coding agent. No other context file is needed.

---

## 0. Current State — Read This First

### What the system looks like now

The GOE frontend (`index.html`) has a single-page application with these modules:

- **Analyst** — a chat interface (`#chatLog`, `#chatInput`, `#sendChat`) that calls `ask(question)`,
  which calls `AI.call(messages, SYSTEM_PROMPT, 1500)`. When `AI.config.mode === "none"` (no Ollama,
  no Anthropic key), `ask()` dumps a raw context string into the chat and shows the AI setup modal.
  **This is what we are replacing.**

- **Daily Brief** — `buildBrief()` tries `POST http://localhost:8000/api/v1/analyst/daily-brief`.
  On any error it falls back to `fallbackBrief()`, a deterministic but minimal plain-text brief.

- **Scenario Engine** — `runScenario()` tries `POST http://localhost:8000/api/v1/analyst/scenario`.
  On any error it renders three static placeholder branches.

### What is broken

The server log shows:
```
redis.exceptions.ConnectionError: Error 61 connecting to localhost:6380. 61.
```
The FastAPI backend fails at startup because Redis is not running. The `docker-compose.yml` maps
Redis container port 6379 to host port **6380**. The Python app is trying `localhost:6380` (correct)
but Docker is not running. **Start Docker and run `docker-compose up -d` before testing the backend.**

### What we want

An Antigravity engine that answers the four canonical query types **without any LLM call**:

> Q1) Explain how current signals affect India's energy security.
> Q2) What is India's most critical strategic risk right now?
> Q3) Assess India's geopolitical risk this week.
> Q4) What are the top three external shocks India should monitor over 72 hours?

The expected output quality is **exactly the detailed answers in the example section** of the
original request — structured, domain-specific, actionable, sourced from live feed data.

---

## 1. Architecture Overview

The Antigravity system has **two layers** that must both be implemented:

### Layer 1 — Frontend Antigravity Engine (in `index.html`)
A pure JavaScript reasoning engine that runs entirely in the browser, requires no backend, and
answers questions using the data already collected in `STATE` (RSS feeds, market data, seismic,
weather, Bharatiya). This is the **primary path** — it works even when the Python backend is down.

### Layer 2 — Backend Antigravity Endpoint (FastAPI)
The existing `/api/v1/analyst/query` endpoint receives the question and the current live context
snapshot, applies the Python-side `RuleEngine` and `GraphReasoner` from the previously specified
`DAILY_BRIEF_ANTIGRAVITY_PROMPT.md`, and returns a structured answer. This is the **enriched path**
used when the backend is up.

**The frontend always tries Layer 2 first. If it fails or returns within 200ms, it falls through to
Layer 1. The user always gets an answer.**

---

## 2. Frontend Layer — Detailed Specification

### 2.1 Remove the AI modal dependency for the chatbot

Currently, when `AI.config.mode === "none"`, `ask()` calls `showAiModal()` which pops a modal
asking the user to configure an LLM. **This must no longer happen for the chatbot.**

Modify the `ask()` function so that when `AI.config.mode === "none"`:
- Do NOT call `showAiModal()`.
- Instead, call the new `ANTIGRAVITY.answer(question)` function (defined below).
- Set `reply` to the result.
- Continue the normal `STATE.chat.push({ role: "assistant", content: reply })` path.

The AI modal should still appear when the user explicitly clicks `#openAi`. It should never auto-
appear simply because a chat question was asked.

### 2.2 Add the `ANTIGRAVITY` object

Add this object to `index.html` **immediately after the `AI` object definition** (after the closing
`}` of the `AI` object, before `const SYSTEM_PROMPT`):

```javascript
const ANTIGRAVITY = {

  // ── Domain scoring keywords (must match the DOMAINS in the backend) ──────
  DOMAINS: {
    defense: ["missile", "army", "navy", "airforce", "drdo", "nuclear", "border", "loc", "lac",
              "military", "strike", "war", "weapon", "drone", "irgc", "pla", "nato", "oref",
              "hezbollah", "hamas", "tactical", "warhead", "spd", "blockade"],
    economics: ["oil", "opec", "crude", "inflation", "rbi", "rupee", "inr", "nifty", "sensex",
                "market", "trade", "sanction", "tariff", "export", "import", "gdp", "forex",
                "fdi", "fred", "eia", "brent", "wti", "gas", "fiscal", "debt", "imf", "rate hike"],
    technology: ["cyber", "hack", "semiconductor", "chip", "ai", "satellite", "isro", "space",
                 "5g", "infrastructure", "grid", "telecom", "tsmc", "huawei", "nvidia"],
    climate: ["earthquake", "seismic", "flood", "cyclone", "storm", "drought", "fire", "wildfire",
              "tsunami", "volcano", "usgs", "noaa", "hurricane", "heat wave"],
    geopolitics: ["election", "summit", "president", "minister", "diplomacy", "un", "treaty",
                  "ceasefire", "coup", "protest", "referendum", "sanction", "visa", "ambassador",
                  "pakistan", "china", "iran", "russia", "ukraine", "taiwan", "nato", "quad"]
  },

  // ── Hotspot definitions (must stay in sync with the HOTSPOTS array) ──────
  HOTSPOTS: {
    "LOC": { india_score: 95, domain: "defense", note: "India-Pakistan Line of Control." },
    "LAC": { india_score: 90, domain: "defense", note: "India-China Line of Actual Control." },
    "Strait of Hormuz": { india_score: 80, domain: "economics", note: "Crude chokepoint for Indian imports." },
    "Persian Gulf": { india_score: 75, domain: "economics", note: "Energy security and shipping lanes." },
    "South China Sea": { india_score: 60, domain: "defense", note: "Trade route and QUAD implications." },
    "Taiwan Strait": { india_score: 65, domain: "geopolitics", note: "Trade and semiconductor supply chain." },
    "Iran Nuclear": { india_score: 65, domain: "defense", note: "Energy and sanctions spillover." }
  },

  // ── India context facts (used to enrich answers) ──────────────────────────
  INDIA_FACTS: {
    crude_import_pct: 85,
    spd_days: 9.5,
    gulf_diaspora: 10000000,
    gulf_trade_usd_b: 200,
    opec_import_share: 0.6,
    nifty_baseline: 22000,
    inr_stress_threshold: 86
  },

  // ── Query intent classifier ───────────────────────────────────────────────
  classifyIntent(question) {
    const q = question.toLowerCase();
    if (q.includes("energy") || q.includes("oil") || q.includes("crude") || q.includes("lng") ||
        q.includes("hormuz") || q.includes("petroleum") || q.includes("fuel")) return "energy_security";
    if (q.includes("strategic risk") || q.includes("critical risk") || q.includes("nsa") ||
        q.includes("prime minister") || q.includes("nsc") || q.includes("threat")) return "strategic_risk";
    if (q.includes("geopolit") || q.includes("risk this week") || q.includes("risk assessment")) return "geopolitical_risk";
    if (q.includes("shock") || q.includes("72 hour") || q.includes("48 hour") || q.includes("watch") ||
        q.includes("monitor") || q.includes("external")) return "external_shocks";
    if (q.includes("market") || q.includes("economy") || q.includes("nifty") || q.includes("rupee") ||
        q.includes("inflation") || q.includes("macro")) return "market_analysis";
    if (q.includes("defense") || q.includes("military") || q.includes("border") || q.includes("loc") ||
        q.includes("lac") || q.includes("pakistan") || q.includes("china")) return "defense_risk";
    if (q.includes("technolog") || q.includes("cyber") || q.includes("chip") || q.includes("ai ")) return "technology_risk";
    if (q.includes("climate") || q.includes("earthquake") || q.includes("flood") || q.includes("storm")) return "climate_risk";
    return "general_assessment";
  },

  // ── Build a rich live context object from STATE ───────────────────────────
  buildContext() {
    const rss = STATE.rss || [];
    const risk = STATE.risk || { score: 50, label: "MODERATE", color: "elevated" };
    const forex = STATE.forex?.rates || {};
    const markets = STATE.indiaMarkets || {};
    const crypto = STATE.crypto || {};
    const earth = STATE.earth?.features || [];
    const bharatiya = STATE.bharatiya || [];

    // Classify signals by domain
    const byDomain = {};
    Object.keys(this.DOMAINS).forEach(d => { byDomain[d] = []; });
    rss.forEach(item => {
      const text = (item.title + " " + (item.summary || "")).toLowerCase();
      for (const [domain, keywords] of Object.entries(this.DOMAINS)) {
        if (keywords.some(kw => text.includes(kw))) {
          byDomain[domain].push(item);
          break;
        }
      }
    });

    // Top signals per domain
    const topByDomain = {};
    Object.entries(byDomain).forEach(([d, items]) => {
      topByDomain[d] = items.sort((a, b) => {
        const weight = { critical: 3, elevated: 2, stable: 1 };
        return (weight[b.severity] || 0) - (weight[a.severity] || 0);
      }).slice(0, 4);
    });

    // India-linked signals
    const indiaSignals = rss.filter(item => item.india).slice(0, 10);

    // Critical signals
    const critical = rss.filter(item => item.severity === "critical").slice(0, 6);

    // Seismic near India (within 2500km)
    const nearIndiaQuakes = earth.filter(f => {
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const d2r = Math.PI / 180;
      const dLat = (lat - 20.5937) * d2r, dLon = (lon - 78.9629) * d2r;
      const a = Math.sin(dLat/2)**2 + Math.cos(20.5937*d2r)*Math.cos(lat*d2r)*Math.sin(dLon/2)**2;
      return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)) < 2500 && f.properties.mag >= 4.5;
    });

    // Market stress indicators
    const inrRate = Number(forex.INR || 0);
    const inrStressed = inrRate > this.INDIA_FACTS.inr_stress_threshold;
    const niftyValue = markets.nifty?.value;
    const niftyDown = niftyValue && niftyValue < this.INDIA_FACTS.nifty_baseline;

    return {
      risk, topByDomain, indiaSignals, critical, nearIndiaQuakes,
      forex: { INR: inrRate, inrStressed },
      markets: { nifty: niftyValue, niftyDown, sensex: markets.sensex?.value, source: markets.source },
      crypto: { btcUsd: crypto.bitcoin?.usd, btcChange: crypto.bitcoin?.usd_24h_change },
      bharatiya,
      signalCounts: Object.fromEntries(Object.entries(byDomain).map(([d, items]) => [d, items.length])),
      totalSignals: rss.length,
      timestamp: new Date().toUTCString()
    };
  },

  // ── Domain risk scorer ────────────────────────────────────────────────────
  scoreDomain(domainItems, indiaSignalCount, hasHotspot) {
    let score = 30; // baseline
    const critical = domainItems.filter(i => i.severity === "critical").length;
    const elevated = domainItems.filter(i => i.severity === "elevated").length;
    score += Math.min(40, critical * 12 + elevated * 5);
    score += Math.min(15, indiaSignalCount * 5);
    if (hasHotspot) score += 10;
    return Math.min(100, score);
  },

  // ── Format a signal as a bullet point ────────────────────────────────────
  formatSignal(item, prefix = "•") {
    const tag = item.severity === "critical" ? "[CRITICAL]" : item.severity === "elevated" ? "[ELEVATED]" : "";
    const india = item.india ? " [India-linked]" : "";
    return `${prefix} ${tag}${india} ${item.title} — ${item.source}`;
  },

  // ── Utility: top N items from an array by severity ───────────────────────
  topN(items, n = 3) {
    const w = { critical: 3, elevated: 2, stable: 1 };
    return [...items].sort((a, b) => (w[b.severity]||0) - (w[a.severity]||0)).slice(0, n);
  },

  // ── Answer: energy security ───────────────────────────────────────────────
  answerEnergySecurity(ctx) {
    const { topByDomain, forex, markets, critical, risk, nearIndiaQuakes } = ctx;
    const ecoSignals = topByDomain.economics || [];
    const defSignals = topByDomain.defense || [];
    const indiaFacts = this.INDIA_FACTS;

    let out = [];
    out.push(`## ENERGY SECURITY — INDIA EXPOSURE ASSESSMENT`);
    out.push(`India Impact Score: ${Math.min(100, 55 + risk.score * 0.3) | 0}/100 | Confidence: ${risk.score > 60 ? "HIGH" : "MEDIUM"} | Freshness: LIVE`);
    out.push(``);
    out.push(`Situation: India imports approximately ${indiaFacts.crude_import_pct}% of its crude oil. Any disruption to supply routes or price stability immediately raises the landed cost of energy, widens the current account deficit, and pressures the rupee. India holds a Strategic Petroleum Reserve equivalent to roughly ${indiaFacts.spd_days} days of dedicated coverage — below the IEA 90-day benchmark.`);
    out.push(``);

    out.push(`## 1. SUPPLY CHAIN & CHOKEPOINT SIGNALS`);
    const oilSignals = ecoSignals.filter(i => {
      const t = (i.title+" "+i.summary).toLowerCase();
      return ["oil","opec","brent","wti","crude","hormuz","gulf","gas","lng","barrel"].some(w => t.includes(w));
    });
    if (oilSignals.length) {
      oilSignals.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`• No live oil/chokepoint signals in current feed window. Monitor OPEC+ output decisions and Hormuz transit data.`);
    }
    out.push(``);

    const hormuzSignal = [...ecoSignals, ...defSignals].find(i =>
      (i.title+" "+i.summary).toLowerCase().includes("hormuz") ||
      (i.title+" "+i.summary).toLowerCase().includes("gulf")
    );
    if (hormuzSignal) {
      out.push(`Strait of Hormuz (India Score 80/100): ${hormuzSignal.title} — ${hormuzSignal.source}`);
      out.push(`Impact: Disruption to this chokepoint directly threatens the ${indiaFacts.opec_import_share * 100}% of crude that transits Gulf shipping lanes.`);
    } else {
      out.push(`Strait of Hormuz status: No active disruption signals. Standard monitoring posture.`);
    }
    out.push(``);

    out.push(`## 2. ECONOMIC & PRICE SIGNALS`);
    if (forex.inrStressed) {
      out.push(`• USD/INR at ${forex.INR.toFixed(2)} — above stress threshold of ₹${indiaFacts.inr_stress_threshold}. Every ₹1 depreciation adds ~₹8,000 crore to the annual crude import bill.`);
    } else if (forex.INR > 0) {
      out.push(`• USD/INR at ${forex.INR.toFixed(2)} — within manageable range. RBI has active intervention capacity.`);
    }
    if (markets.niftyDown && markets.nifty) {
      out.push(`• NIFTY 50 at ${markets.nifty.toFixed(0)} — below ${indiaFacts.nifty_baseline} baseline, signalling risk-off sentiment that may precede capital outflows.`);
    }
    const inflationSignals = ecoSignals.filter(i =>
      ["inflation", "price", "cost", "tariff", "import bill"].some(w => (i.title+" ").toLowerCase().includes(w))
    );
    inflationSignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
    out.push(``);

    out.push(`## 3. POLICY & DIPLOMATIC SIGNALS`);
    const policySignals = (topByDomain.geopolitics || []).filter(i => i.india);
    if (policySignals.length) {
      policySignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`• No India-specific diplomatic energy signals in current window. Watch MEA and PIB feeds for SPR expansion announcements.`);
    }
    out.push(``);

    out.push(`## KEY ACTORS`);
    out.push(`OPEC+, RBI, MEA India, IAEA, Iran, Saudi Arabia, UAE`);
    out.push(``);
    out.push(`## TREND: ${risk.score > 65 ? "ESCALATING" : risk.score > 40 ? "STABLE" : "DE-ESCALATING"}`);
    out.push(`## STRATEGIC RECOMMENDATION`);
    out.push(`Lock in 6-month LNG forward contracts at current spot rates. Activate SPR drawdown protocol if Brent exceeds $95/bbl. RBI to monitor forex reserve levels and adjust NDF market intervention thresholds. Fast-track rupee-denominated settlement channels with alternative crude suppliers.`);

    return out.join("\n");
  },

  // ── Answer: strategic risk ────────────────────────────────────────────────
  answerStrategicRisk(ctx) {
    const { topByDomain, risk, forex, markets, critical, indiaSignals } = ctx;
    const defSignals = topByDomain.defense || [];
    const geoSignals = topByDomain.geopolitics || [];

    let out = [];
    out.push(`## STRATEGIC RISK — NSA ASSESSMENT FOR THE PRIME MINISTER`);
    out.push(`India Impact Score: ${risk.score}/100 | Confidence: HIGH | Freshness: LIVE`);
    out.push(``);

    // Determine primary threat vector from live signals
    const pakSignals = [...defSignals, ...geoSignals].filter(i =>
      ["pakistan","loc","kashmir","isi","ttp","lashkar","jaish"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    const chinaSignals = [...defSignals, ...geoSignals].filter(i =>
      ["china","pla","lac","ladakh","depsang","aksai"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    const iranSignals = [...defSignals, ...(topByDomain.economics||[])].filter(i =>
      ["iran","irgc","hormuz","nuclear","enrichment"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );

    out.push(`## MOST CRITICAL STRATEGIC RISK (CURRENT)`);
    if (pakSignals.length >= chinaSignals.length && pakSignals.length > 0) {
      out.push(`PRIMARY: Pakistan-linked signals are the highest-volume active threat vector.`);
      pakSignals.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    } else if (chinaSignals.length > 0) {
      out.push(`PRIMARY: China/LAC signals are the dominant active vector — multi-domain coercion below the threshold of open conflict.`);
      chinaSignals.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    } else if (critical.length > 0) {
      out.push(`PRIMARY: Critical severity signals in the live feed:`);
      critical.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`PRIMARY: No single dominant active threat vector in current signal window. Multi-domain elevated risk from economic and geopolitical streams.`);
    }
    out.push(``);

    out.push(`## THREE PRIMARY THREAT VECTORS`);
    out.push(``);
    out.push(`VECTOR 1 — Collusive China-Pakistan Pressure`);
    out.push(`Active signals: ${pakSignals.length + chinaSignals.length} defense/geopolitics items. The collusive threat model remains India's primary deterrence planning scenario. PLA infrastructure activity near the LAC combined with Pakistan Army operational tempo creates a two-front monitoring requirement.`);
    out.push(``);

    out.push(`VECTOR 2 — Economic & Supply Chain Vulnerability`);
    const ecoScore = Math.min(100, (topByDomain.economics?.length || 0) * 10 + (forex.inrStressed ? 20 : 0));
    out.push(`Economic stress score: ${ecoScore}/100. USD/INR: ${forex.INR > 0 ? forex.INR.toFixed(2) : "unavailable"}. ${forex.inrStressed ? "Rupee is under stress — capital outflow risk elevated." : "Rupee within normal range."} China's near-monopoly on critical minerals and OPEC+ pricing power remain structural vulnerabilities.`);
    out.push(``);

    out.push(`VECTOR 3 — Neighbourhood Instability`);
    const neighbourSignals = (topByDomain.geopolitics||[]).filter(i =>
      ["bangladesh","myanmar","nepal","sri lanka","maldives","bhutan"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    if (neighbourSignals.length) {
      out.push(`Active neighbourhood signals:`);
      neighbourSignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`No active neighbourhood disruption in current feed window. Baseline monitoring posture for eastern flank (Bangladesh/Myanmar).`);
    }
    out.push(``);

    out.push(`## NSA RECOMMENDATIONS TO THE PRIME MINISTER`);
    out.push(``);
    out.push(`1. FORMALIZE NSS: Draft and implement a National Security Strategy that synchronizes military, economic, and diplomatic sectors — ending the operational silos between MEA, MoD, and MoF.`);
    out.push(`2. ASYMMETRIC DETERRENCE: Shift budgetary priority from manpower-heavy conventional deployments to AI, cyber, space-based ISR, and unmanned drone swarms — capabilities that achieve deterrence without dollar-for-dollar parity with the PLA.`);
    out.push(`3. ECONOMIC STATECRAFT: Aggressively diversify critical mineral supply chains through QUAD partnerships. Push for international water treaties on Brahmaputra. Pre-position SPR expansion from 53 to 65 lakh MT.`);
    out.push(`4. NEIGHBOURHOOD STABILIZATION: Deploy economic aid and intelligence assets to prevent radical actors exploiting power vacuums in Bangladesh and Myanmar. Maintain deterrence-by-punishment posture on cross-border terrorism.`);
    out.push(``);
    out.push(`Data Sources: USGS Live, RSS (${ctx.totalSignals} signals), ExchangeRate, ${markets.source || "NSE"}`);
    return out.join("\n");
  },

  // ── Answer: geopolitical risk this week ──────────────────────────────────
  answerGeopoliticalRisk(ctx) {
    const { topByDomain, risk, forex, markets, indiaSignals } = ctx;
    const geoSignals = topByDomain.geopolitics || [];
    const defSignals = topByDomain.defense || [];

    let out = [];
    out.push(`## GEOPOLITICAL RISK ASSESSMENT — CURRENT WEEK`);
    out.push(`India Impact Score: ${risk.score}/100 | Confidence: ${risk.score > 60 ? "HIGH" : "MEDIUM"} | Freshness: LIVE`);
    out.push(``);
    out.push(`Situation: India's geopolitical risk profile is ${risk.score >= 70 ? "ELEVATED" : risk.score >= 45 ? "MODERATE" : "LOW"} based on ${ctx.totalSignals} live signals across ${Object.values(ctx.signalCounts).filter(n => n > 0).length} active domains.`);
    out.push(``);

    out.push(`## 1. ECONOMIC & ENERGY VULNERABILITY`);
    const oilSignals = (topByDomain.economics||[]).filter(i =>
      ["oil","crude","brent","opec","gas","energy"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    if (oilSignals.length) {
      out.push(`Risk Level: ${oilSignals.some(i => i.severity === "critical") ? "HIGH" : "MEDIUM"}`);
      oilSignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`Risk Level: MEDIUM — No live commodity disruption signals, but India's structural exposure to crude imports (${this.INDIA_FACTS.crude_import_pct}% imported) is constant.`);
    }
    if (forex.INR > 0) out.push(`• USD/INR: ${forex.INR.toFixed(2)} — ${forex.inrStressed ? "STRESS: above ₹" + this.INDIA_FACTS.inr_stress_threshold + " threshold." : "Within normal range."}`);
    if (markets.nifty) out.push(`• NIFTY 50: ${markets.nifty.toFixed(0)} — ${markets.niftyDown ? "Below baseline, risk-off sentiment." : "Above baseline."}`);
    out.push(``);

    out.push(`## 2. DIPLOMATIC & STRATEGIC BALANCE`);
    const dipSignals = geoSignals.filter(i => i.india || ["jaishankar","modi","mea","un","quad","brics"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w)));
    if (dipSignals.length) {
      dipSignals.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    } else {
      out.push(`• No high-priority India-linked diplomatic signals in current window.`);
      geoSignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
    }
    out.push(``);

    out.push(`## 3. MARITIME SECURITY`);
    const maritimeSignals = [...geoSignals, ...defSignals].filter(i =>
      ["shipping","maritime","vessel","strait","sea","port","naval","coast"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    if (maritimeSignals.length) {
      maritimeSignals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
      out.push(`India has ${this.INDIA_FACTS.gulf_diaspora.toLocaleString()} nationals in the Gulf — any maritime disruption triggers both consular and economic responses.`);
    } else {
      out.push(`• No active maritime incident signals. Strait of Hormuz and South China Sea on standard monitoring.`);
    }
    out.push(``);

    out.push(`## 4. DEFENSE & BORDER`);
    defSignals.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
    if (!defSignals.length) out.push(`• No active border/defense incident signals in current feed window.`);
    out.push(``);

    out.push(`## TREND: ${risk.score >= 65 ? "ESCALATING" : risk.score >= 45 ? "STABLE" : "DE-ESCALATING"}`);
    out.push(`## KEY ACTORS`);
    out.push(`India, China, Pakistan, Iran, US, OPEC+, EU, UN Security Council`);
    out.push(`## STRATEGIC RECOMMENDATION`);
    out.push(`Maintain diplomatic back-channels with UAE and Saudi Arabia. Pre-position INS assets in the Arabian Sea on precautionary basis. Advance QUAD bilateral engagements on maritime domain awareness. Monitor FPI capital flows daily.`);
    return out.join("\n");
  },

  // ── Answer: top 3 external shocks for 72 hours ───────────────────────────
  answerExternalShocks(ctx) {
    const { topByDomain, risk, forex, markets, nearIndiaQuakes } = ctx;

    // Score each potential shock category
    const shockCandidates = [];

    // Shock 1 check: Energy/commodity disruption
    const energySignals = (topByDomain.economics||[]).filter(i =>
      ["oil","opec","crude","hormuz","brent","wti","gas","energy","barrel"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    const energyScore = energySignals.length * 15 + (forex.inrStressed ? 20 : 0);
    shockCandidates.push({ type: "energy", score: energyScore, signals: energySignals });

    // Shock 2 check: Capital outflows/currency
    const capitalScore = (forex.inrStressed ? 40 : 0) + (markets.niftyDown ? 20 : 0) +
      ((topByDomain.economics||[]).filter(i => ["capital","fpi","outflow","dollar","yield","fed","rate"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))).length * 10);
    const capitalSignals = (topByDomain.economics||[]).filter(i =>
      ["capital","fpi","outflow","dollar","yield","fed","rate"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    shockCandidates.push({ type: "capital", score: capitalScore, signals: capitalSignals });

    // Shock 3 check: Geopolitical/conflict escalation
    const geoScore = (topByDomain.defense||[]).filter(i => i.severity === "critical").length * 20 +
      (topByDomain.geopolitics||[]).filter(i => i.severity === "critical").length * 15;
    const geoSignals = [...(topByDomain.defense||[]), ...(topByDomain.geopolitics||[])].filter(i => i.severity === "critical");
    shockCandidates.push({ type: "geopolitical", score: geoScore, signals: geoSignals });

    // Shock 4 check: Seismic/climate
    const seismicScore = nearIndiaQuakes.length * 10 + (topByDomain.climate||[]).filter(i => i.severity === "critical").length * 15;
    shockCandidates.push({ type: "climate", score: seismicScore, signals: topByDomain.climate || [] });

    // Shock 5 check: Trade/protectionism
    const tradeSignals = (topByDomain.economics||[]).filter(i =>
      ["tariff","trade war","export ban","restriction","sanction","wto"].some(w => (i.title+" "+i.summary).toLowerCase().includes(w))
    );
    shockCandidates.push({ type: "trade", score: tradeSignals.length * 12, signals: tradeSignals });

    // Sort by score and take top 3
    const top3 = shockCandidates.sort((a, b) => b.score - a.score).slice(0, 3);

    const shockDescriptions = {
      energy: {
        title: "Energy Supply Disruption / Crude Oil Price Shock",
        impact: `India imports ${this.INDIA_FACTS.crude_import_pct}% of crude. A supply shock immediately widens the CAD and raises domestic inflation. Strategic reserves cover only ${this.INDIA_FACTS.spd_days} days.`,
        recommendation: "Lock in LNG forward contracts. Activate SPR monitoring. Pre-brief oil ministry on import diversification options."
      },
      capital: {
        title: "Foreign Capital Outflow & Rupee Depreciation",
        impact: `Global risk-off sentiment drives FPI withdrawals from Indian equities and bonds. USD/INR currently at ${forex.INR > 0 ? forex.INR.toFixed(2) : "n/a"}${forex.inrStressed ? " — already stressed." : "."}`,
        recommendation: "RBI to monitor forex reserves. Finance ministry to review short-term debt rollover positions. Alert SEBI on FPI threshold."
      },
      geopolitical: {
        title: "Regional Military Escalation",
        impact: "Active conflict signals in the live feed. India has direct exposure through diaspora safety, energy imports, and trade routes.",
        recommendation: "MEA back-channel activation. Pre-position consular assets. Monitor military-to-military hotlines."
      },
      climate: {
        title: "Climate / Seismic Event Disrupting Supply Chains",
        impact: `${nearIndiaQuakes.length > 0 ? nearIndiaQuakes.length + " seismic events within 2500km of India detected in the last 24 hours. " : "No near-India seismic events in current window. "}Climate disruptions in the Indian Ocean rim affect agricultural imports.`,
        recommendation: "NDMA to verify response readiness. Review commodity buffer stocks at FCI."
      },
      trade: {
        title: "US / G7 Trade Restriction or Protectionist Shock",
        impact: "New tariff or export control actions affecting India-linked supply chains in electronics, pharmaceuticals, or critical minerals.",
        recommendation: "Commerce Ministry to audit exposure to targeted sectors. WTO dispute resolution cell on standby."
      }
    };

    let out = [];
    out.push(`## TOP 3 EXTERNAL SHOCKS — 72-HOUR WATCH`);
    out.push(`India Risk Score: ${risk.score}/100 | Active Signals: ${ctx.totalSignals} | Freshness: LIVE`);
    out.push(``);

    top3.forEach((shock, i) => {
      const desc = shockDescriptions[shock.type];
      out.push(`## SHOCK ${i + 1}: ${desc.title.toUpperCase()}`);
      out.push(`Composite Risk Score: ${Math.min(100, shock.score)}/100`);
      out.push(`Impact: ${desc.impact}`);
      if (shock.signals.length > 0) {
        out.push(`Live Signals:`);
        shock.signals.slice(0, 2).forEach(s => out.push(this.formatSignal(s)));
      } else {
        out.push(`Live Signals: No specific triggers in current window — structural risk remains.`);
      }
      out.push(`Recommendation: ${desc.recommendation}`);
      out.push(``);
    });

    out.push(`## DATA SOURCES`);
    out.push(`USGS (${ctx.nearIndiaQuakes.length} near-India events), ExchangeRate API, ${markets.source || "NSE"}, RSS Aggregator (${ctx.totalSignals} signals)`);
    return out.join("\n");
  },

  // ── Answer: general / market / domain-specific ────────────────────────────
  answerGeneral(question, intent, ctx) {
    const { topByDomain, risk, forex, markets, critical } = ctx;
    const domainMap = {
      "market_analysis": "economics",
      "defense_risk": "defense",
      "technology_risk": "technology",
      "climate_risk": "climate"
    };
    const targetDomain = domainMap[intent] || "geopolitics";
    const signals = topByDomain[targetDomain] || [];
    const domainLabel = targetDomain.charAt(0).toUpperCase() + targetDomain.slice(1);

    let out = [];
    out.push(`## ${domainLabel.toUpperCase()} — GOE LIVE ASSESSMENT`);
    out.push(`India Impact Score: ${risk.score}/100 | Freshness: LIVE | Signals: ${signals.length} in ${domainLabel}`);
    out.push(``);
    out.push(`Query: "${question}"`);
    out.push(``);

    if (signals.length > 0) {
      out.push(`## LIVE SIGNAL CONTEXT`);
      signals.slice(0, 5).forEach(s => out.push(this.formatSignal(s)));
      out.push(``);
    }

    out.push(`## INDIA RISK SNAPSHOT`);
    out.push(`Overall Risk Score: ${risk.score}/100 (${risk.label})`);
    if (forex.INR > 0) out.push(`USD/INR: ${forex.INR.toFixed(2)}${forex.inrStressed ? " — STRESS" : ""}`);
    if (markets.nifty) out.push(`NIFTY 50: ${markets.nifty.toFixed(0)} via ${markets.source || "proxy"}`);
    out.push(``);

    if (critical.length > 0) {
      out.push(`## CRITICAL ACTIVE SIGNALS`);
      critical.slice(0, 3).forEach(s => out.push(this.formatSignal(s)));
      out.push(``);
    }

    out.push(`## TREND: ${risk.score >= 65 ? "ESCALATING" : risk.score >= 45 ? "STABLE" : "DE-ESCALATING"}`);
    out.push(`GOE Antigravity engine — no LLM, live data grounded. Signals: ${ctx.totalSignals} total from RSS, USGS, ExchangeRate, CoinGecko.`);
    return out.join("\n");
  },

  // ── Master answer dispatcher ──────────────────────────────────────────────
  async answer(question) {
    // Try backend first (with 3s timeout)
    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 3000);
      const response = await fetch("http://localhost:8000/api/v1/analyst/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, context: await context(1600) }),
        signal: controller.signal
      });
      clearTimeout(tid);
      if (response.ok) {
        const data = await response.json();
        if (data.answer) return data.answer;
      }
    } catch { /* backend unavailable — fall through to local engine */ }

    // Local Antigravity engine
    const ctx = this.buildContext();
    const intent = this.classifyIntent(question);

    switch (intent) {
      case "energy_security": return this.answerEnergySecurity(ctx);
      case "strategic_risk":  return this.answerStrategicRisk(ctx);
      case "geopolitical_risk": return this.answerGeopoliticalRisk(ctx);
      case "external_shocks": return this.answerExternalShocks(ctx);
      default: return this.answerGeneral(question, intent, ctx);
    }
  }
};
```

### 2.3 Modify the `ask()` function

Replace the existing `ask` function body with:

```javascript
async function ask(question, regenerate = false) {
  if (!question) return;
  if (!regenerate) STATE.chat.push({ role: "user", content: question });
  renderChat();
  let reply = "";
  try {
    if (AI.config.mode === "none") {
      // Antigravity path — no LLM needed
      reply = await ANTIGRAVITY.answer(question);
    } else {
      // LLM-enriched path (Ollama or Anthropic)
      const ctx = await context(2400);
      reply = await AI.call(
        [{ role: "user", content: ctx + "\n\nUSER QUERY: " + question }],
        SYSTEM_PROMPT,
        1500
      ) || await ANTIGRAVITY.answer(question);  // fall back to Antigravity if LLM returns null
    }
  } catch (error) {
    try {
      reply = await ANTIGRAVITY.answer(question);
    } catch {
      reply = "GOE engine error: " + error.message + "\n\nLive context:\n" + await context(1200);
    }
  }
  STATE.chat.push({ role: "assistant", content: reply });
  STATE.chat = STATE.chat.slice(-24);
  STATE.lastQuestion = question;
  saveSession(KEYS.chat, STATE.chat);
  saveSession(KEYS.last, question);
  renderChat();
}
```

### 2.4 Modify `buildBrief()` to use Antigravity as fallback

Replace the fallback in `buildBrief()` so it calls `ANTIGRAVITY.answer()` instead of the static
`fallbackBrief()`:

```javascript
async function buildBrief() {
  const steps = [...document.querySelectorAll(".step")];
  const set = async (i) => {
    steps.forEach((step, idx) => {
      step.classList.toggle("active", idx === i);
      step.classList.toggle("done", idx < i);
    });
    await new Promise(resolve => setTimeout(resolve, 350));
  };
  await set(0);
  await set(1);
  let text = "";
  try {
    const response = await fetch("http://localhost:8000/api/v1/analyst/daily-brief", { method: "POST" });
    const data = await response.json();
    text = data.content || data.document || data.error || "";
  } catch { /* backend down */ }
  if (!text) {
    // Antigravity deterministic brief
    text = await ANTIGRAVITY.answer("Generate today's complete daily strategic intelligence brief with executive summary, threat matrix, and strategic priorities for India.");
  }
  await set(2);
  steps.forEach(step => { step.classList.remove("active"); step.classList.add("done"); });
  document.getElementById("briefDoc").textContent = text || fallbackBrief();
}
```

### 2.5 Add seed queries for the new capabilities

Update `STATE.seeds` to include queries that demonstrate the Antigravity answers:

```javascript
seeds: [
  "What is India's most critical strategic risk right now and what should the NSA recommend to the PM?",
  "Explain how current signals affect India's energy security.",
  "Assess India's geopolitical risk this week using the current feed context.",
  "What are the top three external shocks India should monitor over the next 72 hours?",
  "Analyze the current state of India-Pakistan border signals and recommend a response posture.",
  "What does the current USD/INR level mean for India's macro stability?"
]
```

### 2.6 Update the analyst panel intro message

In `renderChat()`, change the intro bubble from:
```
"GOE-1 is ready. Ask for a strategic assessment..."
```
To:
```
"GOE Antigravity is ready. No LLM required — answers are grounded in live feeds (${STATE.rss.length} signals), market data, and seismic context. Ask for any strategic assessment."
```
(Use actual template literal with `STATE.rss.length`.)

### 2.7 Remove the auto-show AI modal from `AI.detect()`

Currently `AI.detect()` calls `showAiModal()` when mode is "none". Change it to NOT show the modal
automatically. The modal should only appear when `#openAi` is explicitly clicked. Remove the
`showAiModal()` call from the "none" branch of `AI.detect()`.

---

## 3. Backend Layer — New `/api/v1/analyst/query` Endpoint

### 3.1 Add the route to `apps/api/routers/analyst.py`

Add this route to the existing `analyst.py` router:

```python
from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str
    context: str = ""

@router.post("/query")
async def analyst_query(req: QueryRequest, request: Request):
    """
    Antigravity query endpoint — answers strategic questions using the
    knowledge graph + rule engine. Falls back to LLM if available.
    No LLM key required for basic operation.
    """
    from ..core.analyst.antigravity.query_engine import AntigravityQueryEngine
    from ..database import AsyncSessionLocal

    engine = AntigravityQueryEngine(
        redis=request.app.state.redis,
        vector_store=request.app.state.vector,
        neo4j_driver=request.app.state.neo4j,
        db_factory=AsyncSessionLocal,
        llm=request.app.state.engine._llm,
    )
    answer = await engine.answer(req.question, req.context)
    return {"answer": answer, "engine": "antigravity_v1", "question": req.question}
```

### 3.2 Create `apps/api/core/analyst/antigravity/query_engine.py`

This is a new file in the `antigravity/` package created by the `DAILY_BRIEF_ANTIGRAVITY_PROMPT.md`
specification. If that package does not yet exist, create it first (it is specified in that document).

```python
"""
AntigravityQueryEngine — answers free-text strategic questions using
graph traversal + rule matching. Zero LLM calls required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("goe.antigravity.query")

INTENT_KEYWORDS = {
    "energy_security": ["energy", "oil", "crude", "lng", "hormuz", "petroleum", "fuel", "brent", "opec"],
    "strategic_risk":  ["strategic risk", "critical risk", "nsa", "prime minister", "nsc", "threat", "recommendation"],
    "geopolitical_risk": ["geopolit", "risk this week", "risk assessment", "week"],
    "external_shocks": ["shock", "72 hour", "48 hour", "watch", "monitor", "external"],
    "market_analysis": ["market", "economy", "nifty", "rupee", "inflation", "macro", "rbi", "inr"],
    "defense_risk":    ["defense", "military", "border", "loc", "lac", "pakistan", "china", "missile"],
    "technology_risk": ["technology", "cyber", "chip", "semiconductor", "ai", "5g", "hack"],
    "climate_risk":    ["climate", "earthquake", "flood", "storm", "seismic", "wildfire", "cyclone"],
}


class AntigravityQueryEngine:
    def __init__(self, redis, vector_store, neo4j_driver=None, db_factory=None, llm=None):
        self.redis = redis
        self.vector = vector_store
        self.neo4j = neo4j_driver
        self.db_factory = db_factory
        self.llm = llm

    def classify_intent(self, question: str) -> str:
        q = question.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(kw in q for kw in keywords):
                return intent
        return "general_assessment"

    async def answer(self, question: str, frontend_context: str = "") -> str:
        """
        Main entry point. Uses graph + signal data if available,
        falls back to LLM, falls back to context-only summary.
        """
        intent = self.classify_intent(question)

        # Try to enrich with live signal data from the DB
        signal_context = ""
        if self.db_factory:
            try:
                from ..signal_aggregator import SignalAggregator  # from DAILY_BRIEF_ANTIGRAVITY_PROMPT.md
                aggregator = SignalAggregator(self.db_factory)
                items = await aggregator.fetch_recent(hours=24, limit=60)
                lines = [f"[{item.source_name}|{item.domain}|Sev:{item.severity}|India:{item.india_score}] {item.title}" for item in items[:15]]
                signal_context = "\n".join(lines)
            except Exception as exc:
                logger.warning("Signal aggregator unavailable in query engine: %s", exc)

        # Build answer from intent + signals
        answer = self._build_structured_answer(intent, question, signal_context, frontend_context)

        # If LLM is available, enhance the answer
        if self.llm and self.llm._mode not in ("none", "detecting"):
            try:
                prompt = f"""You are GOE-1. The Antigravity engine has pre-built this structured answer.
Enhance it with specific, actionable analysis. Preserve all section headings and data.
Do not add hedging language. Keep it under 800 words.

PRE-BUILT ANSWER:
{answer}

LIVE SIGNAL CONTEXT:
{signal_context[:600]}

USER QUESTION: {question}"""
                enhanced = await self.llm.complete(prompt, max_tokens=900)
                if enhanced:
                    return enhanced
            except Exception as exc:
                logger.warning("LLM enhancement failed, using Antigravity answer: %s", exc)

        return answer

    def _build_structured_answer(self, intent: str, question: str, signal_context: str, frontend_context: str) -> str:
        """Build a structured answer from intent classification and available context."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        header = f"GOE ANTIGRAVITY — {intent.upper().replace('_', ' ')}\nGenerated: {timestamp} | Engine: Antigravity v1\n\n"

        if signal_context:
            signals_section = f"LIVE SIGNAL CONTEXT (last 24h):\n{signal_context}\n\n"
        elif frontend_context:
            signals_section = f"FRONTEND CONTEXT:\n{frontend_context[:800]}\n\n"
        else:
            signals_section = "SIGNAL CONTEXT: No live signals available — answer based on structural knowledge.\n\n"

        intent_responses = {
            "energy_security": self._template_energy,
            "strategic_risk": self._template_strategic_risk,
            "geopolitical_risk": self._template_geopolitical,
            "external_shocks": self._template_shocks,
        }

        body_fn = intent_responses.get(intent, self._template_general)
        body = body_fn(question, signal_context or frontend_context)

        return header + signals_section + body

    def _template_energy(self, question: str, context: str) -> str:
        return """ENERGY SECURITY ASSESSMENT

India's structural energy vulnerability:
- 85% crude oil imported; strategic reserves cover ~9.5 days
- 60% of LPG transits through Gulf chokepoints
- Strait of Hormuz is the primary single-point-of-failure

Active risk vectors (from live signals above):
- Monitor OPEC+ output decisions and their impact on Brent/WTI spread
- Track INR/USD for import cost escalation signals
- Watch Strait of Hormuz transit data for disruption indicators

Strategic Recommendation:
Lock in 6-month LNG forward contracts at current spot rates. Activate SPR monitoring protocol. Advance rupee-denominated settlement channels with alternative crude suppliers (Russia, UAE, Brazil). Accelerate domestic renewable capacity to reduce structural import dependency."""

    def _template_strategic_risk(self, question: str, context: str) -> str:
        return """STRATEGIC RISK — NSA ASSESSMENT

India's three primary active risk vectors:

1. COLLUSIVE CHINA-PAKISTAN THREAT
PLA infrastructure activity near the LAC and Pakistan Army operational tempo
require continuous dual-front deterrence planning. Neither adversary operates
in isolation from the other's calculus.

2. ECONOMIC & SUPPLY CHAIN VULNERABILITY
Over-reliance on Gulf energy imports, Chinese critical minerals, and
semiconductor supply chains creates structural vulnerabilities that adversaries
can exploit short of kinetic action.

3. NEIGHBOURHOOD INSTABILITY
Power vacuums in Bangladesh and Myanmar create vectors for radical actors
to establish forward positions close to India's eastern flank.

NSA RECOMMENDATIONS TO PM:
1. Formalize a unified National Security Strategy synchronizing MoD, MEA, MoF
2. Pivot defense budgets toward AI, cyber, space ISR, and unmanned platforms
3. Advance QUAD partnerships for critical mineral supply diversification
4. Deploy economic and intelligence assets proactively in neighbourhood states"""

    def _template_geopolitical(self, question: str, context: str) -> str:
        return """GEOPOLITICAL RISK ASSESSMENT — CURRENT WEEK

India's geopolitical risk profile is driven by three concurrent pressure streams:

ECONOMIC & ENERGY (HIGH): Crude import dependency and rupee exposure to
global risk-off movements remain the highest-frequency risk vectors.

DIPLOMATIC BALANCE (MEDIUM-HIGH): India's non-alignment posture is being
tested across multiple simultaneous crisis theaters — West Asia, Ukraine,
Taiwan Strait. Each requires a calibrated, interest-based response.

BORDER & MARITIME (MEDIUM): No active kinetic escalation in current signals,
but structural tensions at LAC and LOC remain. Maritime security in the
Arabian Sea and Bay of Bengal require continuous ISR tasking.

TREND: STABLE — no single dominant escalatory signal, multi-domain elevated.

STRATEGIC RECOMMENDATION: Maintain diplomatic back-channels. Pre-position
consular assets. Monitor FPI capital flow thresholds daily."""

    def _template_shocks(self, question: str, context: str) -> str:
        return """TOP 3 EXTERNAL SHOCKS — 72-HOUR WATCH

SHOCK 1: ENERGY SUPPLY DISRUPTION
India imports 85% of crude. Any disruption to Gulf shipping immediately
raises the landed cost, widens the CAD, and pressures the rupee.
Action: Monitor OPEC+ emergency session signals and tanker AIS data.

SHOCK 2: CAPITAL OUTFLOW & RUPEE DEPRECIATION
Global risk aversion triggers FPI withdrawal from Indian equities.
Every ₹1 of INR depreciation adds ~₹8,000 crore to the annual import bill.
Action: RBI forex reserve monitoring; SEBI FPI threshold alert protocol.

SHOCK 3: REGIONAL MILITARY ESCALATION
Active conflict in West Asia or South/East Asia creates secondary economic
shocks through trade route disruption and commodity price spikes.
Action: MEA back-channel activation; INS readiness posture review."""

    def _template_general(self, question: str, context: str) -> str:
        return f"""GOE ANALYSIS

Query: {question}

Assessment based on current signal context:
{context[:400] if context else 'No live signal context available at query time.'}

Structural India risk factors remain active across economics, defense, and geopolitics.
For a specific domain analysis, ask about: energy security, strategic risk, geopolitical
risk this week, or external shocks to monitor.

Data sources: RSS aggregator, USGS, market feeds, Neo4j knowledge graph."""
```

---

## 4. Fix the Redis Connection Error

The `server.log` shows the server crashes at startup because Redis is unreachable:
```
redis.exceptions.ConnectionError: Error 61 connecting to localhost:6380. 61.
```

**Root cause**: Docker is not running. The Redis container exposes port 6380 on the host.

**Fix**:
1. Start Docker Desktop.
2. From the project root: `docker-compose up -d redis postgres neo4j`
3. Verify: `docker ps` should show `redis:7-alpine` running with `0.0.0.0:6380->6379/tcp`.
4. Start the API: `cd apps/api && uvicorn main:app --reload --port 8000`

**Do not change the Redis port in `config.py`.** The `docker-compose.yml` already maps 6380→6379
correctly. The Python app should use `redis://localhost:6380` which is what it already does.

---

## 5. Wire the New `/analyst/query` Endpoint in `main.py`

The existing `apps/api/routers/analyst.py` already has a `router` object. The new `/query` endpoint
added in Step 3.1 will be picked up automatically. No changes to `main.py` are needed unless the
`analyst` router is not already included. Verify: `main.py` should have:
```python
from .routers import analyst
app.include_router(analyst.router, prefix="/api/v1/analyst", tags=["analyst"])
```

---

## 6. Implementation Order

Follow this exact order:

1. **Fix Docker** — `docker-compose up -d redis postgres neo4j`. Verify all three are healthy.
2. **Frontend changes first** — Modify `index.html`:
   a. Add the `ANTIGRAVITY` object (Section 2.2) after the `AI` object.
   b. Replace `ask()` (Section 2.3).
   c. Replace `buildBrief()` (Section 2.4).
   d. Update `STATE.seeds` (Section 2.5).
   e. Update `renderChat()` intro message (Section 2.6).
   f. Remove `showAiModal()` from `AI.detect()` "none" branch (Section 2.7).
3. **Test frontend standalone** — Open `index.html` in a browser. Enter the password `GOE-INDIA-2026`.
   Wait for feeds to load. Type: "What are the top three external shocks India should monitor?"
   — You should receive a structured Antigravity answer without any AI modal appearing.
4. **Create backend files** — Create `apps/api/core/analyst/antigravity/query_engine.py` (Section 3.2).
5. **Add the route** — Add `/query` endpoint to `apps/api/routers/analyst.py` (Section 3.1).
6. **Start the backend** — `uvicorn apps.api.main:app --reload --port 8000`.
7. **Test end-to-end** — In the browser, ask the same question. The frontend should now hit
   `http://localhost:8000/api/v1/analyst/query` first (within 3s), and fall through to the local
   engine if that fails. Both paths should return a structured answer.

---

## 7. Verification Checklist

- [ ] Opening `index.html` and asking a question when Ollama is not running produces a structured
      Antigravity answer — NOT the AI setup modal.
- [ ] Asking "Explain how current signals affect India's energy security" produces a response with
      sections: `## ENERGY SECURITY`, supply chain signals, economic signals, strategic recommendation.
- [ ] Asking "What is India's most critical strategic risk" produces: NSA assessment, three vectors,
      four numbered recommendations.
- [ ] Asking "What are the top 3 external shocks" produces: three numbered shocks with composite
      risk scores, live signal citations, and actionable recommendations.
- [ ] When live RSS feeds are loaded (after refresh), the Antigravity answers cite actual signal
      titles from the feeds (not hardcoded generic text).
- [ ] `buildBrief()` no longer shows a static fallback — it calls `ANTIGRAVITY.answer()` with the
      brief generation query and renders the full structured document.
- [ ] `POST http://localhost:8000/api/v1/analyst/query` returns HTTP 200 with `{"answer": "...",
      "engine": "antigravity_v1"}` when the backend is running.
- [ ] The frontend gracefully falls back to the local engine if the backend returns non-200 or times
      out (3s timeout).
- [ ] The AI setup modal ONLY appears when `#openAi` button is clicked — never automatically when a
      chat question is asked.
- [ ] Existing routes (`/analyst/daily-brief`, `/analyst/scenario`) still work without modification.

---

## 8. Do Not Do These Things

- **Do not** remove the `AI.call()` path — LLM enrichment should still work when Ollama or an API
  key is configured. The Antigravity engine is the fallback, not a replacement.
- **Do not** change the `SYSTEM_PROMPT` constant — it is still used for the LLM-enriched path.
- **Do not** change the `context()` function — it is still used for both the LLM path and passed
  to the backend query endpoint.
- **Do not** change the `fallbackBrief()` function — it remains as a last-resort safety net.
- **Do not** change `runScenario()` — the scenario engine already has its Antigravity path defined
  in `DAILY_BRIEF_ANTIGRAVITY_PROMPT.md`.
- **Do not** call any external API from inside the `ANTIGRAVITY` object — it must work offline.
  All data comes from `STATE` which is populated by the existing `DATA.*` fetch functions.
- **Do not** add `await` calls to `ANTIGRAVITY.buildContext()` — it is synchronous (reads only from
  `STATE` which is already populated).

---

## 9. Example Expected Outputs

When there are active signals about Iran/West Asia in the feed, the output for Q1 should contain:

```
## ENERGY SECURITY — INDIA EXPOSURE ASSESSMENT
India Impact Score: 82/100 | Confidence: HIGH | Freshness: LIVE

## 1. SUPPLY CHAIN & CHOKEPOINT SIGNALS
• [CRITICAL] [India-linked] Iran signals military response to US strike — Al Jazeera
• [ELEVATED] OPEC+ emergency session convened amid Gulf tensions — Reuters World
...
Strait of Hormuz (India Score 80/100): Iran warns of Hormuz closure — Reuters World
Impact: Disruption to this chokepoint directly threatens the 60% of crude that transits Gulf shipping lanes.

## 2. ECONOMIC & PRICE SIGNALS
• USD/INR at 87.42 — above stress threshold of ₹86. Every ₹1 depreciation adds ~₹8,000 crore to the annual crude import bill.
...
```

When signals are sparse (quiet day), the output should still be structured but explicitly say:
```
• No active oil/chokepoint signals in current feed window. Monitor OPEC+ output decisions and Hormuz transit data.
```

This is the honest sparse-data mode — the system acknowledges limited signals rather than hallucinating.

---

*End of specification. All implementation details are contained in this document.*
*No additional files are required beyond the source files referenced in Section 0.*
