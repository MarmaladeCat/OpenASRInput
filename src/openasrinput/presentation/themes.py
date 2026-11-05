"""Canonical palettes shared by the settings preview and native IPC consumer."""

COLOR_FIELDS = (
    "background",
    "surface",
    "border",
    "text",
    "muted",
    "keyText",
    "waveStart",
    "accent",
    "accentBackground",
    "successBackground",
    "successText",
)

THEMES = {
    "github": {
        "title": "GitHub",
        "description": "清晰克制的中性色与蓝色强调。",
        "light": (
            "ffffff",
            "f6f8fa",
            "d0d7de",
            "1f2328",
            "656d76",
            "57606a",
            "2da9a0",
            "0969da",
            "ddf4ff",
            "dafbe1",
            "1a7f37",
        ),
        "dark": (
            "0d1117",
            "161b22",
            "30363d",
            "e6edf3",
            "8b949e",
            "b1bac4",
            "3fb9a8",
            "58a6ff",
            "172d45",
            "163325",
            "3fb950",
        ),
    },
    "material": {
        "title": "Material",
        "description": "柔和圆角、浅色表面与青绿到靛蓝的操作色。",
        "light": (
            "ffffff",
            "f8fafc",
            "dbe4ee",
            "1e293b",
            "64748b",
            "475569",
            "38b8ab",
            "6366f1",
            "eef2ff",
            "ecfdf5",
            "15803d",
        ),
        "dark": (
            "171923",
            "222533",
            "363b50",
            "edf0f9",
            "a1a8bd",
            "c3c9dc",
            "5dd6c1",
            "a5a6ff",
            "30314f",
            "193b32",
            "6ee7b7",
        ),
    },
    "nord": {
        "title": "Nord · 冰川蓝",
        "description": "雾蓝与冰川青，安静清爽的北欧配色。",
        "light": (
            "eceff4",
            "e5e9f0",
            "c2cbd9",
            "2e3440",
            "596579",
            "4c566a",
            "8fbcbb",
            "5e81ac",
            "d8e4ef",
            "dce9dd",
            "4d7151",
        ),
        "dark": (
            "2e3440",
            "3b4252",
            "4c566a",
            "eceff4",
            "b0bbcc",
            "d8dee9",
            "8fbcbb",
            "88c0d0",
            "40556a",
            "3e554c",
            "a3be8c",
        ),
    },
    "rose-pine": {
        "title": "Rosé Pine · 松木玫瑰",
        "description": "奶油纸色与柔和玫瑰，暗色模式呈现深紫夜色。",
        "light": (
            "faf4ed",
            "fffaf3",
            "e5dacf",
            "575279",
            "797593",
            "6e6a86",
            "56949f",
            "b4637a",
            "f2dfdf",
            "e2ebe1",
            "4b7462",
        ),
        "dark": (
            "191724",
            "26233a",
            "403d52",
            "e0def4",
            "a09bb7",
            "bcb8d1",
            "9ccfd8",
            "ebbcba",
            "403040",
            "2d4545",
            "9ccfd8",
        ),
    },
}


def palette(theme, mode):
    return dict(zip(COLOR_FIELDS, ("#" + value for value in THEMES[theme][mode])))


def public_themes():
    return [
        {
            "id": key,
            "title": value["title"],
            "description": value["description"],
            "light": palette(key, "light"),
            "dark": palette(key, "dark"),
        }
        for key, value in THEMES.items()
    ]
