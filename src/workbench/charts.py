"""Responsive quantity charts with exact values and a shared scale per unit."""
from collections import OrderedDict
from html import escape

from src.workbench.explanations import finite, fmt


def quantity_chart_html(rows, *, recommended=True):
    groups = OrderedDict()
    for row in rows:
        value = row.get("建议数量")
        if finite(value):
            unit = str(row.get("单位") or "单位未标注")
            groups.setdefault(unit, []).append((str(row.get("决策项") or row.get("变量") or "决策项"), value))
    if not groups:
        return ""
    content = ['<section class="quantity-chart" aria-label="决策数量图"><div class="quantity-title">'
               + ("建议数量一览" if recommended else "返回数量一览（待复核）") + '</div>',
               '<p class="quantity-caption">横条表示数量，右侧为准确数值。同一单位使用同一刻度。</p>']
    palette = [("#4f5bdb", "#8e9af5"), ("#148b86", "#59c0b1"), ("#b77822", "#e2b560")]
    for unit, items in groups.items():
        low, high = min(0, *(v for _, v in items)), max(0, *(v for _, v in items))
        scale = max(abs(low),abs(high)) or 1
        span = (high/scale-low/scale) or 1
        zero = 100 * (-low/scale) / span
        content.append('<div class="quantity-group">')
        if len(groups)>1:
            content.append('<div class="quantity-unit">单位：'+escape(unit)+'</div>')
        for index,(label,value) in enumerate(items):
            start = 100 * (min(0,value)/scale-low/scale)/span
            width = 100 * (abs(value)/scale)/span
            color,end = palette[index%len(palette)]
            description = f"{label}：{fmt(value)} {unit}"
            content.append('<div class="quantity-row" role="img" aria-label="'+escape(description,quote=True)+'">'
                '<div class="quantity-row-heading"><span><i style="background:'+color+'"></i>'+escape(label)+'</span>'
                '<strong>'+escape(fmt(value))+' <small>'+escape(unit)+'</small></strong></div>'
                '<div class="quantity-track" aria-hidden="true"><div class="quantity-zero" style="left:'+f'{zero:.5f}'+'%"></div>'
                '<div class="quantity-fill" style="left:'+f'{start:.5f}'+'%;width:'+f'{width:.5f}'+'%;background:linear-gradient(90deg,'+color+','+end+')"></div></div></div>')
        content.append('<div class="quantity-axis" aria-hidden="true"><span>'+escape(fmt(low))+'</span><span>'
                       +escape(fmt(high))+' '+escape(unit)+'</span></div></div>')
    content.append('</section>')
    return ''.join(content)
