import ape
import click
import json
import os
import sys

from rich.console import Console as RichConsole
from typing import Dict

from scripts.call_tree_parser import parse_as_tree
from scripts.get_calltrace_from_tx import (
    _get_avg_gas_cost_per_method_for_tx,
    _get_calltree,
)
from scripts.stableswap_pool_gas_calculator import (
    _get_gas_table_for_stableswap_pool,
    _get_gas_table_for_stableswap_pool_in_block_range,
)


REGISTRIES = {
    "MAIN_REGISTRY": "0x90E00ACe148ca3b23Ac1bC8C240C2a7Dd9c2d7f5",
    "STABLESWAP_FACTORY": "0xB9fC157394Af804a3578134A6585C0dc9cc990d4",
    "CRYPTOSWAP_REGISTRY": "0x8F942C20D02bEfc377D41445793068908E2250D0",
    "CRYPTOSWAP_FACTORY": "0xF18056Bbd320E96A48e3Fbf8bC061322531aac99",
}
STABLESWAP_GAS_TABLE_FILE = f"stableswap_pools_gas_estimates.json"
RICH_CONSOLE = RichConsole(file=sys.stdout)


def __get_pools(registry: str):
    pools = []
    registry = ape.Contract(registry)
    pool_count = registry.pool_count()
    for i in range(pool_count):
        pool = registry.pool_list(i)
        if pool not in pools:
            pools.append(pool)
    return pools


def __append_gas_table_to_output_file(
    output_file_name: str, pool_addr: str, decoded_gas_table: Dict
):

    # save gas costs to file
    RICH_CONSOLE.print(f"saving gas costs to file [green]{output_file_name}...")
    file_exists = os.path.exists(output_file_name)

    costs = {}
    if file_exists:
        with open(output_file_name, "r") as f:
            try:
                costs = json.load(f)
            except json.decoder.JSONDecodeError:
                pass

    # we check if pool_addr key exists in the previously cached gas table:
    # if so, then we check if the new gas table has a higher number of transaction
    # count that are used in the stats. If so, then we update the cached gas table.
    if pool_addr in costs:

        assert "count" in costs[pool_addr]  # dev: cost table should always have `count`

        if decoded_gas_table["count"] > costs[pool_addr]["count"]:
            costs[pool_addr] = decoded_gas_table
            with open(output_file_name, "w") as f:
                json.dump(costs, f, indent=4)


@click.group(short_help="Gets average gas costs for contracts")
def cli():
    """
    Command-line helper for fetching historic gas costs
    """
    pass


# ---- writes to file stableswap_pools_gas_estimates.json---- #


@cli.command(
    cls=ape.cli.NetworkBoundCommand,
    name="stableswap-pools",
    short_help=(
        "Get average gas costs for methods in pool contracts in a registry "
        "in the past `min_transaction` transactions",
    ),
)
@ape.cli.network_option()
@click.option(
    "--min_transactions",
    "-m",
    required=True,
    help="Minimum number of transactions to use in the calculation",
    type=int,
    default=500,
)
def _get_gas_costs_for_stableswap_registry_pools(network, min_transactions):

    # get all pools in the registry:
    RICH_CONSOLE.print("Getting all stableswap pools ...")
    pools = []
    for registry in [REGISTRIES["MAIN_REGISTRY"], REGISTRIES["STABLESWAP_FACTORY"]]:
        pools.extend(__get_pools(registry))
    pools = list(set(pools))
    RICH_CONSOLE.print(f"... found [red]{len(pools)} pools.")

    for pool_addr in pools:

        pool = ape.Contract(pool_addr)

        try:
            # get gas estimates
            decoded_gas_table = _get_gas_table_for_stableswap_pool(
                pool, min_transactions
            )

            # save gas costs to file
            if decoded_gas_table:
                __append_gas_table_to_output_file(
                    STABLESWAP_GAS_TABLE_FILE, pool_addr, decoded_gas_table
                )
        except Exception:
            RICH_CONSOLE.print_exception(show_locals=True)
            RICH_CONSOLE.print(
                f"Error getting gas costs for [red]{pool_addr}. Moving on ..."
            )


@cli.command(
    cls=ape.cli.NetworkBoundCommand,
    name="stableswap-pool",
    short_help=(
        "Get average gas costs for methods in a single pool for txes "
        "in block range `start_block` to `end_block`",
    ),
)
@ape.cli.network_option()
@click.option("--pool", "-p", required=True, help="Pool address", type=str)
@click.option("--start_block", "-s", required=True, help="Start block", type=int)
@click.option("--end_block", "-e", required=True, help="End block", type=int)
def _get_gas_costs_for_stableswap_pool(network, pool, start_block, end_block):

    pool = ape.Contract(pool)

    decoded_gas_table = _get_gas_table_for_stableswap_pool_in_block_range(
        pool, start_block, end_block
    )

    if decoded_gas_table:
        __append_gas_table_to_output_file(
            STABLESWAP_GAS_TABLE_FILE, pool.address, decoded_gas_table
        )

        RICH_CONSOLE.print_json(json.dumps(decoded_gas_table, indent=4))


# ---- read only ---- #


@cli.command(
    cls=ape.cli.NetworkBoundCommand,
    name="stableswap-pool-tx",
    short_help=(
        "Get average gas costs for methods in a single pool in the past "
        "`min_transaction` transactions",
    ),
)
@ape.cli.network_option()
@click.option("--contractaddr", "-p", required=True, help="Contract address", type=str)
@click.option("--tx", "-t", required=True, help="Transaction hash", type=str)
def _get_gas_costs_tx(network, contractaddr, tx):

    contract = ape.Contract(contractaddr)
    call_tree = _get_calltree(tx_hash=tx)
    rich_call_tree = parse_as_tree(call_tree, [contract.address])

    RICH_CONSOLE.print(f"Call trace for [bold blue]'{tx}'[/]")
    RICH_CONSOLE.print(rich_call_tree)
    RICH_CONSOLE.print(f"\nGas consumed per method for [red]'{contract}':")
    gas_cost = _get_avg_gas_cost_per_method_for_tx(contract, call_tree)
    RICH_CONSOLE.print_json(json.dumps(gas_cost, indent=4))
