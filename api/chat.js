const {
  getOpenAIApiKey,
  getOpenAIAuthErrorMessage,
  loadServerConfig,
  isApiKeyConfigured
} = require("../config");

loadServerConfig();

const SCHOOL_CONTEXT = `
You are the parent-support AI assistant for J.P. International School.
Answer in a warm, clear, concise way.
Focus on helping parents with admissions, academics, facilities, fees, timings, contact details, and campus visits.
If exact information is not available, say that politely and ask the parent to contact the school office.
Do not invent fee amounts, policies, dates, or legal claims.
Keep answers short and practical.
`;

function buildInput(history, message) {
  const items = [
    {
      role: "developer",
      content: SCHOOL_CONTEXT.trim()
    }
  ];

  const recentHistory = Array.isArray(history) ? history.slice(-8) : [];

  for (const entry of recentHistory) {
    if (!entry || !entry.text || !entry.sender) continue;
    items.push({
      role: entry.sender === "user" ? "user" : "assistant",
      content: String(entry.text)
    });
  }

  items.push({
    role: "user",
    content: String(message || "")
  });

  return items;
}

function extractReplyText(data) {
  if (data?.choices?.[0]?.message?.content) {
    return data.choices[0].message.content.trim();
  }
  return "";
}

module.exports = async (req, res) => {
  const apiKey = getOpenAIApiKey();

  if (req.method === "GET") {
    res.status(200).json({
      ok: true,
      configured: isApiKeyConfigured(apiKey)
    });
    return;
  }

  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed." });
    return;
  }

  if (!isApiKeyConfigured(apiKey)) {
    res.status(500).json({ error: "Missing OPENAI_API_KEY on the server." });
    return;
  }

  const { message, history } = req.body || {};
  if (!message || !String(message).trim()) {
    res.status(400).json({ error: "Message is required." });
    return;
  }

  try {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: buildInput(history, message)
      })
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      res.status(response.status).json({
        error: getOpenAIAuthErrorMessage(data.error?.message)
      });
      return;
    }

    res.status(200).json({
      reply: extractReplyText(data) || "I am here to help with school-related questions."
    });
  } catch (error) {
    res.status(500).json({
      error: "Server error while contacting OpenAI."
    });
  }
};
