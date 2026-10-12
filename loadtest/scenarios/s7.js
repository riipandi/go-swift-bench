// S7: PUT /orders/{id} (baca lalu update status + updated_at), id order acak
import { put } from '../lib/req.js';
import { pick } from '../lib/rng.js';
const STATUSES = ['pending', 'paid', 'shipped', 'cancelled'];
export function iteration(ctx) {
  put(ctx, '/orders/' + pick(ctx.rng, ctx.data.orders), 'PUT /orders/:id', { status: pick(ctx.rng, STATUSES) });
}
