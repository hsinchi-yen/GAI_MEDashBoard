"""HTML components. Pure functions: data in, escaped HTML string out.

Keeping these free of Streamlit calls makes them cheap to test. Every piece of
data is escaped, because fetcher output (fund names, issuers) is external input.
Tone is always conveyed by icon + word as well as colour.
"""
from __future__ import annotations

from html import escape

from analytics.market_view import CONVICTION_LABELS, DIRECTION_LABELS, DISCLAIMER, STANCES
from macro_index import REGIME_GREEN_PCT, REGIME_RED_PCT, TOTAL_INDICATORS
from ui.theme import TONES

_SCALE = [("strong_bear", -2), ("bear", -1), ("neutral", 0), ("bull", 1), ("strong_bull", 2)]


def _tone_style(tone: str) -> str:
    return f"--tone:{TONES.get(tone, TONES['neutral'])['color']}"


def _join(*parts: str) -> str:
    """Concatenate without newlines: indented HTML would render as a code block."""
    return "".join(parts)


def chip(text: str, tone: str = "neutral") -> str:
    t = TONES.get(tone, TONES["neutral"])
    return (f'<span class="gm-chip" style="{_tone_style(tone)}">'
            f'<i aria-hidden="true">{t["icon"]}</i>{escape(text)}</span>')


def page_head(title: str, subtitle: str = "") -> str:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    return f'<div class="gm-pagehead"><h1>{escape(title)}</h1>{sub}</div>'


def section(title: str, subtitle: str = "") -> str:
    sub = f"<small>{escape(subtitle)}</small>" if subtitle else ""
    return f'<div class="gm-section">{escape(title)}{sub}</div>'


def _stance_scale(stance: dict) -> str:
    score = stance["score"]
    bars, labels = [], []
    for key, value in _SCALE:
        on = score == value
        bars.append(f'<span class="{"on" if on else ""}"></span>')
        word = STANCES[key]["label"]
        labels.append(f"<b>{word}</b>" if on else f"<span>{word}</span>")
    return _join('<div class="gm-scale" aria-hidden="true">', *bars, "</div>",
                 '<div class="gm-scale-labels">', *labels, "</div>")


def verdict_hero(view: dict) -> str:
    """The first thing an investor sees: stance, why, and how sure."""
    stance, gmi = view["stance"], view["gmi"]
    momentum = view["momentum_pp"]
    momentum_text = f"{momentum:+.1f} pp" if momentum is not None else "—"
    pending = ""
    if view["pending_regime"]:
        pending = ('<p class="gm-meaning">燈號訊號已變動，待下月確認後才切換。</p>')
    icon = TONES[stance["tone"]]["icon"]
    return _join(
        f'<section class="gm-hero" style="{_tone_style(stance["tone"])}" aria-label="總經多空判讀">',
        "<div>",
        f'<div class="gm-eyebrow">總經多空判讀 · 資料基準 {escape(str(view["as_of"]))}</div>',
        f'<div class="gm-stance"><span aria-hidden="true">{icon}</span> {escape(stance["label"])}</div>',
        f'<p class="gm-headline">{escape(view["headline"])}</p>',
        f'<p class="gm-meaning">{escape(stance["meaning"])}</p>',
        pending,
        _stance_scale(stance),
        "</div>",
        '<dl class="gm-kv">',
        f'<div><dt>景氣階段</dt><dd>{escape(view["phase_label"])}</dd></div>',
        f'<div><dt>擴散比例</dt><dd>{gmi["diffusion"]:.0f}%</dd></div>',
        f'<div><dt>3 個月動能</dt><dd>{escape(momentum_text)}</dd></div>',
        f'<div><dt>判讀方向</dt><dd>{escape(DIRECTION_LABELS[view["direction"]])}</dd></div>',
        f'<div><dt>有效指標</dt><dd>{gmi["valid_count"]}/{TOTAL_INDICATORS}</dd></div>',
        f'<div><dt>信心</dt><dd>{escape(CONVICTION_LABELS[view["conviction"]])}</dd></div>',
        "</dl></section>",
    )


def status_strip(view: dict, facts: list[tuple[str, str]]) -> str:
    """Slim header on detail pages: keeps the verdict in view everywhere."""
    stance, gmi = view["stance"], view["gmi"]
    cells = "".join(f"<span>{escape(k)} <b>{escape(v)}</b></span>" for k, v in facts)
    return _join(
        '<div class="gm-strip">',
        chip(stance["label"], stance["tone"]),
        f"<span>GMI <b>{gmi['score']}/{gmi['valid_count']}</b></span>",
        f"<span>擴散 <b>{gmi['diffusion']:.0f}%</b></span>",
        cells, "</div>",
    )


