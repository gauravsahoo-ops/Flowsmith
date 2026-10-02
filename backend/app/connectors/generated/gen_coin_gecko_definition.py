"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: CoinGecko Demo API
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "coin_gecko"
CONNECTOR_VERSION = "1.0.0"
OPERATION_VERSION = "1.0.0"


def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):
    return ConnectorOperationV1(
        connector_key=CONNECTOR_KEY,
        connector_version=CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema={"type": "object", "properties": {}},
        credential_require="coin_gecko",
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "ping_server": _operation("ping_server", "API Server Status", "GET /ping", {"type": "object", "properties": {}, "required": []}),
        "simple_price": _operation("simple_price", "Coin Price by IDs, Symbols, or Names", "GET /simple/price", {"type": "object", "properties": {"vs_currencies": {"type": "string", "title": "vs_currencies"}, "ids": {"type": "string", "title": "ids"}, "names": {"type": "string", "title": "names"}, "symbols": {"type": "string", "title": "symbols"}, "include_tokens": {"type": "string", "title": "include_tokens"}, "include_market_cap": {"type": "string", "title": "include_market_cap"}, "include_24hr_vol": {"type": "string", "title": "include_24hr_vol"}, "include_24hr_change": {"type": "string", "title": "include_24hr_change"}, "include_last_updated_at": {"type": "string", "title": "include_last_updated_at"}, "precision": {"type": "string", "title": "precision"}}, "required": ["vs_currencies"]}),
        "search_data": _operation("search_data", "Search Queries", "GET /search", {"type": "object", "properties": {"query": {"type": "string", "title": "query"}}, "required": ["query"]}),
        "simple_supported_currencies": _operation("simple_supported_currencies", "Currencies List", "GET /simple/supported_vs_currencies", {"type": "object", "properties": {}, "required": []}),
        "simple_token_price": _operation("simple_token_price", "Coin Price by Token Addresses", "GET /simple/token_price/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "contract_addresses": {"type": "string", "title": "contract_addresses"}, "vs_currencies": {"type": "string", "title": "vs_currencies"}, "include_market_cap": {"type": "string", "title": "include_market_cap"}, "include_24hr_vol": {"type": "string", "title": "include_24hr_vol"}, "include_24hr_change": {"type": "string", "title": "include_24hr_change"}, "include_last_updated_at": {"type": "string", "title": "include_last_updated_at"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "contract_addresses", "vs_currencies"]}),
        "coins_list": _operation("coins_list", "Coins List", "GET /coins/list", {"type": "object", "properties": {"include_platform": {"type": "string", "title": "include_platform"}, "status": {"type": "string", "title": "status"}}, "required": []}),
        "coins_id": _operation("coins_id", "Coin Data by ID", "GET /coins/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "localization": {"type": "string", "title": "localization"}, "tickers": {"type": "string", "title": "tickers"}, "market_data": {"type": "string", "title": "market_data"}, "community_data": {"type": "string", "title": "community_data"}, "developer_data": {"type": "string", "title": "developer_data"}, "sparkline": {"type": "string", "title": "sparkline"}, "include_categories_details": {"type": "string", "title": "include_categories_details"}, "dex_pair_format": {"type": "string", "title": "dex_pair_format"}}, "required": ["id"]}),
        "coins_markets": _operation("coins_markets", "Coins List with Market Data", "GET /coins/markets", {"type": "object", "properties": {"vs_currency": {"type": "string", "title": "vs_currency"}, "ids": {"type": "string", "title": "ids"}, "names": {"type": "string", "title": "names"}, "symbols": {"type": "string", "title": "symbols"}, "include_tokens": {"type": "string", "title": "include_tokens"}, "category": {"type": "string", "title": "category"}, "order": {"type": "string", "title": "order"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}, "sparkline": {"type": "string", "title": "sparkline"}, "price_change_percentage": {"type": "string", "title": "price_change_percentage"}, "locale": {"type": "string", "title": "locale"}, "precision": {"type": "string", "title": "precision"}, "include_rehypothecated": {"type": "string", "title": "include_rehypothecated"}}, "required": ["vs_currency"]}),
        "coins_id_tickers": _operation("coins_id_tickers", "Coin Tickers by ID", "GET /coins/{id}/tickers", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "exchange_ids": {"type": "string", "title": "exchange_ids"}, "include_exchange_logo": {"type": "string", "title": "include_exchange_logo"}, "page": {"type": "string", "title": "page"}, "order": {"type": "string", "title": "order"}, "depth": {"type": "string", "title": "depth"}, "dex_pair_format": {"type": "string", "title": "dex_pair_format"}}, "required": ["id"]}),
        "coins_id_history": _operation("coins_id_history", "Coin Historical Data by ID", "GET /coins/{id}/history", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "date": {"type": "string", "title": "date"}, "localization": {"type": "string", "title": "localization"}}, "required": ["id", "date"]}),
        "coins_id_market_chart": _operation("coins_id_market_chart", "Coin Historical Chart Data by ID", "GET /coins/{id}/market_chart", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "vs_currency": {"type": "string", "title": "vs_currency"}, "days": {"type": "string", "title": "days"}, "interval": {"type": "string", "title": "interval"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "vs_currency", "days"]}),
        "coins_id_market_chart_range": _operation("coins_id_market_chart_range", "Coin Historical Chart Data within Time Range by ID", "GET /coins/{id}/market_chart/range", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "vs_currency": {"type": "string", "title": "vs_currency"}, "from": {"type": "string", "title": "from"}, "to": {"type": "string", "title": "to"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "vs_currency", "from", "to"]}),
        "coins_id_ohlc": _operation("coins_id_ohlc", "Coin OHLC Chart by ID", "GET /coins/{id}/ohlc", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "vs_currency": {"type": "string", "title": "vs_currency"}, "days": {"type": "string", "title": "days"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "vs_currency", "days"]}),
        "coins_contract_address": _operation("coins_contract_address", "Coin Data by Token Address", "GET /coins/{id}/contract/{contract_address}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "contract_address": {"type": "string", "title": "contract_address"}}, "required": ["id", "contract_address"]}),
        "contract_address_market_chart": _operation("contract_address_market_chart", "Coin Historical Chart Data by Token Address", "GET /coins/{id}/contract/{contract_address}/market_chart", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "contract_address": {"type": "string", "title": "contract_address"}, "vs_currency": {"type": "string", "title": "vs_currency"}, "days": {"type": "string", "title": "days"}, "interval": {"type": "string", "title": "interval"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "contract_address", "vs_currency", "days"]}),
        "contract_address_market_chart_range": _operation("contract_address_market_chart_range", "Coin Historical Chart Data within Time Range by Token Address", "GET /coins/{id}/contract/{contract_address}/market_chart/range", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "contract_address": {"type": "string", "title": "contract_address"}, "vs_currency": {"type": "string", "title": "vs_currency"}, "from": {"type": "string", "title": "from"}, "to": {"type": "string", "title": "to"}, "precision": {"type": "string", "title": "precision"}}, "required": ["id", "contract_address", "vs_currency", "from", "to"]}),
        "asset_platforms_list": _operation("asset_platforms_list", "Asset Platforms List", "GET /asset_platforms", {"type": "object", "properties": {"filter": {"type": "string", "title": "filter"}}, "required": []}),
        "token_lists": _operation("token_lists", "Token Lists by Asset Platform ID", "GET /token_lists/{asset_platform_id}/all.json", {"type": "object", "properties": {"asset_platform_id": {"type": "string", "title": "asset_platform_id"}}, "required": ["asset_platform_id"]}),
        "coins_categories_list": _operation("coins_categories_list", "Coins Categories List", "GET /coins/categories/list", {"type": "object", "properties": {}, "required": []}),
        "coins_categories": _operation("coins_categories", "Coins Categories List with Market Data", "GET /coins/categories", {"type": "object", "properties": {"order": {"type": "string", "title": "order"}}, "required": []}),
        "rwas_list": _operation("rwas_list", "RWA List", "GET /rwas/list", {"type": "object", "properties": {"asset_type": {"type": "string", "title": "asset_type"}}, "required": []}),
        "rwas_markets": _operation("rwas_markets", "RWA List with Market Data", "GET /rwas/markets", {"type": "object", "properties": {"asset_type": {"type": "string", "title": "asset_type"}, "ids": {"type": "string", "title": "ids"}, "names": {"type": "string", "title": "names"}, "symbols": {"type": "string", "title": "symbols"}, "issuer": {"type": "string", "title": "issuer"}, "order": {"type": "string", "title": "order"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}, "sparkline": {"type": "string", "title": "sparkline"}, "price_change_percentage": {"type": "string", "title": "price_change_percentage"}, "precision": {"type": "string", "title": "precision"}}, "required": []}),
        "rwas_id": _operation("rwas_id", "RWA Data by ID", "GET /rwas/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "sparkline": {"type": "string", "title": "sparkline"}, "tokens": {"type": "string", "title": "tokens"}, "tokenized_market_data": {"type": "string", "title": "tokenized_market_data"}}, "required": ["id"]}),
        "rwas_issuers_list": _operation("rwas_issuers_list", "RWA Issuers List", "GET /rwas/issuers/list", {"type": "object", "properties": {}, "required": []}),
        "rwas_issuers_id": _operation("rwas_issuers_id", "RWA Issuer Data by ID", "GET /rwas/issuers/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "exchanges": _operation("exchanges", "Exchanges List with Data", "GET /exchanges", {"type": "object", "properties": {"per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}}, "required": []}),
        "exchanges_list": _operation("exchanges_list", "Exchanges List", "GET /exchanges/list", {"type": "object", "properties": {"status": {"type": "string", "title": "status"}}, "required": []}),
        "exchanges_id": _operation("exchanges_id", "Exchange Data by ID", "GET /exchanges/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "dex_pair_format": {"type": "string", "title": "dex_pair_format"}}, "required": ["id"]}),
        "exchanges_id_tickers": _operation("exchanges_id_tickers", "Exchange Tickers by ID", "GET /exchanges/{id}/tickers", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "coin_ids": {"type": "string", "title": "coin_ids"}, "include_exchange_logo": {"type": "string", "title": "include_exchange_logo"}, "page": {"type": "string", "title": "page"}, "depth": {"type": "string", "title": "depth"}, "order": {"type": "string", "title": "order"}, "dex_pair_format": {"type": "string", "title": "dex_pair_format"}}, "required": ["id"]}),
        "exchanges_id_volume_chart": _operation("exchanges_id_volume_chart", "Exchange Volume Chart by ID", "GET /exchanges/{id}/volume_chart", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "days": {"type": "string", "title": "days"}}, "required": ["id", "days"]}),
        "derivatives_tickers": _operation("derivatives_tickers", "Derivatives Tickers List", "GET /derivatives", {"type": "object", "properties": {}, "required": []}),
        "derivatives_exchanges": _operation("derivatives_exchanges", "Derivatives Exchanges List with Data", "GET /derivatives/exchanges", {"type": "object", "properties": {"order": {"type": "string", "title": "order"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}}, "required": []}),
        "derivatives_exchanges_id": _operation("derivatives_exchanges_id", "Derivatives Exchange Data by ID", "GET /derivatives/exchanges/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "include_tickers": {"type": "string", "title": "include_tickers"}}, "required": ["id"]}),
        "derivatives_exchanges_list": _operation("derivatives_exchanges_list", "Derivatives Exchanges List", "GET /derivatives/exchanges/list", {"type": "object", "properties": {}, "required": []}),
        "entities_list": _operation("entities_list", "Entities List", "GET /entities/list", {"type": "object", "properties": {"entity_type": {"type": "string", "title": "entity_type"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}}, "required": []}),
        "companies_public_treasury": _operation("companies_public_treasury", "Crypto Treasury Holdings by Coin ID", "GET /{entity}/public_treasury/{coin_id}", {"type": "object", "properties": {"entity": {"type": "string", "title": "entity"}, "coin_id": {"type": "string", "title": "coin_id"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}, "order": {"type": "string", "title": "order"}}, "required": ["entity", "coin_id"]}),
        "public_treasury_entity": _operation("public_treasury_entity", "Crypto Treasury Holdings by Entity ID", "GET /public_treasury/{entity_id}", {"type": "object", "properties": {"entity_id": {"type": "string", "title": "entity_id"}, "holding_amount_change": {"type": "string", "title": "holding_amount_change"}, "holding_change_percentage": {"type": "string", "title": "holding_change_percentage"}}, "required": ["entity_id"]}),
        "public_treasury_entity_chart": _operation("public_treasury_entity_chart", "Crypto Treasury Holdings Historical Chart Data by ID", "GET /public_treasury/{entity_id}/{coin_id}/holding_chart", {"type": "object", "properties": {"entity_id": {"type": "string", "title": "entity_id"}, "coin_id": {"type": "string", "title": "coin_id"}, "days": {"type": "string", "title": "days"}, "include_empty_intervals": {"type": "string", "title": "include_empty_intervals"}}, "required": ["entity_id", "coin_id", "days"]}),
        "public_treasury_transaction_history": _operation("public_treasury_transaction_history", "Crypto Treasury Transaction History by Entity ID", "GET /public_treasury/{entity_id}/transaction_history", {"type": "object", "properties": {"entity_id": {"type": "string", "title": "entity_id"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}, "order": {"type": "string", "title": "order"}, "coin_ids": {"type": "string", "title": "coin_ids"}}, "required": ["entity_id"]}),
        "nfts_list": _operation("nfts_list", "NFTs List", "GET /nfts/list", {"type": "object", "properties": {"order": {"type": "string", "title": "order"}, "per_page": {"type": "string", "title": "per_page"}, "page": {"type": "string", "title": "page"}}, "required": []}),
        "nfts_id": _operation("nfts_id", "NFTs Collection Data by ID", "GET /nfts/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "nfts_contract_address": _operation("nfts_contract_address", "NFTs Collection Data by Contract Address", "GET /nfts/{asset_platform_id}/contract/{contract_address}", {"type": "object", "properties": {"asset_platform_id": {"type": "string", "title": "asset_platform_id"}, "contract_address": {"type": "string", "title": "contract_address"}}, "required": ["asset_platform_id", "contract_address"]}),
        "exchange_rates": _operation("exchange_rates", "BTC-to-Currency Exchange Rates", "GET /exchange_rates", {"type": "object", "properties": {}, "required": []}),
        "trending_search": _operation("trending_search", "Trending Search List", "GET /search/trending", {"type": "object", "properties": {}, "required": []}),
        "crypto_global": _operation("crypto_global", "Crypto Global Market Data", "GET /global", {"type": "object", "properties": {}, "required": []}),
        "global_defi": _operation("global_defi", "Global DeFi Market Data", "GET /global/decentralized_finance_defi", {"type": "object", "properties": {}, "required": []}),
        "pool_address": _operation("pool_address", "Specific Pool Data by Pool Address", "GET /onchain/networks/{network}/pools/{address}", {"type": "object", "properties": {"network": {"type": "string", "title": "network"}, "address": {"type": "string", "title": "address"}, "include": {"type": "string", "title": "include"}, "include_volume_breakdown": {"type": "string", "title": "include_volume_breakdown"}, "include_composition": {"type": "string", "title": "include_composition"}}, "required": ["network", "address"]}),
        "trending_pools_list": _operation("trending_pools_list", "Trending Pools List", "GET /onchain/networks/trending_pools", {"type": "object", "properties": {"include": {"type": "string", "title": "include"}, "page": {"type": "string", "title": "page"}, "duration": {"type": "string", "title": "duration"}, "include_gt_community_data": {"type": "string", "title": "include_gt_community_data"}}, "required": []}),
        "trending_pools_network": _operation("trending_pools_network", "Trending Pools by Network", "GET /onchain/networks/{network}/trending_pools", {"type": "object", "properties": {"network": {"type": "string", "title": "network"}, "include": {"type": "string", "title": "include"}, "page": {"type": "string", "title": "page"}, "duration": {"type": "string", "title": "duration"}, "include_gt_community_data": {"type": "string", "title": "include_gt_community_data"}}, "required": ["network"]}),
        "top_pools_network": _operation("top_pools_network", "Top Pools by Network", "GET /onchain/networks/{network}/pools", {"type": "object", "properties": {"network": {"type": "string", "title": "network"}, "include": {"type": "string", "title": "include"}, "page": {"type": "string", "title": "page"}, "sort": {"type": "string", "title": "sort"}, "include_gt_community_data": {"type": "string", "title": "include_gt_community_data"}}, "required": ["network"]}),
    }


def build_coin_gecko_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="CoinGecko",
        description="Generated from CoinGecko Demo API.",
        category="finance",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={
            "coin_gecko": CredentialTypeV1(
                type_key="coin_gecko",
                display_name="CoinGecko",
                description="Credentials for CoinGecko Demo API (imported).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_key": {"type": "string", "title": "API key"}},
                    "required": ["api_key"],
                },
                encryption_required=True,
            ),
        },
        metadata={"source": "openapi-import", "api_title": "CoinGecko Demo API"},
        icon="openapi",
    )
