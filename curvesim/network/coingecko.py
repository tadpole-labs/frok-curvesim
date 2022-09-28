import asyncio
from datetime import datetime, timedelta, timezone
from itertools import combinations

import numpy as np
import pandas as pd

from .http import HTTP

URL = "https://api.coingecko.com/api/v3/"


async def get_prices(coin_id, vs_currency, days):
    url = URL + f"coins/{coin_id}/market_chart"
    p = {"vs_currency": vs_currency, "days": days}

    r = await HTTP.get(url, params=p)

    # Format data
    data = pd.DataFrame(r["prices"], columns=["timestamp", "prices"])
    data = data.merge(pd.DataFrame(r["total_volumes"], columns=["timestamp", "volumes"]))
    data["timestamp"] = pd.to_datetime(data["timestamp"], unit="ms", utc="True")
    data = data.set_index("timestamp")

    return data


async def _pool_prices(coins, vs_currency, days):
    # Times to reindex to: hourly intervals starting on half hour mark
    t_end = datetime.utcnow() - timedelta(days=1)
    t_end = t_end.replace(hour=23, minute=30, second=0, microsecond=0)
    t_start = t_end - timedelta(days=days + 1)
    t_samples = pd.date_range(start=t_start, end=t_end, freq="60T", tz=timezone.utc)

    # Fetch data
    tasks = []
    for coin in coins:
        tasks.append(get_prices(coin, vs_currency, days + 3))

    data = await asyncio.gather(*tasks)

    # Format data
    qprices = []
    qvolumes = []
    for d in data:
        d.drop(d.tail(1).index, inplace=True)  # remove last row
        d = d.reindex(t_samples, method="ffill")
        qprices.append(d["prices"])
        qvolumes.append(d["volumes"])

    qprices = pd.concat(qprices, axis=1)
    qvolumes = pd.concat(qvolumes, axis=1)
    qvolumes = qvolumes / np.array(qprices)

    return qprices, qvolumes


def pool_prices(coins, vs_currency, days):
    # Get data
    loop = asyncio.get_event_loop()

    coins = loop.run_until_complete(coin_ids_from_addresses(coins, "mainnet"))

    qprices, qvolumes = loop.run_until_complete(_pool_prices(coins, vs_currency, days))

    # Compute prices by coin pairs
    combos = list(combinations(range(len(coins)), 2))
    prices = []
    volumes = []

    for pair in combos:
        prices.append(qprices.iloc[:, pair[0]] / qprices.iloc[:, pair[1]])  # divide prices
        volumes.append(qvolumes.iloc[:, pair[0]] + qvolumes.iloc[:, pair[1]])  # sum volumes

    prices = pd.concat(prices, axis=1)
    volumes = pd.concat(volumes, axis=1)

    return prices, volumes


async def coin_id_from_address(address, chain):
    address = address.lower()
    chain = PLATFORMS[chain.lower()]
    url = URL + f"coins/{chain}/contract/{address}"

    r = await HTTP.get(url)

    coin_id = r["id"]

    return coin_id


async def coin_ids_from_addresses(addresses, chain):
    tasks = []
    for addr in addresses:
        tasks.append(coin_id_from_address(addr, chain))

    coin_ids = await asyncio.gather(*tasks)

    return coin_ids


async def coin_info_from_id(ID, chain, chain_out="mainnet"):
    chain = PLATFORMS[chain.lower()]
    chain_out = PLATFORMS[chain_out.lower()]
    url = URL + f"coins/{ID}"

    r = await HTTP.get(url)
    address = r["platforms"][chain_out]
    symbol = r["symbol"]

    return address, symbol


async def coin_info_from_ids(IDs, chain, chain_out="mainnet"):
    tasks = []
    for ID in IDs:
        tasks.append(coin_info_from_id(ID, chain, chain_out=chain_out))

    r = await asyncio.gather(*tasks)

    addresses, symbols = list(zip(*r))

    return addresses, symbols


async def crosschain_coin_address(address, chain_in, chain_out):
    if chain_in == "mainnet" and chain_out == "mainnet":
        return address

    address = address.lower()
    chain_in = PLATFORMS[chain_in.lower()]
    chain_out = PLATFORMS[chain_out.lower()]
    url = URL + f"coins/{chain_in}/contract/{address}"

    r = await HTTP.get(url)

    address = r["platforms"][chain_out]

    return address


async def crosschain_coin_addresses(addresses, chain_in, chain_out):
    tasks = []
    for addr in addresses:
        tasks.append(crosschain_coin_address(addr, chain_in, chain_out))

    addresses_out = await asyncio.gather(*tasks)

    return addresses_out


PLATFORMS = {
    "mainnet": "ethereum",
    "arbitrum": "arbitrum-one",
    "polygon": "polygon-pos",
    "optimism": "optimistic-ethereum",
    "xdai": "xdai",
    "fantom": "fantom",
    "avalanche": "avalanche",
    "matic:": "polygon-pos",
}
