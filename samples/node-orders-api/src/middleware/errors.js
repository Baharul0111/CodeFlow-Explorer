/** Turn thrown errors into tidy JSON, so callers never see a stack trace. */
function errorHandler(error, req, res, next) {
  if (res.headersSent) {
    next(error);
    return;
  }
  const status = error.status || 500;
  res.status(status).json({ error: error.publicMessage || "Something went wrong" });
}

class HttpError extends Error {
  constructor(status, publicMessage) {
    super(publicMessage);
    this.status = status;
    this.publicMessage = publicMessage;
  }
}

module.exports = { errorHandler, HttpError };
