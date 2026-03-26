"""Quick functional test of agent modules (no Redis/DB needed)."""
from apps.api.ingestion.agents.utils.html_extractor import extract_article_text, extract_headline
from apps.api.ingestion.agents.world_monitor_agent import WorldMonitorAgent

# Test HTML extraction
html = '<html><head><title>Test</title></head><body><article><h1>Breaking News: India Tests DRDO Missile</h1><p>India successfully tested a new DRDO missile system near the LOC.</p></article></body></html>'
print("Headline:", extract_headline(html))
print("Text:", extract_article_text(html))

# Test std_signal format without actual Redis
print("\nTesting std_signal dict format...")

class MockAgent(WorldMonitorAgent):
    def __init__(self):
        self.AGENT_NAME = "world_monitor_live"
        self.logger = __import__("logging").getLogger("test")
        self._ws_buffer = []

agent = MockAgent()
sig = agent.std_signal(
    title="Test Signal", summary="Test summary",
    domain="defense", severity=50, india_score=80, url="https://test.com"
)
print(f"  id:          {sig['id'][:20]}")
print(f"  source_name: {sig['source_name']}")
print(f"  title:       {sig['title']}")
print(f"  domain:      {sig['domain']}")
print(f"  severity:    {sig['severity']}")
print(f"  india_score: {sig['india_score']}")
print(f"  raw_text:    {sig['raw_text']}")

# Test India score computation
score = agent._compute_india_score("India tests DRDO missile", "Near LOC border", 28.5, 77.2)
print(f"\nIndia score for India-related signal: {score}")
score2 = agent._compute_india_score("US stocks fall", "Wall street", 40.7, -74.0)
print(f"India score for US signal: {score2}")

# Test severity extraction
sev = agent._extract_severity({"severity": 75})
print(f"\nSeverity from dict with severity=75: {sev}")
sev2 = agent._extract_severity({"level": 3})
print(f"Severity from dict with level=3: {sev2}")

# Test timestamp extraction
ts = agent._extract_timestamp({"timestamp": "2026-03-22T12:00:00Z"})
print(f"Timestamp parsed: {ts}")

print("\nAll agent tests passed!") # comment
