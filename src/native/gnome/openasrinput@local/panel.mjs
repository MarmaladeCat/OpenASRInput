// Data/geometry contract shared by the Shell renderer and isolated Node tests.
export const HEIGHT = 156;

export function validateFrame(payload) {
  if (typeof payload !== 'string' || payload.length > 16384) throw new Error('Invalid frame size');
  const frame = JSON.parse(payload);
  if (frame.position == null) frame.position = 'cursor';
  if (frame.transparency == null) frame.transparency = 0;
  if (
    ![
      'cursor',
      'hidden',
      'top',
      'bottom',
      'top-left',
      'top-right',
      'bottom-left',
      'bottom-right'
    ].includes(frame.position) ||
    !Number.isInteger(frame.transparency) ||
    frame.transparency < 0 ||
    frame.transparency > 100
  )
    throw new Error('Invalid panel placement or transparency');
  if (frame.version !== 1) throw new Error('Unsupported panel protocol');
  for (const [key, low, high] of [
    ['width', 480, 960],
    ['scale', 0.8, 1.5],
    ['fontSize', 12, 22],
    ['radius', 8, 24],
    ['words', 0, 20]
  ]) {
    if (!Number.isFinite(frame[key]) || frame[key] < low || frame[key] > high)
      throw new Error('Invalid ' + key);
  }
  if (
    ![
      'connecting',
      'listening',
      'pausing',
      'edit-connecting',
      'edit-listening',
      'edit-pausing',
      'edit-processing',
      'needs-config'
    ].includes(frame.state)
  )
    throw new Error('Invalid state');
  if (
    typeof frame.text !== 'string' ||
    frame.text.length > 4096 ||
    typeof frame.wave !== 'string' ||
    frame.wave.length > 256
  )
    throw new Error('Invalid text');
  if (
    !Array.isArray(frame.colors) ||
    frame.colors.length !== 11 ||
    !frame.colors.every((color) => Number.isInteger(color) && color >= 0 && color <= 0xffffff)
  )
    throw new Error('Invalid palette');
  if (
    !Array.isArray(frame.cursor) ||
    frame.cursor.length !== 4 ||
    !frame.cursor.every(Number.isFinite) ||
    typeof frame.globalCursor !== 'boolean'
  )
    throw new Error('Invalid cursor');
  return frame;
}

export function positionPanel(frame, workArea, shellCursor = null) {
  const margin = Math.min(12, Math.max(0, (Math.min(workArea.width, workArea.height) - 1) / 4));
  const scale = Math.min(
    frame.scale,
    Math.max(1, workArea.width - margin * 2) / 320,
    Math.max(1, workArea.height - margin * 2) / HEIGHT
  );
  const width = Math.max(1, Math.floor(Math.min(frame.width * scale, workArea.width - margin * 2))),
    height = Math.floor(HEIGHT * scale);
  const cursor =
    shellCursor ||
    (frame.globalCursor
      ? { x: frame.cursor[0], y: frame.cursor[1], width: frame.cursor[2], height: frame.cursor[3] }
      : null);
  let x = workArea.x + (workArea.width - width) / 2;
  let y = workArea.y + workArea.height - height - 16;
  if (cursor && (!frame.position || frame.position === 'cursor')) {
    x = cursor.x;
    y = cursor.y + cursor.height + 8;
    if (y + height > workArea.y + workArea.height - 12) y = cursor.y - height - 8;
  }
  if (frame.position && frame.position !== 'cursor') {
    if (frame.position.startsWith('top')) y = workArea.y + margin;
    if (frame.position.endsWith('left')) x = workArea.x + margin;
    if (frame.position.endsWith('right')) x = workArea.x + workArea.width - width - margin;
  }
  return {
    visible: frame.position !== 'hidden' && frame.transparency !== 100,
    opacity: Math.round(255 * (1 - (frame.transparency || 0) / 100)),
    x: Math.max(workArea.x + margin, Math.min(x, workArea.x + workArea.width - width - margin)),
    y: Math.max(workArea.y + margin, Math.min(y, workArea.y + workArea.height - height - margin)),
    width,
    height,
    scale
  };
}

// Relative Wayland caret coordinates cannot select a monitor. In that case the
// focused window, not the mouse pointer, determines where the preview belongs.
export function selectMonitor(
  monitors,
  frame,
  focusedIndex,
  pointerIndex,
  shellCursor = null,
  focusedBounds = null
) {
  const cursor =
    shellCursor ||
    (frame.globalCursor && frame.cursor[3] > 0 ? { x: frame.cursor[0], y: frame.cursor[1] } : null);
  // A stale/global physical-pixel caret can point at a different logical monitor
  // after focus changes, scaling or a window move. Only trust it if it belongs
  // to the current input window. Spanning windows still use the caret's monitor.
  const insideTarget =
    !focusedBounds ||
    (cursor &&
      cursor.x >= focusedBounds.x &&
      cursor.x < focusedBounds.x + focusedBounds.width &&
      cursor.y >= focusedBounds.y &&
      cursor.y < focusedBounds.y + focusedBounds.height);
  if (cursor && insideTarget) {
    const found = monitors.findIndex(
      (m) =>
        cursor.x >= m.x && cursor.x < m.x + m.width && cursor.y >= m.y && cursor.y < m.y + m.height
    );
    if (found >= 0) return found;
  }
  if (Number.isInteger(focusedIndex) && monitors[focusedIndex]) return focusedIndex;
  if (Number.isInteger(pointerIndex) && monitors[pointerIndex]) return pointerIndex;
  return monitors.length ? 0 : -1;
}

export function waveLevels(wave) {
  const levels = Array.from(wave, (char) => char.codePointAt(0))
    .filter((code) => code >= 0x2581 && code <= 0x2588)
    .map((code) => (code - 0x2581) / 7);
  return levels.length ? levels : [0];
}
