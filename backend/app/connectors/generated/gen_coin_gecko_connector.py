"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.

Source API: CoinGecko Demo API
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)

from gen_coin_gecko_provider import GeneratedProvider


class GeneratedConnectorParams(BaseModel):
    operation: str = Field(default="")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    model_config = {'extra': 'allow'}


OPERATIONS = {'ping_server': {'method': 'GET', 'path': '/ping', 'path_params': [], 'query_params': [], 'has_body': False}, 'simple_price': {'method': 'GET', 'path': '/simple/price', 'path_params': [], 'query_params': ['vs_currencies', 'ids', 'names', 'symbols', 'include_tokens', 'include_market_cap', 'include_24hr_vol', 'include_24hr_change', 'include_last_updated_at', 'precision'], 'has_body': False}, 'search_data': {'method': 'GET', 'path': '/search', 'path_params': [], 'query_params': ['query'], 'has_body': False}, 'simple_supported_currencies': {'method': 'GET', 'path': '/simple/supported_vs_currencies', 'path_params': [], 'query_params': [], 'has_body': False}, 'simple_token_price': {'method': 'GET', 'path': '/simple/token_price/{id}', 'path_params': ['id'], 'query_params': ['contract_addresses', 'vs_currencies', 'include_market_cap', 'include_24hr_vol', 'include_24hr_change', 'include_last_updated_at', 'precision'], 'has_body': False}, 'coins_list': {'method': 'GET', 'path': '/coins/list', 'path_params': [], 'query_params': ['include_platform', 'status'], 'has_body': False}, 'coins_id': {'method': 'GET', 'path': '/coins/{id}', 'path_params': ['id'], 'query_params': ['localization', 'tickers', 'market_data', 'community_data', 'developer_data', 'sparkline', 'include_categories_details', 'dex_pair_format'], 'has_body': False}, 'coins_markets': {'method': 'GET', 'path': '/coins/markets', 'path_params': [], 'query_params': ['vs_currency', 'ids', 'names', 'symbols', 'include_tokens', 'category', 'order', 'per_page', 'page', 'sparkline', 'price_change_percentage', 'locale', 'precision', 'include_rehypothecated'], 'has_body': False}, 'coins_id_tickers': {'method': 'GET', 'path': '/coins/{id}/tickers', 'path_params': ['id'], 'query_params': ['exchange_ids', 'include_exchange_logo', 'page', 'order', 'depth', 'dex_pair_format'], 'has_body': False}, 'coins_id_history': {'method': 'GET', 'path': '/coins/{id}/history', 'path_params': ['id'], 'query_params': ['date', 'localization'], 'has_body': False}, 'coins_id_market_chart': {'method': 'GET', 'path': '/coins/{id}/market_chart', 'path_params': ['id'], 'query_params': ['vs_currency', 'days', 'interval', 'precision'], 'has_body': False}, 'coins_id_market_chart_range': {'method': 'GET', 'path': '/coins/{id}/market_chart/range', 'path_params': ['id'], 'query_params': ['vs_currency', 'from', 'to', 'precision'], 'has_body': False}, 'coins_id_ohlc': {'method': 'GET', 'path': '/coins/{id}/ohlc', 'path_params': ['id'], 'query_params': ['vs_currency', 'days', 'precision'], 'has_body': False}, 'coins_contract_address': {'method': 'GET', 'path': '/coins/{id}/contract/{contract_address}', 'path_params': ['id', 'contract_address'], 'query_params': [], 'has_body': False}, 'contract_address_market_chart': {'method': 'GET', 'path': '/coins/{id}/contract/{contract_address}/market_chart', 'path_params': ['id', 'contract_address'], 'query_params': ['vs_currency', 'days', 'interval', 'precision'], 'has_body': False}, 'contract_address_market_chart_range': {'method': 'GET', 'path': '/coins/{id}/contract/{contract_address}/market_chart/range', 'path_params': ['id', 'contract_address'], 'query_params': ['vs_currency', 'from', 'to', 'precision'], 'has_body': False}, 'asset_platforms_list': {'method': 'GET', 'path': '/asset_platforms', 'path_params': [], 'query_params': ['filter'], 'has_body': False}, 'token_lists': {'method': 'GET', 'path': '/token_lists/{asset_platform_id}/all.json', 'path_params': ['asset_platform_id'], 'query_params': [], 'has_body': False}, 'coins_categories_list': {'method': 'GET', 'path': '/coins/categories/list', 'path_params': [], 'query_params': [], 'has_body': False}, 'coins_categories': {'method': 'GET', 'path': '/coins/categories', 'path_params': [], 'query_params': ['order'], 'has_body': False}, 'rwas_list': {'method': 'GET', 'path': '/rwas/list', 'path_params': [], 'query_params': ['asset_type'], 'has_body': False}, 'rwas_markets': {'method': 'GET', 'path': '/rwas/markets', 'path_params': [], 'query_params': ['asset_type', 'ids', 'names', 'symbols', 'issuer', 'order', 'per_page', 'page', 'sparkline', 'price_change_percentage', 'precision'], 'has_body': False}, 'rwas_id': {'method': 'GET', 'path': '/rwas/{id}', 'path_params': ['id'], 'query_params': ['sparkline', 'tokens', 'tokenized_market_data'], 'has_body': False}, 'rwas_issuers_list': {'method': 'GET', 'path': '/rwas/issuers/list', 'path_params': [], 'query_params': [], 'has_body': False}, 'rwas_issuers_id': {'method': 'GET', 'path': '/rwas/issuers/{id}', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'exchanges': {'method': 'GET', 'path': '/exchanges', 'path_params': [], 'query_params': ['per_page', 'page'], 'has_body': False}, 'exchanges_list': {'method': 'GET', 'path': '/exchanges/list', 'path_params': [], 'query_params': ['status'], 'has_body': False}, 'exchanges_id': {'method': 'GET', 'path': '/exchanges/{id}', 'path_params': ['id'], 'query_params': ['dex_pair_format'], 'has_body': False}, 'exchanges_id_tickers': {'method': 'GET', 'path': '/exchanges/{id}/tickers', 'path_params': ['id'], 'query_params': ['coin_ids', 'include_exchange_logo', 'page', 'depth', 'order', 'dex_pair_format'], 'has_body': False}, 'exchanges_id_volume_chart': {'method': 'GET', 'path': '/exchanges/{id}/volume_chart', 'path_params': ['id'], 'query_params': ['days'], 'has_body': False}, 'derivatives_tickers': {'method': 'GET', 'path': '/derivatives', 'path_params': [], 'query_params': [], 'has_body': False}, 'derivatives_exchanges': {'method': 'GET', 'path': '/derivatives/exchanges', 'path_params': [], 'query_params': ['order', 'per_page', 'page'], 'has_body': False}, 'derivatives_exchanges_id': {'method': 'GET', 'path': '/derivatives/exchanges/{id}', 'path_params': ['id'], 'query_params': ['include_tickers'], 'has_body': False}, 'derivatives_exchanges_list': {'method': 'GET', 'path': '/derivatives/exchanges/list', 'path_params': [], 'query_params': [], 'has_body': False}, 'entities_list': {'method': 'GET', 'path': '/entities/list', 'path_params': [], 'query_params': ['entity_type', 'per_page', 'page'], 'has_body': False}, 'companies_public_treasury': {'method': 'GET', 'path': '/{entity}/public_treasury/{coin_id}', 'path_params': ['entity', 'coin_id'], 'query_params': ['per_page', 'page', 'order'], 'has_body': False}, 'public_treasury_entity': {'method': 'GET', 'path': '/public_treasury/{entity_id}', 'path_params': ['entity_id'], 'query_params': ['holding_amount_change', 'holding_change_percentage'], 'has_body': False}, 'public_treasury_entity_chart': {'method': 'GET', 'path': '/public_treasury/{entity_id}/{coin_id}/holding_chart', 'path_params': ['entity_id', 'coin_id'], 'query_params': ['days', 'include_empty_intervals'], 'has_body': False}, 'public_treasury_transaction_history': {'method': 'GET', 'path': '/public_treasury/{entity_id}/transaction_history', 'path_params': ['entity_id'], 'query_params': ['per_page', 'page', 'order', 'coin_ids'], 'has_body': False}, 'nfts_list': {'method': 'GET', 'path': '/nfts/list', 'path_params': [], 'query_params': ['order', 'per_page', 'page'], 'has_body': False}, 'nfts_id': {'method': 'GET', 'path': '/nfts/{id}', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'nfts_contract_address': {'method': 'GET', 'path': '/nfts/{asset_platform_id}/contract/{contract_address}', 'path_params': ['asset_platform_id', 'contract_address'], 'query_params': [], 'has_body': False}, 'exchange_rates': {'method': 'GET', 'path': '/exchange_rates', 'path_params': [], 'query_params': [], 'has_body': False}, 'trending_search': {'method': 'GET', 'path': '/search/trending', 'path_params': [], 'query_params': [], 'has_body': False}, 'crypto_global': {'method': 'GET', 'path': '/global', 'path_params': [], 'query_params': [], 'has_body': False}, 'global_defi': {'method': 'GET', 'path': '/global/decentralized_finance_defi', 'path_params': [], 'query_params': [], 'has_body': False}, 'pool_address': {'method': 'GET', 'path': '/onchain/networks/{network}/pools/{address}', 'path_params': ['network', 'address'], 'query_params': ['include', 'include_volume_breakdown', 'include_composition'], 'has_body': False}, 'trending_pools_list': {'method': 'GET', 'path': '/onchain/networks/trending_pools', 'path_params': [], 'query_params': ['include', 'page', 'duration', 'include_gt_community_data'], 'has_body': False}, 'trending_pools_network': {'method': 'GET', 'path': '/onchain/networks/{network}/trending_pools', 'path_params': ['network'], 'query_params': ['include', 'page', 'duration', 'include_gt_community_data'], 'has_body': False}, 'top_pools_network': {'method': 'GET', 'path': '/onchain/networks/{network}/pools', 'path_params': ['network'], 'query_params': ['include', 'page', 'sort', 'include_gt_community_data'], 'has_body': False}}


class GeneratedCoinGeckoConnector(ConnectorSDK):
    connector_id = "coin_gecko"
    display_name = "CoinGecko"
    description = "Generated from CoinGecko Demo API."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeneratedProvider()

    @property
    def node_types(self) -> list[str]:
        return ["coin_gecko"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GeneratedConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Invalid payload: {exc}', retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get('credentials'):
            creds = context['credentials'].get("coin_gecko") or {}
        raw = payload or {}
        op = (operation or '').lower()
        if op in ('', 'execute'):
            op = str(params.operation or '').lower()
        meta = OPERATIONS.get(op)
        if meta is None:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Unsupported operation {operation!r}.', retryable=False)
        path_values = {k: raw.get(k, '') for k in meta['path_params']}
        query = {k: raw[k] for k in meta['query_params'] if raw.get(k) not in (None, '')}
        body = raw.get('body') if meta['has_body'] else None
        result = await self._provider.call(
            creds, meta['method'], meta['path'], path_values, query, body,
            timeout=params.timeout_seconds, what=op,
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {'items': result}
        return {'result': result}

    async def op_list(self, payload=None, context=None):
        return {'output': {'connector_id': self.connector_id, 'operations': sorted(OPERATIONS)}}
