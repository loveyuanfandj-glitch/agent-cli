# Autoresearch Program: APEX Config Optimization

## Objective
Optimize APEX trading strategy parameters by replaying historical trades through the backtest harness and maximizing net PnL while maintaining trade quality.

## Mutable File
`apex_config.json`

## Run Command
```
python3 scripts/backtest_apex.py --config apex_config.json --trades data/cli/trades.jsonl
```

## Target Metric
`net_pnl` (highest)

## Secondary Metrics (monitor but don't optimize directly)
- `win_rate` — should stay above 40%
- `fdr` — should stay below 30%
- `trades` — should stay above 5 (quality gate)
- `profit_factor` — should stay above 1.0

## Parameter Bounds (guardrails)

| Parameter                    | Min   | Max   | Step | Default |
|------------------------------|-------|-------|------|---------|
| radar_score_threshold        | 120   | 280   | 10   | 170     |
| pulse_confidence_threshold   | 40.0  | 95.0  | 5.0  | 70.0    |
| daily_loss_limit             | 50.0  | 5000.0| 50.0 | 500.0   |
| max_same_direction           | 1     | 3     | 1    | 2       |

## Research Directions

These are common exploration paths based on REFLECT findings:

1. **High FDR (>30%)**: Raise `radar_score_threshold` in [170, 250] to filter low-quality entries that generate fees without sufficient edge.

2. **Low Win Rate (<40%)**: Sweep `pulse_confidence_threshold` in [70, 95] to require higher conviction before entry.

3. **Direction Imbalance**: If one direction is consistently losing, set `max_same_direction` to 1 to force diversification.

4. **Loss Streaks**: Reduce `daily_loss_limit` by 20% increments to cut drawdowns from consecutive losses.

5. **Healthy Strategy**: If metrics look good (win_rate >50%, FDR <15%), try *lowering* `radar_score_threshold` in [140, 170] to capture more trades without degrading quality.

6. **Fee Drag Emergency**: If fees exceed gross PnL, simultaneously raise `radar_score_threshold` to [220, 280] and `pulse_confidence_threshold` to [85, 95].

## Workflow

1. Start with the current `apex_config.json` as baseline
2. Run backtest to get baseline metrics
3. Pick a research direction based on the metrics
4. Modify one parameter at a time within bounds
5. Re-run backtest and compare
6. If `REJECT: too few trades` appears, the config is too restrictive — back off
7. Keep the config that maximizes `net_pnl` while passing all quality gates

## Quality Gates
- Must produce at least 5 round trips
- `profit_factor` must be > 1.0 (net profitable)
- `fdr` must be < 50% (fees not destroying all edge)
