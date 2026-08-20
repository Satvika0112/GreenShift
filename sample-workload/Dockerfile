# ─────────────────────────────────────────────────────────────────────────────
# GreenShift Sample Workload Dockerfile
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Non-root user
RUN groupadd -r workload && useradd -r -g workload workload

WORKDIR /app

COPY workload.py .

USER workload

ENV JOB_ID=UNKNOWN
ENV TEAM_ID=UNKNOWN
ENV DURATION_SECONDS=60

CMD ["python", "workload.py"]
