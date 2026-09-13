/** Pure helpers used by gestures and exports. Coordinates remain in map units. */
export function viewPoint(clientX, clientY, rect, view) {
  return [view.x + (clientX - rect.left) / rect.width * view.w,
    view.y + (clientY - rect.top) / rect.height * view.h];
}
export function scaledPoint(point, oldSize, newSize) {
  return [point[0] * newSize[0] / oldSize[0], point[1] * newSize[1] / oldSize[1]];
}
export function escapeXML(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[c]));
}
