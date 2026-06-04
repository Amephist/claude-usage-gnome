# claude-usage-gnome

GNOME Shell extension that shows your Claude Code token usage and consumption rate in the top panel.

![panel label: ◆ 924.1K/2.00M  374K/h  |w 924.1K/22.20M](https://img.shields.io/badge/panel-◆_924K%2F2M_374K%2Fh_|w_924K%2F22M-informational)

## What it shows

**Panel label** (always visible):
```
◆ 924.1K/2.00M  374K/h  |w 924.1K/22.20M
      ↑period        ↑rate    ↑weekly
```

**Click to expand:**
- Period (~5h window): used / limit with progress bar and ETA
- Weekly (resets Thursday 4am): used / limit, time to reset, ETA
- Current consumption rate (6h rolling window)
- Last hour token count
- Recent daily history

## Requirements

- Fedora / GNOME Shell 46–50
- Wayland or X11
- Python 3.x (standard library only)
- Claude Code CLI (`~/.claude/` directory with session data)

## Installation

```bash
# 1. Clone
git clone https://github.com/Amephist/claude-usage-gnome.git
cd claude-usage-gnome

# 2. Copy to GNOME extensions directory
EXT_DIR=~/.local/share/gnome-shell/extensions/claude-usage@amephist
mkdir -p "$EXT_DIR"
cp extension.js metadata.json claude_stats.py "$EXT_DIR/"

# 3. Add to enabled extensions
gsettings set org.gnome.shell enabled-extensions \
  "$(gsettings get org.gnome.shell enabled-extensions | sed "s/]$/, 'claude-usage@amephist']/")"

# 4. Log out and back in (required on Wayland to load new extensions)
#    On X11 you can restart the shell with Alt+F2 → r
```

After logging back in, verify:
```bash
gnome-extensions info claude-usage@amephist
# Should say: State: ENABLED
```

## Configuration

Create `~/.claude/usage-widget.json` to set your limits:

```json
{
  "daily_budget_tokens": 2000000,
  "weekly_budget_tokens": 20000000,
  "period_hours": 5
}
```

The defaults are rough estimates. **Calibrate them for your plan** — see the section below.

## Calibrating your limits

Claude's usage page (claude.ai) shows percentage-based usage but not the raw token limit. You can infer the real limits by cross-referencing the percentage with locally measured tokens.

**Run a calibration observation:**
1. Open claude.ai and note: period %, weekly %, minutes until reset
2. Run the stats script:
   ```bash
   python3 ~/.local/share/gnome-shell/extensions/claude-usage@amephist/claude_stats.py | python3 -m json.tool
   ```
3. Calculate:
   ```
   period_limit  = period_tokens_measured  / (period_pct  / 100)
   weekly_limit  = weekly_tokens_measured  / (weekly_pct  / 100)
   ```
4. Update `~/.claude/usage-widget.json` with the inferred values

Best results: capture at 40–80% usage on a single model (Sonnet or Opus, not mixed). Repeat 2–3 times and average.

## How it works

`claude_stats.py` reads the JSONL session files in `~/.claude/projects/` where Claude Code records every message with token usage (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`).

**Effective tokens** = `input + output + cache_creation` (cache reads are excluded — they don't count against limits).

The extension runs the script every 30 seconds and updates the panel label.

## Files

| File | Description |
|---|---|
| `extension.js` | GNOME Shell panel widget (GJS / ES modules) |
| `claude_stats.py` | Stats calculator — reads `~/.claude/projects/**/*.jsonl` |
| `metadata.json` | GNOME Shell extension metadata |

## License

MIT
