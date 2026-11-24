# Wave 4A conversational evaluation

Independent customer conversations for the local `POST /api/chat` contract. The application and UI stay with the implementation work. This directory does not start a model and does not read the reserved held-out split.

## What a run sends

Each case is a customer-only transcript. For turn N the runner posts:

- `request_id`: a new UUID
- `conversation_id`: one UUID for the whole case
- `messages`: the customer turns so far, alternating with the assistant replies actually returned earlier in that case

Messages contain only `role` and `text`. Grading notes, acceptable phrasings, and this folder's review fields are not posted. If a turn has no assistant reply, later turns in that case are not sent.

## What a run records

The packet stores the actual reply, the HTTP or transport error, and end-to-end client latency. Server `metrics.elapsed_ms` is stored separately when the response includes it. Turns are summarized in two buckets, `conversation` and `automotive`.

Automatic observations are facts: a non-empty reply, Cyrillic text, a currency or price amount, a high-precision booking confirmation, and a high-precision opening-hours claim. They are not a quality score. A Russian-speaking reviewer judges understanding, reasonable questions, and the concrete failures written on each turn. Any natural Russian phrasing is acceptable. A greeting is not required.

No case contains a verified price, opening hours, availability, stock level, or completed booking.

## Commands

Harness, local stub only:

```bash
python3 benchmark/wave4a/test_harness.py
```

After the chat server is already listening on port 8766:

```bash
python3 benchmark/wave4a/run_eval.py --base-url http://127.0.0.1:8766
```

The runner does not start the server. The packet is written to `benchmark/wave4a/results/run.json`. Paths are resolved from this file, so the command can use an absolute path to `run_eval.py`. The default label is `evaluation`. A label that starts with `harness` marks the packet as a harness run.
