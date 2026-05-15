const { saveAdmission } = require("../admission-store");

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed." });
    return;
  }

  try {
    const savedRecord = await saveAdmission(req.body || {});
    res.status(201).json({
      ok: true,
      admissionId: savedRecord.admissionId,
      submittedAt: savedRecord.submittedAt,
      message: "Registration successfully submitted."
    });
  } catch (error) {
    if (error?.statusCode === 400) {
      res.status(400).json({
        error: "Please review the admission form.",
        details: error.details || []
      });
      return;
    }

    res.status(500).json({
      error: "Unable to save the admission form right now."
    });
  }
};
