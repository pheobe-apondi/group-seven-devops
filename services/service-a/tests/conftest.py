import os

# Unit tests don't have a Jaeger collector reachable; disable the OTel SDK so
# span export doesn't retry against an unresolvable host during test teardown.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
