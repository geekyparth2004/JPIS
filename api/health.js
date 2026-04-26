const { loadServerConfig, isApiKeyConfigured } = require("../config");

loadServerConfig();

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.status(405).json({ error: "Method not allowed." });
    return;
  }

  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  res.status(200).json({
    ok: true,
    configured: isApiKeyConfigured(apiKey)
  });
};
