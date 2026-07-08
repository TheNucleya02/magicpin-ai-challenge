# magicpin Vera AI Assistant - Submission README

## Briefly
- Approach: I built a deterministic, challenge-aligned composer that produces structured messages with a single CTA and a stable submission contract, while keeping Gemini as an optional enhancement path rather than a dependency.
- Tradeoffs: I prioritized reliability, harness compatibility, and safe output formatting over highly stylized copy, which means the messages are more conservative but easier to validate consistently.
- Additional context that would have helped most: more examples of ideal merchant/customer tone by category, clearer evaluation criteria for what makes a message “high quality,” and richer trigger payloads for edge cases.

## Approach
This repository now centers on a deterministic, challenge-aligned composer that satisfies the submission contract in the brief without depending on an LLM for every turn. The core flow is:

- expose a standard compose() interface that returns body, cta, send_as, suppression_key, and rationale
- keep the FastAPI server compatible with the judge harness endpoints
- use deterministic templates first, then fall back to Gemini only when an API key is present
- keep message bodies URL-safe and single-CTA by construction

## What was cleaned up
- added a direct compose() entry point for the brief’s expected submission contract
- made the server tolerate missing Gemini credentials and still emit safe fallback messages
- added regression tests covering merchant-facing and customer-facing compose behavior
- reduced the chance of malformed or overly promotional outputs by enforcing a single CTA and URL stripping

## Tradeoffs
- Deterministic templates are used as the default path for reliability and speed.
- LLM generation remains available as an enhancement path when the environment has a valid Gemini key.
- This favors correctness and harness compatibility over highly stylized prose.

## Validation
Run:

- python3 -m pytest -q tests/test_bot.py
- python3 -m compileall .
