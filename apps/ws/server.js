const WebSocket = require("ws");
const Redis = require("ioredis");
const { resolveRole } = require("./auth");

const WS_PORT = process.env.WS_PORT || 8001;
const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";
const JWT_SECRET = process.env.API_SECRET_KEY || "dev-secret";

const subscriber = new Redis(REDIS_URL);
const redis = new Redis(REDIS_URL);
const wss = new WebSocket.Server({ port: WS_PORT });
const clients = new Map();

const CHANNELS = [
  "goe:live_signals",
  "goe:alerts",
  "goe:market_update",
  "goe:daily_brief_ready",
  "goe:ais_vessels",
];

subscriber.subscribe(...CHANNELS, (err, count) => {
  if (err) {
    console.error("Redis subscribe failed:", err);
    return;
  }
  console.log(`WebSocket server subscribed to ${count} Redis channels`);
});

// ── AISStream Maritime Vessel Tracking ────────────────────────────────────
const AISSTREAM_KEY = process.env.AISSTREAM_API_KEY || "";
let aisWs = null;
let aisReconnectTimer = null;

const STRATEGIC_BOUNDING_BOXES = [
  // Red Sea / Suez / Gulf of Aden
  [[10.0, 30.0], [30.0, 50.0]],
  // Persian Gulf / Strait of Hormuz
  [[22.0, 48.0], [30.0, 60.0]],
  // Strait of Malacca / South China Sea
  [[0.0, 95.0], [22.0, 120.0]],
  // Eastern Mediterranean / Levant
  [[30.0, 25.0], [42.0, 42.0]],
  // Indian Ocean shipping lanes
  [[-10.0, 50.0], [20.0, 80.0]],
];

function connectAISStream() {
  if (!AISSTREAM_KEY) {
    console.log("AISStream: no API key configured, skipping.");
    return;
  }

  aisWs = new WebSocket("wss://stream.aisstream.io/v0/stream");

  aisWs.on("open", () => {
    console.log("AISStream: connected");
    aisWs.send(JSON.stringify({
      APIKey: AISSTREAM_KEY,
      BoundingBoxes: STRATEGIC_BOUNDING_BOXES,
      FilterMessageTypes: ["PositionReport", "ShipStaticData"],
    }));
  });

  aisWs.on("message", async (data) => {
    try {
      const msg = JSON.parse(data.toString());
      const msgType = msg.MessageType;
      const meta = msg.MetaData || {};

      // Build a normalized vessel signal
      const vessel = {
        mmsi:       meta.MMSI || "",
        ship_name:  meta.ShipName || "",
        lat:        meta.latitude || 0,
        lon:        meta.longitude || 0,
        speed:      meta.ShipSpeed || 0,
        heading:    meta.TrueHeading || 0,
        msg_type:   msgType,
        time_utc:   meta.time_utc || new Date().toISOString(),
      };

      // Add static data if present
      if (msgType === "ShipStaticData") {
        const sd = msg.Message?.ShipStaticData || {};
        vessel.ship_type    = sd.Type || 0;
        vessel.destination  = sd.Destination || "";
        vessel.callsign     = sd.CallSign || "";
        vessel.length       = sd.Dimension?.A + sd.Dimension?.B || 0;

        // Flag naval vessels (ship_type 35 = military, 36 = sailing, etc.)
        vessel.is_naval = vessel.ship_type === 35;
      }

      // Publish raw vessel position to Redis for Python connectors to consume
      await redis.setex(
        `goe:ais_vessel:${vessel.mmsi}`,
        300,  // 5 min TTL — vessel positions stale after this
        JSON.stringify(vessel)
      );

      // Publish to AIS channel for WebSocket fan-out to frontend clients
      await redis.publish(
        "goe:ais_vessels",
        JSON.stringify({ type: "AIS_POSITION", data: vessel })
      );

    } catch (err) {
      // Silently ignore malformed AIS messages
    }
  });

  aisWs.on("close", (code, reason) => {
    console.log(`AISStream: disconnected (${code}). Reconnecting in 30s...`);
    aisWs = null;
    if (aisReconnectTimer) clearTimeout(aisReconnectTimer);
    aisReconnectTimer = setTimeout(connectAISStream, 30000);
  });

  aisWs.on("error", (err) => {
    console.error("AISStream error:", err.message);
    // close handler will trigger reconnect
  });
}

// Start AISStream connection
connectAISStream();


subscriber.on("message", (channel, message) => {
  let payload;
  try {
    payload = JSON.parse(message);
  } catch {
    payload = { type: "RAW_MESSAGE", data: message };
  }

  for (const [ws, meta] of clients.entries()) {
    if (ws.readyState !== WebSocket.OPEN) {
      continue;
    }
    if (channel === "goe:alerts") {
      const level = payload.data && payload.data.level;
      if (meta.role === "OBSERVER" && level === "ROUTINE") {
        continue;
      }
    }
    ws.send(JSON.stringify({ channel, ...payload, ts: Date.now() }));
  }
});

wss.on("connection", (ws, req) => {
  const url = new URL(req.url, "http://localhost");
  const token = url.searchParams.get("token") || "";
  const meta = resolveRole(token, JWT_SECRET);
  meta.connectedAt = Date.now();
  clients.set(ws, meta);
  console.log(`Client connected (${meta.role}). Total: ${clients.size}`);

  sendInitialSnapshot(ws).catch(console.error);

  ws.on("close", () => {
    clients.delete(ws);
    console.log(`Client disconnected. Total: ${clients.size}`);
  });

  const ping = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.ping();
    } else {
      clearInterval(ping);
    }
  }, 30000);
});

async function sendInitialSnapshot(ws) {
  const [signalsToday, indiaRisk, marketRaw, lastQuake] = await Promise.all([
    redis.get("goe:stats:signals_today"),
    redis.get("goe:india_risk_score_full"),
    redis.get("goe:market_snapshot"),
    redis.get("goe:cache:usgs_earthquakes"),
  ]);

  ws.send(
    JSON.stringify({
      type: "INITIAL_SNAPSHOT",
      data: {
        signals_today: parseInt(signalsToday || "0", 10),
        india_risk: indiaRisk ? JSON.parse(indiaRisk) : null,
        market_snapshot: marketRaw ? JSON.parse(marketRaw) : null,
        seismic_count: lastQuake ? JSON.parse(lastQuake).length : 0,
      },
    })
  );
}

console.log(`GOE WebSocket server running on port ${WS_PORT}`);
