// Drag-and-drop helpers shared by Sidebar and Canvas (kept out of
// component files so Fast Refresh works).

const DRAG_TYPE = 'application/mat-node'

export function startNodeDrag(e, nodeType) {
  e.dataTransfer.setData(DRAG_TYPE, nodeType)
  e.dataTransfer.effectAllowed = 'move'
}

export function draggedNodeType(e) {
  return e.dataTransfer.getData(DRAG_TYPE)
}
