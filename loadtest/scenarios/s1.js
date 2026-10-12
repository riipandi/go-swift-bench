// S1: GET /bench/json (overhead framework + encode JSON)
import { get } from '../lib/req.js';
export function iteration(ctx) { get(ctx, '/bench/json', 'GET /bench/json'); }