def pillar_cards(pillars: list[dict]) -> str:
    cards = []
    for p in pillars:
        if p["pct"] is None:
            body = '<div class="gm-big">—</div><div class="gm-sub">暫無資料</div>'
            bar = ""
        else:
            delta = "" if p["delta"] is None else f" · 3M {p['delta']:+.0f} pp"
            word = TONES[p["tone"]]["word"]
            body = (f'<div class="gm-big">{p["bull"]}/{p["valid"]}</div>'
                    f'<div class="gm-sub">{word} · 偏多比例 {p["pct"]:.0f}%{delta}</div>')
            bar = (f'<div class="gm-bar" role="img" aria-label="偏多比例 {p["pct"]:.0f}%">'
                   f'<i style="width:{p["pct"]:.0f}%"></i></div>')
        cards.append(_join(
            f'<div class="gm-card" style="{_tone_style(p["tone"])}">',
            f'<h4>{escape(p["name"])}</h4><p>{escape(p["desc"])}</p>',
            bar, body, "</div>"))
    return _join('<div class="gm-grid">', *cards, "</div>")


def signal_card(title: str, signals: list[dict], tone: str, empty: str) -> str:
    """Bull or bear case: which indicators, at what level, under which rule."""
    if signals:
        items = "".join(
            f"<li><b>{escape(s['name'])}</b> {escape(str(s['raw']))}"
            f"<small>{escape(s['rule'])}</small></li>"
            for s in signals)
        body = f"<ul>{items}</ul>"
    else:
        body = f"<p>{escape(empty)}</p>"
    icon = TONES[tone]["icon"]
    return _join(
        f'<div class="gm-card" style="{_tone_style(tone)}">',
        f'<h4><span style="color:var(--tone)" aria-hidden="true">{icon}</span> '
        f'{escape(title)}（{len(signals)}）</h4>',
        body, "</div>")


def changes_card(changes: list[dict]) -> str:
    if changes:
        items = []
        for c in changes:
            tone = "bullish" if c["to"] == "bull" else "bearish"
            word = "翻多" if c["to"] == "bull" else "翻空"
            items.append(f"<li>{chip(word, tone)} <b>{escape(c['name'])}</b> "
                         f"<small>{escape(str(c['raw']))}</small></li>")
        body = f"<ul>{''.join(items)}</ul>"
    else:
        body = "<p>過去 3 個月沒有指標改變方向，訊號穩定。</p>"
    return _join('<div class="gm-card"><h4>近 3 個月變化</h4>', body, "</div>")


def flip_meter(view: dict) -> str:
    """Where diffusion sits between the red and green zones, and the distance out."""
    gmi, flip = view["gmi"], view["flip"]
    value = max(0.0, min(100.0, gmi["diffusion"]))
    if flip["to_green"] is None:
        note = "暫無足夠指標計算距離。"
    elif flip["to_green"] == 0:
        note = f"已在擴張區；再 {flip['to_red']} 項轉空才會落入收縮區。"
    elif flip["to_red"] == 0:
        note = f"已在收縮區；再 {flip['to_green']} 項轉多才會進入擴張區。"
    else:
        note = f"再 {flip['to_green']} 項轉多進入擴張區；再 {flip['to_red']} 項轉空落入收縮區。"
    return _join(
        '<div class="gm-card"><h4>距離燈號翻轉</h4>',
        f'<div class="gm-meter" role="img" aria-label="擴散比例 {value:.0f}%">',
        f'<span class="z red" style="width:{REGIME_RED_PCT:.0f}%"></span>',
        f'<span class="z yel" style="width:{REGIME_GREEN_PCT - REGIME_RED_PCT:.0f}%"></span>',
        f'<span class="z grn" style="width:{100 - REGIME_GREEN_PCT:.0f}%"></span>',
        f'<span class="pin" style="left:{value:.1f}%"></span>',
        f'<span class="val" style="left:{value:.1f}%">{value:.0f}%</span>',
        f'<span class="tick" style="left:{REGIME_RED_PCT:.0f}%">{REGIME_RED_PCT:.0f}%</span>',
        f'<span class="tick" style="left:{REGIME_GREEN_PCT:.0f}%">{REGIME_GREEN_PCT:.0f}%</span>',
        f"</div><p>{escape(note)}</p></div>")


def playbook_card(playbook: dict) -> str:
    items = "".join(f"<li>{escape(a)}</li>" for a in playbook["actions"])
    return _join('<div class="gm-card"><h4>操作框架</h4>',
                 f'<p><b style="color:var(--ink)">{escape(playbook["posture"])}</b></p>',
                 f"<ul>{items}</ul></div>")


def clock_card(clock: dict | None) -> str:
    if not clock:
        return ('<div class="gm-card"><h4>成長／通膨時鐘</h4>'
                "<p>成長或通膨序列的歷史不足 36 個月，暫無法定位。</p></div>")
    return _join(
        '<div class="gm-card"><h4>成長／通膨時鐘</h4>',
        f'<div class="gm-big">{escape(clock["label"])}</div>',
        f'<div class="gm-sub">{escape(clock["desc"])}</div>',
        f'<ul><li><b>相對有利</b> {escape(clock["favoured"])}</li>',
        f'<li><b>相對不利</b> {escape(clock["avoid"])}</li></ul></div>')


