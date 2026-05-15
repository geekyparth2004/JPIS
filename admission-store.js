const fs = require("fs");
const path = require("path");

const DATA_DIR = path.join(__dirname, "data");
const ADMISSIONS_JSONL_FILE = path.join(DATA_DIR, "admission-leads.jsonl");
const ADMISSIONS_CSV_FILE = path.join(DATA_DIR, "admission-leads.csv");
const CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4";

let writeQueue = Promise.resolve();
let schemaInitPromise = null;

function collapseWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function limitText(value, maxLength) {
  return collapseWhitespace(value).slice(0, maxLength);
}

function normalizeEnvValue(value) {
  return String(value || "").trim().replace(/^['"]|['"]$/g, "");
}

function isConfiguredValue(value) {
  const normalizedValue = normalizeEnvValue(value);
  return Boolean(normalizedValue && !/^replace_with_/i.test(normalizedValue) && normalizedValue !== "your_cloudflare_account_id");
}

function getEnvValue(names) {
  for (const name of names) {
    const value = normalizeEnvValue(process.env[name]);
    if (isConfiguredValue(value)) {
      return value;
    }
  }
  return "";
}

function getCloudflareD1Config() {
  const apiToken = getEnvValue(["CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"]);
  const accountId = getEnvValue(["CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID", "R2_ACCOUNT_ID"]);
  const databaseId = getEnvValue(["CLOUDFLARE_D1_DATABASE_ID", "CF_D1_DATABASE_ID", "D1_DATABASE_ID"]);

  if (!apiToken || !accountId || !databaseId) {
    return null;
  }

  return { apiToken, accountId, databaseId };
}

function buildAdmissionId() {
  const randomPart = Math.random().toString(36).slice(2, 8).toUpperCase();
  return `ADM-${Date.now()}-${randomPart}`;
}

function parseAdmissionPayload(payload) {
  const record = {
    studentName: limitText(payload?.studentName, 120),
    dateOfBirth: limitText(payload?.dateOfBirth, 30),
    gradeApplyingFor: limitText(payload?.gradeApplyingFor, 60),
    gender: limitText(payload?.gender, 20),
    fatherName: limitText(payload?.fatherName, 120),
    motherName: limitText(payload?.motherName, 120),
    contactNumber: limitText(payload?.contactNumber, 30),
    emailAddress: limitText(payload?.emailAddress, 160).toLowerCase(),
    lastSchoolAttended: limitText(payload?.lastSchoolAttended, 160),
    medicalConditions: limitText(payload?.medicalConditions, 1000),
    declarationAccepted: Boolean(payload?.declarationAccepted)
  };

  const errors = [];
  const requiredFields = [
    ["studentName", "Student name is required."],
    ["dateOfBirth", "Date of birth is required."],
    ["gradeApplyingFor", "Grade is required."],
    ["gender", "Gender is required."],
    ["fatherName", "Father's name is required."],
    ["motherName", "Mother's name is required."],
    ["contactNumber", "Contact number is required."],
    ["emailAddress", "Email address is required."]
  ];

  for (const [fieldName, message] of requiredFields) {
    if (!record[fieldName]) {
      errors.push(message);
    }
  }

  const phoneDigits = record.contactNumber.replace(/\D/g, "");
  if (record.contactNumber && (phoneDigits.length < 10 || phoneDigits.length > 15)) {
    errors.push("Contact number must contain 10 to 15 digits.");
  }

  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (record.emailAddress && !emailPattern.test(record.emailAddress)) {
    errors.push("Please enter a valid email address.");
  }

  if (!record.declarationAccepted) {
    errors.push("Please accept the declaration before submitting.");
  }

  return { errors, record };
}

function csvEscape(value) {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, "\"\"")}"`;
}

