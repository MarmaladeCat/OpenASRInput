// Execute the real extension lifecycle with a deterministic Shell facade.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {
  HEIGHT,
  positionPanel,
  selectMonitor,
  validateFrame,
  waveLevels
} from '../src/native/gnome/openasrinput@local/panel.mjs';

function signals(object = {}) {
  const handlers = new Map();
  return Object.assign(object, {
    connect(name, callback) {
      handlers.set(name, callback);
      return name;
    },
    disconnect(name) {
      handlers.delete(name);
    },
    emit(name) {
      handlers.get(name)?.();
    }
  });
}
class Actor {
  constructor(properties) {
    Object.assign(this, properties);
  }
  connect() {
    return 1;
  }
  disconnect() {}
  destroy() {}
  queue_repaint() {}
  set_position(x, y) {
    this.x = x;
    this.y = y;
  }
  set_size(width, height) {
    this.width = width;
    this.height = height;
  }
  show() {
    this.visible = true;
  }
  hide() {
    this.visible = false;
  }
}
let focusedMonitor = 1;
const window = signals({
  get_monitor: () => focusedMonitor,
  get_frame_rect: () => layout.monitors[focusedMonitor]
});
const display = signals({ focus_window: window, get_current_monitor: () => 0 });
const shellConfig = { PACKAGE_VERSION: '50.4' };
const layout = signals({
  monitors: [
    { x: 0, y: 0, width: 1920, height: 1080 },
    { x: -1280, y: 0, width: 1280, height: 1024 }
  ],
  addChrome(actor, parameters) {
    // GNOME 50 validates these options; affectsInputRegion was removed.
    const allowed = ['affectsStruts', 'trackFullscreen'];
    if (Number.parseInt(shellConfig.PACKAGE_VERSION, 10) < 50) {
      allowed.push('affectsInputRegion');
      assert.equal(parameters.affectsInputRegion, false);
    }
    for (const name of Object.keys(parameters))
      assert.ok(allowed.includes(name), `Unknown chrome option: ${name}`);
    assert.equal(actor.reactive, false);
    assert.equal(actor.can_focus, false);
  },
  removeChrome() {}
});
const session = signals({ isLocked: false, isGreeter: false });
const context = vm.createContext({
  HEIGHT,
  positionPanel,
  selectMonitor,
  validateFrame,
  waveLevels,
  Extension: class {},
  Config: shellConfig,
  St: { DrawingArea: Actor },
  GLib: { Variant: class {} },
  Gio: {
    DBusExportedObject: { wrapJSObject: () => ({ export() {}, unexport() {} }) },
    DBus: { session: {} },
    BusNameOwnerFlags: { NONE: 0 },
    BusNameWatcherFlags: { NONE: 0 },
    bus_own_name_on_connection: () => 1,
    bus_watch_name_on_connection: () => 2,
    bus_unwatch_name() {},
    bus_unown_name() {}
  },
  Main: {
    layoutManager: layout,
    sessionMode: session,
    inputMethod: { currentFocus: true, _cursorRect: { x: 1200, y: 300, width: 1, height: 20 } }
  },
  global: {
    display,
    workspace_manager: {
      get_active_workspace: () => ({
        get_work_area_for_monitor: (index) => layout.monitors[index]
      })
    }
  }
});
let source = fs.readFileSync(
  process.argv[2] ||
    new URL('../src/native/gnome/openasrinput@local/extension.js', import.meta.url),
  'utf8'
);
source = source
  .replace(/^import .*;$/gm, '')
  .replace('export default class VoicePanelExtension', 'globalThis.VoicePanelExtension = class');
