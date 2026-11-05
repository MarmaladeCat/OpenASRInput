import assert from 'node:assert/strict';
import {
  positionPanel,
  selectMonitor,
  validateFrame,
  waveLevels
} from '../src/native/gnome/openasrinput@local/panel.mjs';

const frame = {
  version: 1,
  text: '公园。',
  wave: '▁▂▄▆█',
  state: 'listening',
  words: 1,
  width: 760,
  scale: 1,
  fontSize: 15,
  radius: 18,
  colors: Array(11).fill(0xffffff),
  globalCursor: false,
  cursor: [100, 200, 2, 24]
};
assert.deepEqual(validateFrame(JSON.stringify(frame)), {
  ...frame,
  position: 'cursor',
  transparency: 0
});
assert.throws(() => validateFrame(JSON.stringify({ ...frame, transparency: 101 })));
assert.throws(() => validateFrame(JSON.stringify({ ...frame, position: 'invalid' })));
const top = positionPanel(
  { ...frame, position: 'top-right' },
  { x: -1920, y: -100, width: 1920, height: 1080 }
);
assert.equal(top.x, -772);
assert.equal(top.y, -88);
const monitor = { x: 1920, y: 0, width: 1200, height: 900 };
const fixed = positionPanel(frame, monitor);
assert.equal(fixed.x, 2140);
assert.equal(fixed.y, 728); // Relative cursor must not be interpreted as screen coordinates.
const caret = positionPanel(frame, monitor, { x: 2900, y: 840, width: 2, height: 24 });
assert.equal(caret.x, 2348); // Clamp within the active monitor.
assert.equal(caret.y, 676); // Flip above a caret at the bottom.
const scaled = positionPanel({ ...frame, scale: 1.5 }, { x: 0, y: 0, width: 800, height: 600 });
assert.ok(scaled.width <= 776);
assert.equal(scaled.scale, 1.5, 'narrow monitors compact the layout without shrinking the font');
assert.equal(scaled.height, 234);
const screens = [{ x: -1920, y: 0, width: 1920, height: 1080 }, monitor];
assert.equal(selectMonitor(screens, frame, 1, 0), 1, 'focus monitor takes priority over mouse');
assert.equal(
  selectMonitor(screens, { ...frame, globalCursor: true, cursor: [-100, 10, 1, 20] }, 1, 1),
  0
);
assert.equal(selectMonitor([], frame, 1, 1), -1);
assert.equal(
  selectMonitor(screens, { ...frame, globalCursor: true, cursor: [-100, 10, 0, 0] }, 1, 0),
  1
);
assert.equal(
  selectMonitor(
    screens,
    { ...frame, globalCursor: true, cursor: [-100, 10, 1, 20] },
    1,
    0,
    null,
    monitor
  ),
  1,
  'global coordinates outside the focused window must not choose another screen'
);
assert.equal(
  selectMonitor(screens, { ...frame, globalCursor: true, cursor: [-100, 10, 1, 20] }, 1, 1, null, {
    x: -300,
    y: 0,
    width: 3000,
    height: 500
  }),
  0,
  'a spanning window still follows the actual caret screen'
);
const tiny = positionPanel(frame, { x: -10, y: -10, width: 10, height: 8 });
assert.ok(tiny.scale > 0 && tiny.width > 0 && tiny.x >= -10 && tiny.y >= -10);
assert.deepEqual(waveLevels('▁█'), [0, 1]);
assert.deepEqual(waveLevels(''), [0]);
for (const patch of [
  { version: 2 },
  { width: 100000 },
  { scale: null },
  { state: 'idle' },
  { colors: [] },
  { cursor: [0] },
  { text: 'x'.repeat(4097) }
])
  assert.throws(() => validateFrame(JSON.stringify({ ...frame, ...patch })));
console.log(
  'PASS Wayland panel: validated frames, relative/global caret placement, monitor bounds, scale, audio energy'
);
