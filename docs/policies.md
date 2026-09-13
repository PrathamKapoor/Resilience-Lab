# Resilience policies

A resilience policy controls how requests to a dependency are protected:
retries, backoff/jitter, circuit breakers, concurrency limits, and timeouts.

## Policy scope

Policies are scoped to the **destination service**. When the system under test
calls a dependency, the *effective* policy for that dependency governs that
call — including its own circuit-breaker state, concurrency limiter, and retry
accounting. State never leaks across services.

```text
per-service override  →  default/global policy  →  schema defaults
```

## Global/default policy

```yaml
policy:
  retry:
    enabled: true
    max_attempts: 3
  backoff:
    type: exponential
    base: 100ms
    maximum: 5s
    jitter: full
  circuit_breaker:
    threshold: 10
    recovery_window: 15s
  timeout:
    total: 1s
  concurrency:
    limit: 50
```

## Per-service overrides

Optional, keyed by service name. An override may specify only part of a policy;
unspecified fields inherit from the default.

```yaml
policies:
  payment_service:
    retry:
      enabled: true
      max_attempts: 3
    circuit_breaker:
      threshold: 5

  inventory_service:
    retry:
      enabled: false

  shipping:
    retry: null          # disable retry entirely (inherits timeout etc.)
    timeout:
      total: 500ms
```

## Semantics

- A service with no override uses the global policy verbatim.
- Partial overrides deep-merge onto the global policy; explicit values win.
- `retry: null` (or `retry: {enabled: false}`) disables retry for that service.
- Each resolved policy is built into independent runtime state: separate
  `CircuitBreaker`, `ConcurrencyLimiter`, and `Retry` instances per service.
- Resolution is deterministic and recorded in artifacts (`policies.resolved`)
  and in the report's "Service policies" section.

## Backward compatibility

Existing configurations with a single global `policy` (and no `policies` key)
behave exactly as before. In the default single-dependency topology, the
resolver maps the lone `payment_service` to the global policy.