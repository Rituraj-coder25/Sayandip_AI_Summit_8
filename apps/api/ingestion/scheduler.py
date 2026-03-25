import json
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ── Existing connectors ──
from .connectors.acled import ACLEDConnector
from .connectors.coingecko import CoinGeckoConnector
from .connectors.gdelt import GDELTConnector
from .connectors.iaea import IAEAConnector
from .connectors.india_gov import IndiaGovConnector
from .connectors.nasa_firms import NASAFirmsConnector
from .connectors.noaa import NOAAConnector
from .connectors.opensky import OpenSkyConnector
from .connectors.reliefweb import ReliefWebConnector
from .connectors.usgs import USGSConnector
from .connectors.who import WHOConnector
from .connectors.worldbank import WorldBankConnector
from .connectors.yahoo_finance import YahooFinanceConnector

# ── New connectors ──
from .connectors.mass_rss import MassRSSAggregatorConnector
from .connectors.gov_advisories import GovAdvisoryConnector
from .connectors.cyber_ioc import CyberIOCConnector
from .connectors.natural_disasters import NaturalDisasterConnector
from .connectors.climate_anomalies import ClimateAnomalyConnector
from .connectors.aviation_delays import AviationDelaysConnector
from .connectors.internet_outages import InternetOutagesConnector
from .connectors.gps_jamming import GPSJammingConnector
from .connectors.fred_economic import FREDEconomicConnector
from .connectors.eia_energy import EIAEnergyConnector
from .connectors.polymarket import PolymarketConnector
from .connectors.bis_data import BISDataConnector
from .connectors.wto_trade import WTOTradeConnector
from .connectors.humanitarian import HumanitarianConnector
from .connectors.oref_alerts import OREFAlertsConnector
from .connectors.iran_liveuamap import IranLiveUAMapConnector
from .connectors.health_feeds import GlobalHealthFeedsConnector
from .connectors.live_streams import LiveStreamCatalogConnector
from .connectors.ucdp import UCDPConnector
from .connectors.nga_navwarnings import NGANavWarningsConnector

# ── Scraper Agents ──
from .agents.world_monitor_agent import WorldMonitorAgent
from .agents.playwright_scraper_agent import PlaywrightScraperAgent
from .agents.ai_director_agent import AIDirectorAgent

logger = logging.getLogger("goe.scheduler")