def alerts_card(alerts: list[dict], stale_count: int = 0) -> str:
    items = []
    for a in alerts:
        tone = "bearish" if a["level"] == "alert" else "neutral"
        word = "警戒" if a["level"] == "alert" else "留意"
        items.append(f"<li>{chip(word, tone)} <b>{escape(a['title'])}</b>"
                     f"<small>{escape(a['message'])}</small></li>")
    if stale_count:
        items.append(f"<li>{chip('資料', 'neutral')} <b>{stale_count} 項指標過期</b>"
                     "<small>可到趨勢雷達篩選「資料過期」查看</small></li>")
    body = f"<ul>{''.join(items)}</ul>" if items else "<p>目前沒有觸發中的風險警示。</p>"
    return _join('<div class="gm-card"><h4>風險警示</h4>', body, "</div>")


def theme_brief_bar(brief: dict) -> str:
    return _join(f'<div class="gm-brief" style="{_tone_style(brief["tone"])}">',
                 chip(TONES[brief["tone"]]["word"], brief["tone"]),
                 f"<span>{escape(brief['summary'])}</span></div>")


def breadth_cards(rows: list[dict]) -> str:
    cards = []
    for r in rows:
        total = r["total"]
        pct = r["bull"] / total * 100 if total else 0
        cards.append(_join(
            f'<div class="gm-card" style="{_tone_style(r["tone"])}">',
            f'<h4>{escape(r["label"])}</h4>',
            f'<div class="gm-bar" role="img" aria-label="趨勢向好 {pct:.0f}%">'
            f'<i style="width:{pct:.0f}%"></i></div>',
            f'<div class="gm-sub">▲ {r["bull"]} · ▼ {r["bear"]} · ● {r["neutral"]}</div>',
            "</div>"))
    return _join('<div class="gm-grid">', *cards, "</div>")


def evidence_table(rows: list[dict], label: str) -> str:
    """Forward returns after the current regime vs the all-period baseline."""
    if not rows:
        return ""
    head = "<tr><th>持有期</th><th>中位報酬</th><th>相對全期</th><th>勝率</th><th>P10</th><th>獨立樣本</th></tr>"
    body = []
    for r in rows:
        flag = " ⚠" if r["thin"] else ""
        body.append(
            f"<tr><td>{r['horizon']} 個月</td><td>{r['median']:+.1f}%</td><td>{r['edge']:+.1f} pp</td>"
            f"<td>{r['win_rate']:.0f}%</td><td>{r['p10']:+.1f}%</td><td>≈{r['n_eff']}{flag}</td></tr>")
    return _join('<div class="gm-card">',
                 f"<h4>{escape(label)}</h4>",
                 f'<table class="gm-table">{head}{"".join(body)}</table>', "</div>")


def disclaimer() -> str:
    return f'<p class="gm-sub" style="margin-top:20px">{escape(DISCLAIMER)}</p>'


def indicator_tile(signal: dict, tone: str) -> str:
    """One GMI indicator: direction, name, reading, and the rule behind it."""
    t = TONES.get(tone, TONES["neutral"])
    word = "無資料" if not signal["has_data"] else t["word"]
    return _join(
        f'<div class="gm-card" style="{_tone_style(tone)}">',
        f'<div class="gm-sub"><span style="color:var(--tone)" aria-hidden="true">{t["icon"]}</span> {word}</div>',
        f'<h4>{escape(signal["name"])}</h4>',
        f'<p>{escape(str(signal["raw"]))}</p>',
        f'<div class="gm-sub">{escape(signal["rule"])}</div></div>')


_ROTATION_GROUPS = (
    ("hot", "強勢類股", "bullish", "資金持續流入"),
    ("warming", "升溫中", "neutral", "跌勢收斂，留意布局"),
    ("cooling", "退潮中", "neutral", "漲勢收斂，留意調節"),
    ("cold", "弱勢類股", "bearish", "資金持續流出"),
)


def rotation_cards(signals: dict) -> str:
    cards = []
    for key, title, tone, hint in _ROTATION_GROUPS:
        names = signals.get(key) or ["—"]
        items = "".join(f"<li>{escape(str(n))}</li>" for n in names)
        cards.append(_join(
            f'<div class="gm-card" style="{_tone_style(tone)}">',
            f'<h4><span style="color:var(--tone)" aria-hidden="true">{TONES[tone]["icon"]}</span> '
            f'{title}</h4><div class="gm-sub">{hint}</div><ul>{items}</ul></div>'))
    return _join('<div class="gm-grid">', *cards, "</div>")
