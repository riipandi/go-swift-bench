// Entry k6: satu invokasi per titik ukur. Parameter lewat -e:
//   SCENARIO=s1..s9 | s8 ; MODE=vus|rate|warmup ; BASE_URL ; SEED
//   vus   : VUS, RAMP_S, STEADY_S    (constant-vus, closed-loop; submetric {phase:steady} setelah RAMP_S)
//   rate  : RATE, DURATION_S, PRE_VUS, MAX_VUS  (constant-arrival-rate, open-loop)
//   warmup: VUS, DURATION_S          (tidak dihitung)
import { SharedArray } from 'k6/data';
import { Gauge } from 'k6/metrics';
import { mulberry32 } from './lib/rng.js';
import * as s1 from './scenarios/s1.js';
import * as s2 from './scenarios/s2.js';
import * as s3 from './scenarios/s3.js';
import * as s4 from './scenarios/s4.js';
import * as s5 from './scenarios/s5.js';
import * as s6 from './scenarios/s6.js';
import * as s7 from './scenarios/s7.js';
import * as s8 from './scenarios/s8.js';
import * as s9 from './scenarios/s9.js';

const SCENARIOS = { s1, s2, s3, s4, s5, s6, s7, s8, s9 };
const SCEN = __ENV.SCENARIO || 's1';
const MODE = __ENV.MODE || 'vus';
const BASE = __ENV.BASE_URL || 'http://go-app:8080';
const SEED = parseInt(__ENV.SEED || '20261013');
const RAMP_S = parseInt(__ENV.RAMP_S || '10');
const num = (k, d) => parseInt(__ENV[k] || String(d));

const users = new SharedArray('users', () => JSON.parse(open('/loadtest/data/user_ids.json')));
const orders = new SharedArray('orders', () => JSON.parse(open('/loadtest/data/order_ids.json')));
const pending = new SharedArray('pending', () => JSON.parse(open('/loadtest/data/pending_order_ids.json')));

const startGauge = new Gauge('bench_test_start_ms');

function buildScenarios() {
  if (MODE === 'warmup') {
    return { warmup: { executor: 'constant-vus', vus: num('VUS', 32), duration: num('DURATION_S', 20) + 's' } };
  }
  if (MODE === 'rate') {
    return { steady: { executor: 'constant-arrival-rate', rate: num('RATE', 100), timeUnit: '1s',
      duration: num('DURATION_S', 60) + 's', preAllocatedVUs: num('PRE_VUS', 100), maxVUs: num('MAX_VUS', 1000) } };
  }
  return { steady: { executor: 'constant-vus', vus: num('VUS', 16), duration: (RAMP_S + num('STEADY_S', 30)) + 's' } };
}

export const options = {
  scenarios: buildScenarios(),
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)', 'p(99.9)'],
  thresholds: {
    // submetric steady-only (selalu lolos; hanya agar muncul di --summary-export)
    'http_req_duration{phase:steady}': ['max>=0'],
    'http_req_failed{phase:steady}': ['rate>=0'],
    'http_reqs{phase:steady}': ['count>=0'],
  },
};

export function setup() {
  const t0 = Date.now();
  startGauge.add(t0);
  return { t0: t0 };
}

let rng = null;
export default function (data) {
  if (rng === null) rng = mulberry32(SEED + __VU * 7919);
  let phase = 'steady';
  if (MODE === 'warmup') phase = 'warmup';
  else if (MODE === 'vus' && Date.now() - data.t0 < RAMP_S * 1000) phase = 'ramp';
  SCENARIOS[SCEN].iteration({ base: BASE, rng: rng, phase: phase, data: { users: users, orders: orders, pending: pending } });
}
