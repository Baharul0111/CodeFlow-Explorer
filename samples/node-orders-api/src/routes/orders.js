const express = require("express");
const service = require("../services/orders-service");
const repo = require("../db/orders-repo");

const ordersRouter = express.Router();

ordersRouter.get("/", async (req, res, next) => {
  try {
    res.json(await repo.listOrders(req.query.status));
  } catch (error) {
    next(error);
  }
});

ordersRouter.get("/:id", async (req, res, next) => {
  try {
    res.json(await service.readOrder(Number(req.params.id)));
  } catch (error) {
    next(error);
  }
});

ordersRouter.post("/", async (req, res, next) => {
  try {
    const order = await service.placeOrder(req.body);
    res.status(201).json(order);
  } catch (error) {
    next(error);
  }
});

ordersRouter.post("/:id/status", async (req, res, next) => {
  try {
    res.json(await service.changeStatus(Number(req.params.id), req.body.status));
  } catch (error) {
    next(error);
  }
});

module.exports = { ordersRouter };
