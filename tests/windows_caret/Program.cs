using System.Drawing;
using OpenASRInput;

void Check(bool value, string message) { if (!value) throw new Exception(message); }
Target Read() => Target.Read() ?? throw new Exception("Expected editable target");
Scene.Reset();
var target = Read();
Check(target.CaretKnown && target.Caret == new Rectangle(320, 260, 1, 28),
    "multiline selection anchors at trailing edge of final character, not first selected line");
Check(Scene.Start == 0 && Scene.End == 3, "geometry queries do not modify user's selection");
Scene.Start = Scene.End = 1;
Check(Read().Caret == new Rectangle(220, 200, 1, 28), "collapsed middle caret uses next character leading edge");
Scene.Start = Scene.End = 0;
Check(Read().Caret == new Rectangle(200, 200, 1, 28), "start of text does not use editor origin");
Scene.Reset();
Scene.Rtl = true;
Check(Read().Caret.Left == 300, "RTL final character uses left trailing edge");
Scene.Reset();
Scene.NativeCaret = true;
Scene.NativeBounds = new Native.Rect { Left = 140, Top = 160, Right = 142, Bottom = 188 };
Check(Read().Caret == new Rectangle(240, 260, 2, 28), "valid native caret is mapped once from client to screen");
Scene.NativeBounds = new Native.Rect { Left = 0, Top = 0, Right = 1, Bottom = 1 };
Check(Read().Caret == target.Caret, "native caret outside focused editor falls back to UIA");
Scene.NativeBounds = default;
Check(Read().Caret == target.Caret, "zero native caret does not suppress UIA fallback");
Scene.ThrowCollapsed = true;
Check(Read().Caret == target.Caret, "provider that rejects collapsed rectangles still uses adjacent character");
Scene.NoGeometry = true;
var fallback = Read();
Check(!fallback.CaretKnown && fallback.Caret.Left == Scene.Editor.Left && fallback.Caret.Bottom == Scene.Editor.Bottom,
    "missing geometry is explicitly an editor-edge fallback");
Scene.GeometryReads = 0;
var identity = Target.Read(includeGeometry: false);
Check(target.Same(identity) && Scene.GeometryReads == 0,
    "per-character authorization validates identity without any geometry calls");
Scene.ReadOnly = true;
Check(Target.Read() == null && Target.Read(includeGeometry: false) == null,
    "both positioning and authorization reject readonly targets");
Console.WriteLine("PASS headless Target: multiline selection endpoint, caret start/middle/end, RTL, native validation, missing bounds and geometry-free identity checks");
