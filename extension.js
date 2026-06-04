import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const REFRESH_SECONDS = 30;
const CONFIG_PATH = GLib.get_home_dir() + '/.claude/usage-widget.json';

const ClaudeIndicator = GObject.registerClass(
class ClaudeIndicator extends PanelMenu.Button {
    _init(scriptPath) {
        super._init(0.0, 'Claude Usage', false);
        this._scriptPath = scriptPath;
        this._stats = null;

        this._label = new St.Label({
            text: '◆ …',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-size: 12px;',
        });
        this.add_child(this._label);

        this._buildMenu();
        this._refresh();

        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, REFRESH_SECONDS, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _buildMenu() {
        // — Period (5h window) —
        this._periodHeader = this._addItem('Período actual (5h)', true);
        this._periodUsedItem = this._addItem('  Usado: …');
        this._periodRemainingItem = this._addItem('  Restante: …');
        this._periodBarItem = this._addItem('  …');
        this._periodEtaItem = this._addItem('  ETA: …');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // — Weekly —
        this._weekHeader = this._addItem('Semana (reinicia jue 4am)', true);
        this._weekUsedItem = this._addItem('  Usado: …');
        this._weekRemainingItem = this._addItem('  Restante: …');
        this._weekBarItem = this._addItem('  …');
        this._weekResetItem = this._addItem('  Reinicia en: …');
        this._weekEtaItem = this._addItem('  ETA agotarse: …');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // — Rate —
        this._rateHeader = this._addItem('Tasa de consumo', true);
        this._rateItem = this._addItem('  Actual: …');
        this._lastHourItem = this._addItem('  Última hora: …');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // — History —
        this._histHeader = this._addItem('Días recientes', true);
        this._histItem = this._addItem('  …');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._updatedItem = this._addItem('Actualizado: nunca');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._toggleItem = new PopupMenu.PopupMenuItem('⇄  Modo: raw');
        this._toggleItem.connect('activate', () => this._toggleMode());
        this.menu.addMenuItem(this._toggleItem);

        let refreshItem = new PopupMenu.PopupMenuItem('↻  Actualizar ahora');
        refreshItem.connect('activate', () => this._refresh());
        this.menu.addMenuItem(refreshItem);
    }

    _addItem(text, bold = false) {
        let item = new PopupMenu.PopupMenuItem(text, { reactive: false });
        if (bold)
            item.label.set_style('font-weight: bold;');
        this.menu.addMenuItem(item);
        return item;
    }

    _refresh() {
        try {
            let proc = Gio.Subprocess.new(
                ['python3', this._scriptPath],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            );
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    let [, stdout] = p.communicate_utf8_finish(res);
                    if (stdout && stdout.trim()) {
                        this._stats = JSON.parse(stdout.trim());
                        this._updateDisplay();
                    }
                } catch (_e) {
                    this._label.set_text('◆ err');
                }
            });
        } catch (_e) {
            this._label.set_text('◆ err');
        }
    }

    _updateDisplay() {
        if (!this._stats) return;
        const s = this._stats;
        const f = s.fmt;
        const p = s.period;
        const w = s.weekly;

        this._label.set_text(s.panel_label);
        this._toggleItem.label.set_text(`⇄  Modo: ${s.label_mode === 'pct' ? 'porcentaje → raw' : 'raw → porcentaje'}`);

        // Period
        this._periodUsedItem.label.set_text(`  Usado:     ${f.period_used}  (${p.pct}%)`);
        this._periodRemainingItem.label.set_text(`  Restante:  ${f.period_remaining}`);
        this._periodBarItem.label.set_text(`  [${this._bar(p.pct, 20)}]`);
        if (p.eta_hours !== null)
            this._periodEtaItem.label.set_text(`  Se agota en: ~${p.eta_hours}h al ritmo actual`);
        else
            this._periodEtaItem.label.set_text(`  ETA: —`);

        // Weekly
        this._weekUsedItem.label.set_text(`  Usado:     ${f.weekly_used}  (${w.pct}%)`);
        this._weekRemainingItem.label.set_text(`  Restante:  ${f.weekly_remaining}`);
        this._weekBarItem.label.set_text(`  [${this._bar(w.pct, 20)}]`);
        const resetH = w.reset_in_hours;
        const resetStr = resetH > 48
            ? `${Math.round(resetH / 24)}d ${Math.round(resetH % 24)}h`
            : `${Math.round(resetH)}h`;
        this._weekResetItem.label.set_text(`  Reinicia en: ${resetStr}`);
        if (w.eta_hours !== null)
            this._weekEtaItem.label.set_text(`  Se agota en: ~${w.eta_hours}h al ritmo actual`);
        else
            this._weekEtaItem.label.set_text(`  ETA agotarse: —`);

        // Rate
        this._rateItem.label.set_text(`  Actual:     ${f.rate}/h  (ventana 6h)`);
        this._lastHourItem.label.set_text(`  Última hora: ${f.last_1h}  (${s.last_1h.messages} msgs)`);

        // History
        if (s.daily_history && s.daily_history.length > 0) {
            let hist = s.daily_history.slice(-4)
                .map(d => `${d.date.slice(5)}: ${this._fmt(d.tokens)}`)
                .join('   ');
            this._histItem.label.set_text(`  ${hist}`);
        } else {
            this._histItem.label.set_text('  (sin historial)');
        }

        this._updatedItem.label.set_text(`Actualizado: ${new Date().toLocaleTimeString()}`);
    }

    _toggleMode() {
        try {
            const file = Gio.File.new_for_path(CONFIG_PATH);
            let cfg = {};
            try {
                const [, contents] = file.load_contents(null);
                cfg = JSON.parse(new TextDecoder().decode(contents));
            } catch (_e) {}
            cfg.label_mode = (cfg.label_mode === 'pct') ? 'raw' : 'pct';
            file.replace_contents(
                new TextEncoder().encode(JSON.stringify(cfg, null, 2)),
                null, false, Gio.FileCreateFlags.NONE, null,
            );
        } catch (_e) {}
        this._refresh();
    }

    _bar(pct, width) {
        const filled = Math.round(Math.min(pct, 100) / 100 * width);
        return '█'.repeat(filled) + '░'.repeat(width - filled);
    }

    _fmt(n) {
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
        return String(Math.round(n));
    }

    destroy() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        super.destroy();
    }
});

export default class ClaudeUsageExtension extends Extension {
    enable() {
        this._indicator = new ClaudeIndicator(`${this.path}/claude_stats.py`);
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