class GOEScheduler:
    def __init__(self, redis_client, http_client, db_factory, intelligence_engine, alert_engine):
        self.redis = redis_client
        self.http = http_client
        self.db_factory = db_factory
        self.engine = intelligence_engine
        self.alerts = alert_engine
        self.sched = AsyncIOScheduler(timezone="UTC")

        args = (redis_client, http_client)
        connector_list = [
            # ── Existing (kept) ──
            USGSConnector(*args),
            GDELTConnector(*args),
            ACLEDConnector(*args),
            CoinGeckoConnector(*args),
            WorldBankConnector(*args),
            NASAFirmsConnector(*args),
            NOAAConnector(*args),
            WHOConnector(*args),
            ReliefWebConnector(*args),
            IAEAConnector(*args),
            OpenSkyConnector(*args),
            YahooFinanceConnector(*args),
            IndiaGovConnector(*args),
            # ── New connectors ──
            MassRSSAggregatorConnector(*args),
            GovAdvisoryConnector(*args),
            CyberIOCConnector(*args),
            NaturalDisasterConnector(*args),
            ClimateAnomalyConnector(*args),
            AviationDelaysConnector(*args),
            InternetOutagesConnector(*args),
            GPSJammingConnector(*args),
            FREDEconomicConnector(*args),
            EIAEnergyConnector(*args),
            PolymarketConnector(*args),
            BISDataConnector(*args),
            WTOTradeConnector(*args),
            HumanitarianConnector(*args),
            OREFAlertsConnector(*args),
            IranLiveUAMapConnector(*args),
            GlobalHealthFeedsConnector(*args),
            LiveStreamCatalogConnector(*args),
            UCDPConnector(*args),
            NGANavWarningsConnector(*args),
        ]
        self.connectors = {connector.SOURCE_NAME: connector for connector in connector_list}

        # ── Register Scraper Agents ──
        agent_args = (redis_client, http_client)
        self.agents = [
            WorldMonitorAgent(*agent_args),
            PlaywrightScraperAgent(*agent_args),
            AIDirectorAgent(*agent_args, llm=None),   # llm injected after build in main.py
        ]

    def start(self):
        for name, connector in self.connectors.items():
            self.sched.add_job(
                self._run,
                trigger=IntervalTrigger(seconds=60),
                args=[name, connector],
                id=f"connector_{name}",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=30,
            )

        # Add agent jobs to scheduler (identical pattern to connector jobs)
        for agent in self.agents:
            self.sched.add_job(
                self._run_agent,
                trigger=IntervalTrigger(seconds=agent.POLL_INTERVAL_SECONDS),
                args=[agent],
                id=f"agent_{agent.AGENT_NAME}",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )

        self.sched.add_job(self._risk_score, trigger=IntervalTrigger(minutes=15), id="india_risk_score", max_instances=1)
        self.sched.add_job(self._daily_brief, trigger="cron", hour=0, minute=30, id="daily_brief")
        self.sched.start()
        logger.info("Scheduler started with %s connectors + %s agents", len(self.connectors), len(self.agents))

    def stop(self):
        if self.sched.running:
            self.sched.shutdown(wait=False)

    async def _run(self, name: str, connector):
        try:
            signals = await connector.run()
            if not signals:
                return

            new_items = []
            async with self.db_factory() as db:
                for raw in signals:
                    item = await self.engine.process_signal(raw, db)
                    if item:
                        new_items.append(item)
                        await self.alerts.evaluate(item, db)
                await db.commit()

            for item in new_items:
                await self.redis.publish(
                    "goe:live_signals",
                    json.dumps({"type": "NEW_SIGNAL", "data": item.to_ws_dict()}),
                )
            if new_items:
                logger.info("%s processed %s new signals", name, len(new_items))
        except Exception:
            logger.exception("Connector %s failed during scheduled execution", name)

    async def _daily_brief(self):
        from ..core.analyst.daily_brief import DailyBriefGenerator

        async with self.db_factory() as db:
            generator = DailyBriefGenerator(self.redis, self.engine._llm)
            brief = await generator.generate(db)
            await db.commit()
            return brief

    async def _risk_score(self):
        from ..core.india.risk_score import compute_india_risk_score

        async with self.db_factory() as db:
            await compute_india_risk_score(db, self.redis)

    async def force_run(self, connector_name: str):
        connector = self.connectors.get(connector_name)
        if connector is None:
            connector = next(
                (candidate for name, candidate in self.connectors.items() if name.lower() == connector_name.lower()),
                None,
            )
        if connector is None:
            raise KeyError(f"Unknown connector: {connector_name}")
        await self.redis.delete(f"goe:last_fetch:{connector.SOURCE_NAME}")
        await self._run(connector.SOURCE_NAME, connector)

    async def _run_agent(self, agent):
        """Identical to _run — agents produce the same std_signal format."""
        try:
            signals = await agent.run()
            if not signals:
                return
            new_items = []
            async with self.db_factory() as db:
                for raw in signals:
                    item = await self.engine.process_signal(raw, db)
                    if item:
                        new_items.append(item)
                        await self.alerts.evaluate(item, db)
                await db.commit()
            for item in new_items:
                await self.redis.publish(
                    "goe:live_signals",
                    json.dumps({"type": "NEW_SIGNAL", "data": item.to_ws_dict()}),
                )
            if new_items:
                logger.info("Agent %s processed %s new signals", agent.AGENT_NAME, len(new_items))
        except Exception:
            logger.exception("Agent %s failed during scheduled execution", agent.AGENT_NAME)

    async def start_agent_background_tasks(self):
        """
        Call this from main.py after scheduler.start().
        Starts long-running tasks (WebSocket listeners) in background.
        """
        import asyncio
        wm_agent = next((a for a in self.agents if isinstance(a, WorldMonitorAgent)), None)
        if wm_agent:
            asyncio.create_task(wm_agent.start_ws_listener())
            logger.info("World Monitor WebSocket listener started in background")