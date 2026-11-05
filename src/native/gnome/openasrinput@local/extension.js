import Cairo from 'cairo';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import PangoCairo from 'gi://PangoCairo';
import St from 'gi://St';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Config from 'resource:///org/gnome/shell/misc/config.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { HEIGHT, positionPanel, selectMonitor, validateFrame, waveLevels } from './panel.mjs';

const SERVICE = 'org.openasrinput.Panel';
const XML = `<node><interface name="org.openasrinput.Panel1">
  <method name="Show"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="Hide"/>
  <method name="Describe"><arg type="s" direction="out"/></method>
</interface></node>`;

function color(cr, rgb) {
  cr.setSourceRGB(((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255);
}
function rounded(cr, x, y, width, height, radius) {
  cr.newSubPath();
  cr.arc(x + width - radius, y + radius, radius, -Math.PI / 2, 0);
  cr.arc(x + width - radius, y + height - radius, radius, 0, Math.PI / 2);
  cr.arc(x + radius, y + height - radius, radius, Math.PI / 2, Math.PI);
  cr.arc(x + radius, y + radius, radius, Math.PI, Math.PI * 1.5);
  cr.closePath();
}
function label(cr, text, x, y, size, rgb, width = -1) {
  const layout = PangoCairo.create_layout(cr);
  const font = Pango.FontDescription.from_string('Sans');
  font.set_absolute_size(size * Pango.SCALE);
  layout.set_font_description(font);
  layout.set_text(text, -1);
  layout.set_single_paragraph_mode(true);
  layout.set_auto_dir(false);
  if (width >= 0) {
    layout.set_width(width * Pango.SCALE);
    layout.set_ellipsize(Pango.EllipsizeMode.START);
  }
  color(cr, rgb);
  cr.moveTo(x, y);
  PangoCairo.show_layout(cr, layout);
}

export default class VoicePanelExtension extends Extension {
  enable() {
    this._frame = null;
    this._sender = null;
    this._senderWatch = 0;
    this._frames = 0;
    this._targetSignals = [];
    this._actor = new St.DrawingArea({ reactive: false, can_focus: false, visible: false });
    this._repaint = this._actor.connect('repaint', () => this._paint());
    Main.layoutManager.addChrome(this._actor, {
      // GNOME 50 removed this option. Earlier X11 shells need it to keep
      // the status card out of the stage's input region.
      ...(Number.parseInt(Config.PACKAGE_VERSION, 10) < 50 ? { affectsInputRegion: false } : {}),
      trackFullscreen: false
    });
    this._focus = global.display.connect('notify::focus-window', () => {
      if (this._targetWindow !== global.display.focus_window) this._hide();
      else this._relayout();
    });
    this._monitors = Main.layoutManager.connect('monitors-changed', () => this._relayout());
    this._workareas = global.display.connect('workareas-changed', () => this._relayout());
    this._monitorEntered = global.display.connect(
      'window-entered-monitor',
      (_display, _index, window) => {
        if (window === this._targetWindow) this._relayout();
      }
    );
    this._session = Main.sessionMode.connect('updated', () => {
      if (Main.sessionMode.isLocked || Main.sessionMode.isGreeter) this._hide();
      else this._relayout();
    });
    this._export = Gio.DBusExportedObject.wrapJSObject(XML, this);
    this._export.export(Gio.DBus.session, '/org/openasrinput/Panel');
    this._name = Gio.bus_own_name_on_connection(
      Gio.DBus.session,
      SERVICE,
      Gio.BusNameOwnerFlags.NONE,
      null,
      null
    );
  }

  ShowAsync([payload], invocation) {
    try {
      const frame = validateFrame(payload);
      if (Main.sessionMode.isLocked || Main.sessionMode.isGreeter)
        throw new Error('Session unavailable');
      const sender = invocation.get_sender();
      if (sender !== this._sender) {
        if (this._senderWatch) Gio.bus_unwatch_name(this._senderWatch);
        this._sender = sender;
        this._senderWatch = Gio.bus_watch_name_on_connection(
          Gio.DBus.session,
          sender,
          Gio.BusNameWatcherFlags.NONE,
          null,
          () => this._hide()
        );
      }
      this._frame = frame;
      this._setTargetWindow(global.display.focus_window);
      this._frames++;
      this._relayout();
      invocation.return_value(new GLib.Variant('(b)', [true]));
    } catch (error) {
      invocation.return_dbus_error('org.openasrinput.InvalidFrame', error.message);
    }
  }

  HideAsync(_parameters, invocation) {
    if (invocation.get_sender() === this._sender) this._hide();
    invocation.return_value(null);
  }

  Describe() {
    return JSON.stringify({
      protocolVersion: 1,
      capabilities: ['panel-layout-v2'],
      backend: 'gnome-shell',
      visible: this._actor.visible,
      frames: this._frames,
      reactive: this._actor.reactive,
      canFocus: this._actor.can_focus,
      position: this._frame ? this._frame.position : null,
      transparency: this._frame ? this._frame.transparency : null,
      opacity: this._actor.opacity,
      geometry: this._geometry == null ? null : this._geometry,
      monitorIndex: this._monitorIndex == null ? null : this._monitorIndex,
      monitors: Main.layoutManager.monitors.map(({ x, y, width, height }) => ({
        x,
        y,
        width,
        height
      }))
    });
  }

  _hide() {
    this._frame = null;
    this._setTargetWindow(null);
    this._monitorIndex = null;
    this._actor.hide();
  }

  _setTargetWindow(window) {
    if (window === this._targetWindow) return;
    for (const id of this._targetSignals) this._targetWindow.disconnect(id);
    this._targetSignals = [];
    this._targetWindow = window;
    if (!window) return;
    for (const signal of ['position-changed', 'size-changed'])
      this._targetSignals.push(window.connect(signal, () => this._relayout()));
    this._targetSignals.push(window.connect('unmanaged', () => this._hide()));
  }

  _relayout() {
    if (!this._frame) return;
    // Shell's cached caret belongs to its IBus path, not necessarily to the
    // Fcitx client. Borrowing it can place this frame on the previous monitor.
    const shellCursor = null;
    const monitor = selectMonitor(
      Main.layoutManager.monitors,
      this._frame,
      this._targetWindow ? this._targetWindow.get_monitor() : undefined,
      global.display.get_current_monitor(),
      shellCursor,
      this._targetWindow ? this._targetWindow.get_frame_rect() : undefined
    );
    if (monitor < 0) {
      this._actor.hide(); // Preserve the frame during a transient display reconfiguration.
      return;
    }
    this._monitorIndex = monitor;
    const area = global.workspace_manager.get_active_workspace().get_work_area_for_monitor(monitor);
    this._geometry = positionPanel(this._frame, area, shellCursor);
    this._actor.opacity = this._geometry.opacity;
    this._actor.set_position(this._geometry.x, this._geometry.y);
    this._actor.set_size(this._geometry.width, this._geometry.height);
    if (this._geometry.visible) this._actor.show();
    else this._actor.hide();
    this._actor.queue_repaint();
  }

  _paint() {
    if (!this._frame) return;
    const f = this._frame,
      p = f.colors,
      w = this._geometry.width / this._geometry.scale;
    const cr = this._actor.get_context();
    cr.scale(this._geometry.scale, this._geometry.scale);
    cr.setOperator(Cairo.Operator.CLEAR);
    cr.paint();
    cr.setOperator(Cairo.Operator.OVER);
    rounded(cr, 1, 1, w - 2, HEIGHT - 2, f.radius - 1);
    color(cr, p[0]);
    cr.fillPreserve();
    color(cr, p[2]);
    cr.setLineWidth(1);
    cr.stroke();
    rounded(cr, 20, 16, 32, 32, 10);
    color(cr, p[8]);
    cr.fill();
    rounded(cr, 32, 22, 8, 13, 4);
    color(cr, p[7]);
    cr.fill();
    cr.setLineWidth(1.7);
    cr.arc(36, 30, 7, 0, Math.PI);
    cr.moveTo(36, 37);
    cr.lineTo(36, 41);
    cr.moveTo(32, 41);
    cr.lineTo(40, 41);
    cr.stroke();
    const levels = waveLevels(f.wave),
      gradient = new Cairo.LinearGradient(68, 0, w - 126, 0);
    for (const [stop, rgb] of [
      [0, p[6]],
      [1, p[7]]
    ])
      gradient.addColorStopRGB(
        stop,
        ((rgb >> 16) & 255) / 255,
        ((rgb >> 8) & 255) / 255,
        (rgb & 255) / 255
      );
    cr.setSource(gradient);
    for (let index = 0; index < 56; index++) {
      const position = (index * (levels.length - 1)) / 55,
        left = Math.floor(position),
        fraction = position - left;
      const energy =
        levels[left] * (1 - fraction) + levels[Math.min(left + 1, levels.length - 1)] * fraction;
      const height = 3 + energy * 25;
      rounded(cr, 70 + (index * (w - 198)) / 55, 32 - height / 2, 3.5, height, 1.75);
      cr.fill();
    }
    const states = {
      listening: '录音中',
      connecting: '录音缓存',
      'edit-connecting': '指令缓存',
      'edit-listening': '听取指令',
      'edit-pausing': '识别指令',
      'edit-processing': '修改中',
      pausing: '收尾中',
      'needs-config': '需设置'
    };
    rounded(cr, w - 102, 20, 80, 25, 12.5);
    color(cr, f.state === 'listening' ? p[9] : p[8]);
    cr.fill();
    label(cr, states[f.state], w - 85, 23, 13, f.state === 'listening' ? p[10] : p[7]);
    rounded(cr, 20, 58, w - 40, 43, 9);
    color(cr, p[1]);
    cr.fill();
    label(
      cr,
      f.text || '等待语音识别…',
      34,
      68,
      f.fontSize,
      f.text ? p[3] : p[4],
      Math.floor(w - 138)
    );
    label(cr, `${f.words} / 20`, w - 82, 71, 12, p[4]);
    const compact = w < 620;
    let x = 24;
    const key = (name, hint, keyWidth, hintWidth) => {
      rounded(cr, x, 117, keyWidth, 22, 5);
      color(cr, p[1]);
      cr.fill();
      label(cr, name, x + 7, 120, 11, p[5]);
      label(cr, hint, x + keyWidth + 8, 119, 12, p[4]);
      x += keyWidth + hintWidth + (compact ? 16 : 28);
    };
    key(
      compact ? '⇧ Space' : 'Shift + Space',
      f.state === 'needs-config' ? '重试' : compact ? '启停' : '暂停 / 恢复',
      compact ? 62 : 96,
      compact ? 30 : 70
    );
    if (f.state === 'needs-config')
      label(cr, '请打开设置检查 Portal 连接与识别档案', x, 119, 12, p[4], Math.floor(w - x - 24));
    else {
      key('Enter', '收尾', compact ? 42 : 46, 30);
      key('Esc', '取消', compact ? 32 : 34, 30);
      if (w >= 720) label(cr, 'Alt + Z 也可启停', x, 119, 11, p[4], Math.floor(w - x - 24));
    }
    cr.$dispose();
  }

  disable() {
    this._hide();
    if (this._senderWatch) Gio.bus_unwatch_name(this._senderWatch);
    Gio.bus_unown_name(this._name);
    this._export.unexport();
    global.display.disconnect(this._focus);
    global.display.disconnect(this._workareas);
    global.display.disconnect(this._monitorEntered);
    Main.layoutManager.disconnect(this._monitors);
    Main.sessionMode.disconnect(this._session);
    Main.layoutManager.removeChrome(this._actor);
    this._actor.disconnect(this._repaint);
    this._actor.destroy();
  }
}
