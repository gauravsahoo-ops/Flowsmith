/**
 * Searchable text for a node/connector in the sidebar and command palette.
 *
 * Operation labels and the words "method"/"methods" are included so a query
 * such as "HubSpot methods" finds the connector even though the node title
 * only says "HubSpot".
 */
export function nodeSearchText(node, prefix = '') {
  if (!node) return prefix
  const operationText = node.operations && typeof node.operations === 'object'
    ? Object.values(node.operations)
      .map((op) => `${op?.display_name || ''} ${op?.description || ''}`)
      .join(' ')
    : ''
  const methodText = node.is_connector || (node.credential_types && node.credential_types.length > 0)
    ? 'methods operations actions'
    : ''
  return [
    prefix,
    node.display_name,
    node.type,
    node.category || '',
    node.description || '',
    operationText,
    methodText,
  ]
    .filter(Boolean)
    .join(' ')
}
