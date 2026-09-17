const express = require("express");
const customers = require("../db/customers-repo");
const { HttpError } = require("../middleware/errors");

const customersRouter = express.Router();

customersRouter.get("/:email", async (req, res, next) => {
  try {
    const customer = await customers.findByEmail(req.params.email);
    if (!customer) {
      throw new HttpError(404, "No customer with that email");
    }
    res.json(customer);
  } catch (error) {
    next(error);
  }
});

module.exports = { customersRouter };
