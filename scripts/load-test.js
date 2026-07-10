import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const SCENARIO = __ENV.SCENARIO || "normal";

// Normal/stress drive the real cross-service flow (gateway -> A -> B -> C -> callback to A).
// Failure hits service-a's lab-only /fail endpoint to produce a known 100% error rate.
const SCENARIOS = {
  normal: { vus: 10, iterations: 500, path: "/service-a/greet-service-b", expectedStatus: 200 },
  stress: { vus: 50, iterations: 2000, path: "/service-a/greet-service-b", expectedStatus: 200 },
  failure: { vus: 10, iterations: 300, path: "/service-a/fail", expectedStatus: 500 },
};

const cfg = SCENARIOS[SCENARIO];
if (!cfg) {
  throw new Error(`Unknown SCENARIO "${SCENARIO}" - expected one of: ${Object.keys(SCENARIOS).join(", ")}`);
}

export const options = {
  scenarios: {
    [SCENARIO]: {
      executor: "shared-iterations",
      vus: cfg.vus,
      iterations: cfg.iterations,
      maxDuration: "3m",
    },
  },
};

export default function () {
  const res = http.get(`${BASE_URL}${cfg.path}`, {
    headers: { "X-Request-ID": `k6-${SCENARIO}-${__VU}-${__ITER}` },
    timeout: "10s",
  });
  check(res, {
    "status matches scenario expectation": (r) => r.status === cfg.expectedStatus,
  });
}
