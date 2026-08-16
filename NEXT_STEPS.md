# Next steps

The project currently has a tested offline decision path and a live, visible
observer. It is not yet a reliable table reader or a complete poker strategy.

1. Calibrate vision. Create `config/vision.json` from the example, then use
   fresh screenshots in `data/observations/vision/` to set the action-badge,
   hero-card, and board-card rectangles. Add representative card templates for
   all ranks and suits.
2. Build a labelled fixture set from the recorded observations. Add tests for
   each real action-panel and table-state variation before changing the parser
   or selectors.
3. Harden state validation. Require a stable turn signal, valid hero-card
   reads, and an unambiguous legal action before any automatic action. Keep
   unknown or inconsistent state at `NO_ACTION`.
4. Replace the placeholder strategy with explicitly scoped, independently
   tested preflop and postflop rules. Include stack, position, blinds, pot,
   action history, and configurable risk limits.
5. Make automated play auditable: add structured decision/action logs,
   session and loss caps, a dry-run default, and a kill switch. Exercise only
   on tables where automation is allowed and that you are authorized to use.
6. Add development hygiene: a dependency lockfile, formatting/linting, and a
   CI workflow that runs the test suite on supported Python versions.