if (process.argv[2]) {
  context.imports = {
    cairo: {},
    gi: { Gio: context.Gio, GLib: context.GLib, St: context.St },
    misc: { config: shellConfig },
    ui: { main: context.Main }
  };
  shellConfig.PACKAGE_VERSION = '42.9';
  source += '\nglobalThis.VoicePanelExtension = VoicePanelExtension;';
}
vm.runInContext(source, context);
const extension = new context.VoicePanelExtension();
extension.enable();
const frame = {
  version: 1,
  text: '',
  wave: '▁',
  state: 'connecting',
  words: 0,
  width: 760,
  scale: 1,
  fontSize: 15,
  radius: 18,
  colors: Array(11).fill(0xffffff),
  globalCursor: false,
  cursor: [10, 10, 1, 20]
};
extension.ShowAsync([JSON.stringify(frame)], {
  get_sender: () => ':native',
  return_value() {},
  return_dbus_error(_name, message) {
    throw new Error(message);
  }
});
assert.equal(extension._actor.visible, true);
const invocation = {
  get_sender: () => ':native',
  return_value() {},
  return_dbus_error(_name, message) {
    throw new Error(message);
  }
};
// Same content, only hot presentation settings change; no focus/audio transition.
extension.ShowAsync(
  [JSON.stringify({ ...frame, position: 'top-right', transparency: 50 })],
  invocation
);
assert.equal(extension._actor.x, -772);
assert.equal(extension._actor.y, 12);
assert.equal(extension._actor.opacity, 128);
extension.ShowAsync(
  [JSON.stringify({ ...frame, position: 'hidden', transparency: 50 })],
  invocation
);
assert.equal(extension._actor.visible, false);
extension.ShowAsync(
  [JSON.stringify({ ...frame, position: 'bottom-left', transparency: 25 })],
  invocation
);
assert.equal(extension._actor.visible, true);
assert.equal(extension._actor.x, -1268);
assert.equal(extension._actor.y, 852);
assert.equal(extension._actor.opacity, 191);
assert.ok(extension.Describe().includes('panel-layout-v2'));
assert.ok(
  extension._actor.x < 0,
  'stale IBus caret / mouse monitor must not override focused Fcitx window'
);
// Unknown/stale global coordinates must not pick the previous or mouse monitor.
extension.ShowAsync(
  [JSON.stringify({ ...frame, globalCursor: true, cursor: [0, 0, 0, 0], position: 'bottom' })],
  invocation
);
assert.equal(JSON.parse(extension.Describe()).monitorIndex, 1);
extension.ShowAsync(
  [
    JSON.stringify({ ...frame, globalCursor: true, cursor: [1200, 300, 1, 20], position: 'bottom' })
  ],
  invocation
);
assert.equal(JSON.parse(extension.Describe()).monitorIndex, 1);
// Moving the same input window needs no new audio/SHOW or focus change.
focusedMonitor = 0;
window.emit('position-changed');
assert.equal(JSON.parse(extension.Describe()).monitorIndex, 0);
assert.equal(extension._actor.x, (1920 - frame.width) / 2);
assert.equal(extension._actor.y, 1080 - HEIGHT - 16);
focusedMonitor = 1;
window.emit('size-changed');
assert.equal(JSON.parse(extension.Describe()).monitorIndex, 1);
layout.monitors[1] = { x: 1920, y: 400, width: 1024, height: 768 };
layout.emit('monitors-changed');
assert.equal(extension._actor.visible, true);
assert.ok(extension._actor.x >= 1920 && extension._actor.y >= 400);
display.emit('notify::focus-window');
assert.equal(
  extension._actor.visible,
  true,
  'redundant focus notification must not hide the frame'
);
const previous = layout.monitors;
layout.monitors = [];
layout.emit('monitors-changed');
assert.equal(extension._actor.visible, false);
layout.monitors = previous;
layout.emit('monitors-changed');
assert.equal(extension._actor.visible, true, 'hotplug recovery must not require new audio/text');
display.focus_window = {};
display.emit('notify::focus-window');
assert.equal(extension._actor.visible, false);
extension.disable();
for (const version of ['45.0', '49.3']) {
  shellConfig.PACKAGE_VERSION = version;
  const legacy = new context.VoicePanelExtension();
  legacy.enable();
  legacy.disable();
}
console.log(
  'PASS GNOME lifecycle: focused monitor, stale IBus caret isolation, hotplug recovery and genuine focus loss'
);
