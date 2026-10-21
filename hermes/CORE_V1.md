# Hermes + AI Quant Terminal Core V1

## Role

Hermes is an orchestration, research, and diagnostic layer.

Hermes must not become the bar-by-bar portfolio state machine.

## First command

For a single machine-readable context bundle use `python run.py snapshot --mode paper`.

Always inspect capabilities before assuming an integration exists:

```bash
python run.py capabilities
```

Important distinction:

```text
python_package_detected = true
```

does not mean:

```text
enabled = true
```

OpenBB/Qlib/Freqtrade/Nautilus remain disabled until their adapter is implemented and tested.

## Safe research loop

```text
Hypothesis
  -> acceptance criteria
  -> deterministic tool call
  -> metrics
  -> OOS / walk-forward / IC where relevant
  -> journal
  -> PASS / FAIL
```

## Do not

- invent an integration that is not enabled
- directly edit portfolio state files to simulate a successful trade
- call a real-money broker
- promote a strategy because train performance is highest
- change several strategy assumptions in one experiment without recording them
