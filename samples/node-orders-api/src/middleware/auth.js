const VALID_KEYS = (process.env.API_KEYS || "demo-key").split(",");

/** Refuse any request that does not carry a known API key. */
function requireApiKey(req, res, next) {
  const key = req.header("x-api-key");
  if (!key || !VALID_KEYS.includes(key)) {
    res.status(401).json({ error: "Missing or unknown API key" });
    return;
  }
  req.apiKey = key;
  next();
}

module.exports = { requireApiKey };
