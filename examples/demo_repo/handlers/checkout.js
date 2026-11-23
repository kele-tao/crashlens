'use strict';

const { readOrder } = require('../lib/orders');

async function handleCheckout(body) {
  const order = await readOrder(body);
  const skus = order.items.map((item) => item.sku);
  return skus.join(',');
}

module.exports = { handleCheckout };
