// S4: GET /users/{id}/orders?limit=20 (query terindeks + urutan + mapping 20 baris)
import { get } from '../lib/req.js';
import { pick } from '../lib/rng.js';
export function iteration(ctx) { get(ctx, '/users/' + pick(ctx.rng, ctx.data.users) + '/orders?limit=20', 'GET /users/:id/orders'); }
