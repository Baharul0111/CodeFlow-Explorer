const express = require("express");
const { ordersRouter } = require("./routes/orders");
const { customersRouter } = require("./routes/customers");
const { errorHandler } = require("./middleware/errors");
const { requireApiKey } = require("./middleware/auth");
const { runMigrations } = require("./db/migrate");

const app = express();
app.use(express.json());
app.use(requireApiKey);
app.use("/orders", ordersRouter);
app.use("/customers", customersRouter);
app.use(errorHandler);

async function start() {
  await runMigrations();
  const port = process.env.PORT || 3000;
  app.listen(port, () => {
    console.log(`orders api listening on ${port}`);
  });
}

if (require.main === module) {
  start();
}

module.exports = { app, start };
