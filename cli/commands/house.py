"""hl house — TEE clearing house agent commands."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

import typer

house_app = typer.Typer(no_args_is_help=True)


@house_app.command("join")
def house_join(
    strategy: str = typer.Argument(..., help="Strategy module:Class or short name"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", "-a",
                                            help="Agent ID (default: auto-generated)"),
    url: str = typer.Option("http://localhost:8080", "--url", "-u",
                            help="House relay URL"),
    poll: float = typer.Option(2.0, "--poll", "-p", help="Poll interval (seconds)"),
    max_rounds: int = typer.Option(0, "--max-rounds", help="Stop after N rounds (0=forever)"),
    register: bool = typer.Option(False, "--register", help="Register strategy hash before joining"),
):
    """Join a running house enclave as a trading agent."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from cli.strategy_registry import resolve_strategy_path
    from sdk.strategy_sdk.loader import load_strategy
    from agent.client import AgentClient

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)-14s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve strategy
    module_path = resolve_strategy_path(strategy)
    cls = load_strategy(module_path)
    strat = cls()
    typer.echo(f"Strategy: {cls.__name__} ({module_path})")

    # Optionally register strategy hash
    if register:
        from sdk.strategy_sdk.registry import ModelRegistry
        registry = ModelRegistry()
        bundle = registry.register(module_path)
        typer.echo(f"Registered: {bundle.strategy_id} (hash={bundle.source_hash[:16]}...)")

    # Generate agent ID if not provided
    if not agent_id:
        import os
        agent_id = f"agent-{os.urandom(4).hex()}"
    typer.echo(f"Agent ID: {agent_id}")
    typer.echo(f"Relay: {url}")

    client = AgentClient(agent_id=agent_id, strategy=strat, relay_url=url)

    # Fetch enclave identity
    try:
        identity = client.fetch_identity()
        typer.echo(f"Connected to enclave (pubkey={identity['enclave_pubkey'][:16]}...)")
    except Exception as e:
        typer.echo(f"Error: Cannot connect to relay at {url}: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Polling every {poll}s — waiting for clearing rounds...")

    rounds_completed = 0
    try:
        while True:
            try:
                result = client.poll_and_participate()
                if result:
                    rounds_completed += 1
                    typer.echo(f"Round {result['round_id']}: submitted {result['num_orders']} orders")
                    if max_rounds > 0 and rounds_completed >= max_rounds:
                        typer.echo(f"Completed {max_rounds} rounds, exiting.")
                        break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logging.getLogger("house_join").warning("Poll error: %s", e)

            time.sleep(poll)
    except KeyboardInterrupt:
        typer.echo(f"\nStopped after {rounds_completed} rounds.")


@house_app.command("status")
def house_status(
    url: str = typer.Option("http://localhost:8080", "--url", "-u",
                            help="House relay URL"),
):
    """Show house scoreboard and current round state."""
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import requests

    # Fetch scoreboard
    try:
        resp = requests.get(f"{url.rstrip('/')}/v1/scoreboard", timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        typer.echo(f"Error: Cannot connect to relay at {url}: {e}", err=True)
        raise typer.Exit(1)

    agents = data.get("agents", [])
    if not agents:
        typer.echo("No agents on scoreboard yet.")
        return

    typer.echo(f"{'Rank':<6} {'Agent':<20} {'PnL':>10} {'Fills':>8} {'Rounds':>8}")
    typer.echo("-" * 55)
    for i, a in enumerate(agents, 1):
        agent_id = a.get("agent_id", "?")
        pnl = a.get("total_pnl", 0)
        fills = a.get("total_fills", 0)
        rounds = a.get("rounds_participated", 0)
        typer.echo(f"{i:<6} {agent_id:<20} {pnl:>+10.2f} {fills:>8} {rounds:>8}")

    # Also show current round info
    try:
        snap_resp = requests.get(f"{url.rstrip('/')}/v1/snapshot", timeout=5)
        snap_resp.raise_for_status()
        snap = snap_resp.json()
        typer.echo(f"\nCurrent round: {snap.get('round_id', 'none')}  |  "
                   f"Phase: {snap.get('phase', 'idle')}")
    except Exception:
        pass
