// S5: GET /users/{id}?include=orders (eager loading, 2 query, sampai ~250 baris)
import { get } from '../lib/req.js';
import { pick } from '../lib/rng.js';
export function iteration(ctx) { get(ctx, '/users/' + pick(ctx.rng, ctx.data.users) + '?include=orders', 'GET /users/:id?include=orders'); }