async function executeD1Query(config, sql, params = []) {
  const response = await fetch(
    `${CLOUDFLARE_API_BASE_URL}/accounts/${config.accountId}/d1/database/${config.databaseId}/query`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${config.apiToken}`
      },
      body: JSON.stringify({
        sql,
        params
      })
    }
  );

  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.success === false || Array.isArray(data?.errors) && data.errors.length > 0) {
    const detail =
      data?.errors?.[0]?.message ||
      data?.messages?.[0]?.message ||
      data?.result?.find?.((entry) => entry?.success === false)?.error ||
      "Cloudflare D1 query failed.";
    throw new Error(detail);
  }

  return data;
}

async function ensureD1Schema(config) {
  if (!schemaInitPromise) {
    schemaInitPromise = executeD1Query(
      config,
      `
      CREATE TABLE IF NOT EXISTS admission_leads (
        admission_id TEXT PRIMARY KEY,
        submitted_at TEXT NOT NULL,
        student_name TEXT NOT NULL,
        date_of_birth TEXT NOT NULL,
        grade_applying_for TEXT NOT NULL,
        gender TEXT NOT NULL,
        father_name TEXT NOT NULL,
        mother_name TEXT NOT NULL,
        contact_number TEXT NOT NULL,
        email_address TEXT NOT NULL,
        last_school_attended TEXT,
        medical_conditions TEXT,
        declaration_accepted INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'website'
      );
      CREATE INDEX IF NOT EXISTS idx_admission_leads_submitted_at
      ON admission_leads (submitted_at DESC);
      CREATE INDEX IF NOT EXISTS idx_admission_leads_contact_number
      ON admission_leads (contact_number);
      CREATE INDEX IF NOT EXISTS idx_admission_leads_email_address
      ON admission_leads (email_address);
      `
    ).catch((error) => {
      schemaInitPromise = null;
      throw error;
    });
  }

  return schemaInitPromise;
}

async function saveAdmissionToD1(record) {
  const config = getCloudflareD1Config();
  if (!config) {
    return false;
  }

  await ensureD1Schema(config);
  await executeD1Query(
    config,
    `
    INSERT INTO admission_leads (
      admission_id,
      submitted_at,
      student_name,
      date_of_birth,
      grade_applying_for,
      gender,
      father_name,
      mother_name,
      contact_number,
      email_address,
      last_school_attended,
      medical_conditions,
      declaration_accepted,
      source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    `,
    [
      record.admissionId,
      record.submittedAt,
      record.studentName,
      record.dateOfBirth,
      record.gradeApplyingFor,
      record.gender,
      record.fatherName,
      record.motherName,
      record.contactNumber,
      record.emailAddress,
      record.lastSchoolAttended,
      record.medicalConditions,
      record.declarationAccepted ? "1" : "0",
      "website"
    ]
  );

  return true;
}

async function appendAdmissionRecord(record) {
  await fs.promises.mkdir(DATA_DIR, { recursive: true });

  const csvHeader =
    "admissionId,submittedAt,studentName,dateOfBirth,gradeApplyingFor,gender,fatherName,motherName,contactNumber,emailAddress,lastSchoolAttended,medicalConditions\n";

  try {
    await fs.promises.access(ADMISSIONS_CSV_FILE);
  } catch {
    await fs.promises.writeFile(ADMISSIONS_CSV_FILE, csvHeader, "utf8");
  }

  const csvRow = [
    record.admissionId,
    record.submittedAt,
    record.studentName,
    record.dateOfBirth,
    record.gradeApplyingFor,
    record.gender,
    record.fatherName,
    record.motherName,
    record.contactNumber,
    record.emailAddress,
    record.lastSchoolAttended,
    record.medicalConditions
  ]
    .map(csvEscape)
    .join(",") + "\n";

  await fs.promises.appendFile(ADMISSIONS_JSONL_FILE, `${JSON.stringify(record)}\n`, "utf8");
  await fs.promises.appendFile(ADMISSIONS_CSV_FILE, csvRow, "utf8");
}

function saveAdmission(payload) {
  const { errors, record } = parseAdmissionPayload(payload);
  if (errors.length > 0) {
    const error = new Error("Invalid admission payload.");
    error.statusCode = 400;
    error.details = errors;
    throw error;
  }

  const savedRecord = {
    admissionId: buildAdmissionId(),
    submittedAt: new Date().toISOString(),
    ...record
  };

  const d1Config = getCloudflareD1Config();
  if (d1Config) {
    return saveAdmissionToD1(savedRecord).then(() => savedRecord);
  }

  writeQueue = writeQueue
    .catch(() => {})
    .then(() => appendAdmissionRecord(savedRecord));
  return writeQueue.then(() => savedRecord);
}

module.exports = {
  ADMISSIONS_CSV_FILE,
  ADMISSIONS_JSONL_FILE,
  DATA_DIR,
  saveAdmission
};
