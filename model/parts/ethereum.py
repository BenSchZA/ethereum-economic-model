"""
# Ethereum System

Policy Functions and State Update Functions shared between the Eth1 and Eth2 systems.
"""

import typing

import model.constants as constants
from model.types import ETH, USD_per_ETH, Gwei, Stage


def policy_network_issuance(
    params, substep, state_history, previous_state
) -> typing.Dict[str, ETH]:
    # Parameters
    dt = params["dt"]
    daily_pow_issuance = params["daily_pow_issuance"]

    # State Variables
    stage = previous_state["stage"]
    amount_slashed = previous_state["amount_slashed"]
    total_basefee = previous_state["total_basefee"]
    total_tips_to_validators = previous_state["total_tips_to_validators"]
    total_online_validator_rewards = previous_state["total_online_validator_rewards"]

    # Calculate network issuance in ETH
    network_issuance = (
        # Remove tips to validators which is not issuance (ETH transferred rather than minted)
        (total_online_validator_rewards - total_tips_to_validators)
        - amount_slashed
        - total_basefee
    ) / constants.gwei

    # Calculate Proof of Work issuance
    pow_issuance = (
        daily_pow_issuance / constants.epochs_per_day
        if Stage(stage) in [Stage.BEACON_CHAIN, Stage.EIP1559]
        else 0
    )
    network_issuance += pow_issuance * dt

    return {
        "network_issuance": network_issuance,
        "pow_issuance": pow_issuance,
    }


def policy_eip1559_transaction_pricing(
    params, substep, state_history, previous_state
) -> typing.Dict[str, Gwei]:
    """EIP1559 Transaction Pricing Mechanism
    A transaction pricing mechanism that includes fixed-per-block network fee
    that is burned and dynamically expands/contracts block sizes to deal with transient congestion.

    See:
    * https://github.com/ethereum/EIPs/blob/master/EIPS/eip-1559.md
    * https://eips.ethereum.org/EIPS/eip-1559
    """

    stage = Stage(previous_state["stage"])
    if not stage in [Stage.EIP1559, Stage.PROOF_OF_STAKE]:
        return {
            "basefee": 0,
            "total_basefee": 0,
            "total_tips_to_miners": 0,
            "total_tips_to_validators": 0,
        }

    # Parameters
    dt = params["dt"]
    gas_target = params["gas_target"]  # Gas
    ELASTICITY_MULTIPLIER = params["ELASTICITY_MULTIPLIER"]
    BASE_FEE_MAX_CHANGE_DENOMINATOR = params["BASE_FEE_MAX_CHANGE_DENOMINATOR"]
    eip1559_basefee_process = params["eip1559_basefee_process"]
    eip1559_tip_process = params["eip1559_tip_process"]
    daily_transactions_process = params["daily_transactions_process"]
    transaction_average_gas = params["transaction_average_gas"]

    # State Variables
    run = previous_state["run"]
    timestep = previous_state["timestep"]
    previous_basefee = previous_state["basefee"]

    # Get samples for current run and timestep from basefee, tip, and transaction processes
    basefee = eip1559_basefee_process(run, timestep * dt)  # Gwei per Gas

    # Ensure basefee changes by no more than 1 / BASE_FEE_MAX_CHANGE_DENOMINATOR %
    # assert (
    #     abs(basefee - previous_basefee) / previous_basefee
    #     <= constants.slots_per_epoch / BASE_FEE_MAX_CHANGE_DENOMINATOR
    #     if timestep > 1
    #     else True
    # ), "basefee changed by more than 1 / BASE_FEE_MAX_CHANGE_DENOMINATOR %"

    avg_tip_amount = eip1559_tip_process(run, timestep * dt)  # Gwei per Gas
    transactions_per_day = daily_transactions_process(
        run, timestep * dt
    )  # Transactions per day
    transactions_per_epoch = (
        transactions_per_day / constants.epochs_per_day
    )  # Transactions per epoch

    # Calculate total basefee and tips to validators
    gas_used = transactions_per_epoch * transaction_average_gas  # Gas
    total_basefee = gas_used * basefee  # Gwei
    total_tips = gas_used * avg_tip_amount  # Gwei

    if stage in [Stage.PROOF_OF_STAKE]:
        total_tips_to_miners = 0
        total_tips_to_validators = total_tips
    else:
        total_tips_to_miners = total_tips
        total_tips_to_validators = 0

    # Check if the block used too much gas
    assert (
        gas_used <= gas_target * ELASTICITY_MULTIPLIER * constants.slots_per_epoch
    ), "invalid block: too much gas used"

    return {
        "basefee": basefee,
        "total_basefee": total_basefee * dt,
        "total_tips_to_miners": total_tips_to_miners * dt,
        "total_tips_to_validators": total_tips_to_validators * dt,
    }


def update_eth_price(
    params, substep, state_history, previous_state, policy_input
) -> typing.Tuple[str, USD_per_ETH]:
    # Parameters
    dt = params["dt"]
    eth_price_process = params["eth_price_process"]

    # State Variables
    run = previous_state["run"]
    timestep = previous_state["timestep"]

    # Get the ETH price sample for the current run and timestep
    eth_price_sample = eth_price_process(run, timestep * dt)

    return "eth_price", eth_price_sample


def update_eth_supply(
    params, substep, state_history, previous_state, policy_input
) -> typing.Tuple[str, ETH]:
    # Policy Inputs
    network_issuance = policy_input["network_issuance"]

    # State variables
    eth_supply = previous_state["eth_supply"]

    return "eth_supply", eth_supply + network_issuance
