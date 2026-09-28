FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY scripts/smoke_card_1050602.py /app/scripts/smoke_card_1050602.py
COPY scripts/smoke_voice_stack.py /app/scripts/smoke_voice_stack.py
COPY contracts/examples/scenario-1050602.json /app/contracts/examples/scenario-1050602.json
