const jwt = require("jsonwebtoken");

function resolveRole(token, secret) {
  if (!token) {
    return { role: "OBSERVER", authenticated: false };
  }

  try {
    const decoded = jwt.verify(token, secret);
    return {
      role: decoded.role || "ANALYST",
      authenticated: true,
      subject: decoded.sub || null,
    };
  } catch {
    return { role: "OBSERVER", authenticated: false };
  }
}

module.exports = { resolveRole };
