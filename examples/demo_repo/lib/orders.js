'use strict';

async function readOrder(body) {
  const parsed = JSON.parse(body);
  return parsed.order;
}

module.exports = { readOrder };
