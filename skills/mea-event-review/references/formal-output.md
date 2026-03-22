# Formal Output

Before submitting, open and follow this schema exactly:
- `specs/modules/agent_gateway/contracts/news.schema.json`

Prompt contract reference:
- `specs/modules/agent_gateway/contracts/news.prompt.md`

Rules:
- Formal submission is exactly one JSON object.
- Keep the `input_id` from your runtime pack and send it with the submit bridge call.
- Output only JSON. Do not emit markdown fences, prose, side notes, or trailing explanation.
- Submit structured event list only. Do not add `submission_id` or `generated_at_utc`; the system will generate them.
- Each event summary should stay concise.
- Do not emit an `alert` field.
- Direct reminders to `PM` and `RT` are conversation behavior, not a formal submission field.
