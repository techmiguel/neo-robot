# Contributing to NEO

Thanks for your interest. NEO is a hobby project, so issues with clear steps to reproduce
and small, focused pull requests are the easiest to review.

## Before you open a pull request

1. Run the tests that cover what you changed:
   ```bash
   cd servidor && pip install -e ".[dev]" && pytest
   cd firmware/tools && pytest
   cd firmware && pio run -e esp32dev
   ```
   `tests/test_ws_echo.py` is an integration test; it only runs when `WS_URL` points to a
   server started with `WS_MODO=echo`.
2. If you change latency, recognition or audio behaviour, say how you measured it. The
   validation panel (`python -m src.benchmark.panel`, see `servidor/benchmark/README.md`)
   produces a report you can attach.
3. Never commit secrets: `servidor/.env` and `firmware/src/config_local.h` are gitignored.
   Do not commit voice recordings of people without their consent.

## Conventions

- **Language:** the code comments, docs and experiment reports are in Spanish; the README
  is in English. Either language is fine in issues and pull requests.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) in English,
  imperative mood (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`), one logical change each.
- **Firmware:** one class per peripheral with its own `.h`/`.cpp`; no `delay()` in the main
  loop (state machines or FreeRTOS tasks instead); handle I2S and WiFi errors explicitly.
- **Server:** one module per responsibility (STT, LLM, TTS, each command handler), each with
  tests in `servidor/tests/`; log the latency of every pipeline stage.
- **New voice commands** are a `Handler` subclass in `servidor/src/commands/` plus its
  keywords in `router.py`. The firmware does not change.

## Reporting a bug

Include the board, the server profile (`local` or `nube`), the relevant lines of the serial
log (`pio device monitor -e esp32dev`) and of the server log.
