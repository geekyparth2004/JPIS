const http = require("http");
const fs = require("fs");
const path = require("path");
const { loadServerConfig, isApiKeyConfigured, RUNTIME_CONFIG_FILE } = require("./config");

const HOST = process.env.HOST || "0.0.0.0";
const PORT = Number(process.env.PORT || 3000);
const BASE_DIR = __dirname;

const SCHOOL_CONTEXT = `
You are the parent-support AI assistant for J.P. International School.
Answer in a warm, clear, concise way.
Focus on helping parents with admissions, academics, facilities, fees, timings, contact details, and campus visits.
If exact information is not available, say that politely and ask the parent to contact the school office.
Do not invent fee amounts, policies, dates, or legal claims.
Keep answers short and practical.
`.trim();
loadServerConfig();

function buildInput(history, message) {
  const items = [
    {
      role: "developer",
      content: [{ type: "input_text", text: SCHOOL_CONTEXT }]
    }
  ];

  const recentHistory = Array.isArray(history) ? history.slice(-8) : [];
  for (const entry of recentHistory) {
    if (!entry || typeof entry !== "object") continue;
    const text = String(entry.text || "").trim();
    const sender = entry.sender;
    if (!text || (sender !== "user" && sender !== "assistant")) continue;
    items.push({
      role: sender,
      content: [{ type: "input_text", text }]
    });
  }

  items.push({
    role: "user",
    content: [{ type: "input_text", text: String(message || "").trim() }]
  });

  return items;
}

function extractReplyText(data) {
  if (typeof data?.output_text === "string" && data.output_text.trim()) {
    return data.output_text.trim();
  }

  const outputItems = Array.isArray(data?.output) ? data.output : [];
  for (const item of outputItems) {
    const contents = Array.isArray(item?.content) ? item.content : [];
    for (const content of contents) {
      if (typeof content?.text === "string" && content.text.trim()) {
        return content.text.trim();
      }
    }
  }

  return "";
}

function sendJson(res, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Access-Control-Allow-Origin": "*"
  });
  res.end(body);
}

function getContentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const types = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8"
  };
  return types[ext] || "application/octet-stream";
}

function serveFile(req, res, relativePath) {
  const targetPath = path.resolve(BASE_DIR, relativePath);
  if (!targetPath.startsWith(BASE_DIR)) {
    sendJson(res, 403, { error: "Forbidden" });
    return;
  }

  const blockedFiles = new Set([
    ".env",
    ".env.local",
    ".env.development",
    ".env.example",
    "config.js",
    "server.js",
    "server.py",
    RUNTIME_CONFIG_FILE,
    "runtime-config.json",
    "runtime-config.example.json"
  ]);
  const baseName = path.basename(targetPath);
  if (blockedFiles.has(baseName)) {
    sendJson(res, 403, { error: "Forbidden" });
    return;
  }

  fs.readFile(targetPath, (error, data) => {
    if (error) {
      if (error.code === "ENOENT") {
        sendJson(res, 404, { error: "File not found" });
        return;
      }

      sendJson(res, 500, { error: "Unable to read file" });
      return;
    }

    res.writeHead(200, { "Content-Type": getContentType(targetPath) });
    res.end(data);
  });
}

async function handleChat(req, res) {
  const apiKey = (process.env.OPENAI_API_KEY || "").trim();
  if (!isApiKeyConfigured(apiKey)) {
    sendJson(res, 500, { error: "Missing OPENAI_API_KEY on the server." });
    return;
  }

  let rawBody = "";
  for await (const chunk of req) {
    rawBody += chunk;
  }

  let payload;
  try {
    payload = JSON.parse(rawBody || "{}");
  } catch {
    sendJson(res, 400, { error: "Invalid JSON body." });
    return;
  }

  const message = String(payload.message || "").trim();
  const history = payload.history;
  if (!message) {
    sendJson(res, 400, { error: "Message is required." });
    return;
  }

  try {
    const response = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        input: buildInput(history, message)
      })
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      sendJson(res, response.status, {
        error: data.error?.message || "OpenAI request failed."
      });
      return;
    }

    sendJson(res, 200, {
      reply: extractReplyText(data) || "I am here to help with school-related questions."
    });
  } catch {
    sendJson(res, 500, { error: "Server error while contacting OpenAI." });
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    });
    res.end();
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/health") {
    sendJson(res, 200, {
      ok: true,
      configured: isApiKeyConfigured((process.env.OPENAI_API_KEY || "").trim())
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/api/chat") {
    await handleChat(req, res);
    return;
  }

  if (req.method === "GET" && url.pathname === "/") {
    serveFile(req, res, "index.html");
    return;
  }

  if (req.method === "GET") {
    serveFile(req, res, decodeURIComponent(url.pathname.replace(/^\/+/, "")));
    return;
  }

  sendJson(res, 405, { error: "Method not allowed." });
});

server.listen(PORT, HOST, () => {
  console.log(`JPIS app server running at http://${HOST}:${PORT}`);
});
