import os

# Replay never calls a model; keep tracing off anyway, as the test suite does.
os.environ["OTEL_TRACING_ENABLED"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
