const fs = require("fs");
const path = require("path");

const BASE_DIR = __dirname;
const ENV_FILES = [".env", ".env.local", ".env.development"];
const RUNTIME_CONFIG_FILE = "runtime-config.local.json";

function applyEntries(entries) {
  for (const [rawKey, rawValue] of entries) {
    const key = String(rawKey || "").trim();
    if (!key || process.env[key]) {
      continue;
    }

    const value = String(rawValue || "").trim().replace(/^['"]|['"]$/g, "");
    process.env[key] = value;
  }
}

function loadEnvFiles() {
  for (const fileName of ENV_FILES) {
    const envPath = path.join(BASE_DIR, fileName);
    if (!fs.existsSync(envPath)) {
      continue;
    }

    const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
    const entries = [];
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) {
        continue;
      }

      const [key, ...rest] = line.split("=");
      entries.push([key, rest.join("=")]);
    }

    applyEntries(entries);
  }
}

function loadRuntimeConfig() {
  const configPath = path.join(BASE_DIR, RUNTIME_CONFIG_FILE);
  if (!fs.existsSync(configPath)) {
    return;
  }

  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    if (config && typeof config === "object") {
      applyEntries(Object.entries(config));
    }
  } catch {
    // Ignore invalid runtime config and continue with existing env values.
  }
}

function loadServerConfig() {
  loadEnvFiles();
  loadRuntimeConfig();
}

function isApiKeyConfigured(apiKey) {
  return Boolean(
    apiKey &&
    apiKey.startsWith("sk-") &&
    !apiKey.includes("replace_with_your_new_openai_api_key")
  );
}

module.exports = {
  loadServerConfig,
  isApiKeyConfigured,
  RUNTIME_CONFIG_FILE
};
