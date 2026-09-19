# Changelog

All notable decisions and changes to this project are recorded here.
Per the execution plan: Friday-gate decisions and any change to a frozen
contract (`docs/CONTRACTS.md`) are joint decisions and must be logged here.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- 2026-09-19 — Initial repository scaffold: `.env.example`, `scripts/`
  (setup / credential-check / teardown), `src/evtol/` package skeleton
  (config, Token Factory permit-reasoner wrapper, event-bus topic
  constants), `docs/SETUP.md` manual-steps guide, `docs/CONTRACTS.md`
  day-1 freeze draft, CI workflow, Apache-2.0 license, FEEDBACK.md.

### Decisions

- 2026-09-19 — Cosmos 3 generation model resolved to the `nvidia/Cosmos3-*`
  HF family (`Cosmos3-Super` for generation sweeps, `Cosmos3-Edge` for the
  Orin monitor target). `nvidia/Cosmos-Reason2-2B` confirmed as a
  *separate* gated repo (the GR00T N1.7 backbone the plan misses).
