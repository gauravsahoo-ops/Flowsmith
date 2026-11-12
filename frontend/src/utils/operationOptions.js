/**
 * Build searchable option metadata for a node's operation/method selector.
 *
 * The selector lists operation display names, but users naturally search for
 * "<Connector> methods" or an operation key. The aliases make that search
 * match without changing the visible labels.
 */
export function buildOperationSearchOptions(operationKeys, operationsMeta, connectorName) {
  return (operationKeys || []).map((key) => {
    const op = (operationsMeta || {})[key] || {}
    return {
      value: key,
      label: op.display_name || key.replace(/_/g, ' ').toUpperCase(),
      description: op.description || `${connectorName} method`,
      aliases: [
        connectorName,
        `${connectorName} method`,
        `${connectorName} methods`,
        key,
        key.replace(/_/g, ' '),
        'operation',
        'method',
      ],
    }
  })
}
