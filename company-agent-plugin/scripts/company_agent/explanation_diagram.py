"""Bounded, offline explanation diagrams made only from validated data.

The SVG is complete without JavaScript. Optional playback changes emphasis only;
it never runs an operation, hides a node, fetches a resource, or infers progress.
"""
from __future__ import annotations

import heapq
import html
import math
import re
import textwrap
from typing import Any


TYPES = ("flow", "structure", "swimlane", "state")
STATUSES = {"planned": "계획", "completed": "완료", "failed": "실패",
            "waiting": "대기", "unknown": "미확인"}
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")
_NOTICE = "설명용 재생 — 실제 작업을 다시 실행하지 않습니다"


def _fail(message: str) -> None:
    # business_artifacts imports this module when normalizing optional diagrams.
    from .business_artifacts import ArtifactError
    raise ArtifactError("invalid_diagram", message)


def _object(value: Any, keys: set[str], name: str) -> dict:
    if not isinstance(value, dict) or any(key not in keys for key in value):
        _fail(f"{name}에는 지원하는 설명 항목만 지정해 주세요. 코드, SVG, 실행 옵션은 받지 않습니다.")
    return value


def _text(value: Any, limit: int, name: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        _fail(f"{name}은 {limit}자 이하의 글자로 지정해 주세요.")
    if any((ord(char) < 32 and char not in "\n\r\t") or 0x7f <= ord(char) <= 0x9f
           or 0xd800 <= ord(char) <= 0xdfff for char in value):
        _fail(f"{name}에 지원하지 않는 제어 문자가 있습니다.")
    result = value.strip()
    if required and not result:
        _fail(f"{name}을 입력해 주세요.")
    return result


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(f"{name}은 영문자로 시작하는 영문·숫자·밑줄·붙임표 1~32자로 지정해 주세요.")
    return value


def normalize(raw: Any) -> dict[str, Any]:
    """Validate the public data contract; do not mutate or silently trim input."""
    raw = _object(raw, {"type", "title", "summary", "nodes", "edges", "lanes", "motion", "steps"}, "다이어그램")
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in TYPES:
        _fail("다이어그램 유형은 flow, structure, swimlane, state 중에서 선택해 주세요.")
    title = _text(raw.get("title"), 120, "그림 제목", required=True)
    summary = _text(raw.get("summary", ""), 600, "그림 설명")
    nodes, edges, lanes = raw.get("nodes"), raw.get("edges", []), raw.get("lanes", [])
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 9:
        _fail("한 그림에는 1~9개 항목을 지정해 주세요.")
    if not isinstance(edges, list) or len(edges) > 12:
        _fail("한 그림의 연결은 12개 이하로 지정해 주세요.")
    if not isinstance(lanes, list) or len(lanes) > 4:
        _fail("역할 구역은 4개 이하로 지정해 주세요.")
    if (kind == "swimlane" and not lanes) or (kind != "swimlane" and lanes):
        _fail("역할 구역은 swimlane 유형에만 필요하며 1~4개를 지정해 주세요.")
    normalized_lanes, lane_ids = [], set()
    for lane in lanes:
        lane = _object(lane, {"id", "label"}, "역할 구역")
        lane_id = _identifier(lane.get("id"), "구역 ID")
        if lane_id in lane_ids:
            _fail("역할 구역 ID는 서로 달라야 합니다.")
        lane_ids.add(lane_id)
        normalized_lanes.append({"id": lane_id, "label": _text(lane.get("label"), 80, "구역 이름", required=True)})
    normalized_nodes, node_ids = [], set()
    for node in nodes:
        node = _object(node, {"id", "label", "detail", "status", "evidence", "lane"}, "그림 항목")
        node_id = _identifier(node.get("id"), "항목 ID")
        if node_id in node_ids:
            _fail("항목 ID는 서로 달라야 합니다.")
        node_ids.add(node_id)
        status = node.get("status", "unknown")
        if not isinstance(status, str) or status not in STATUSES:
            _fail("상태는 planned, completed, failed, waiting, unknown 중에서 선택해 주세요.")
        checked = {"id": node_id, "label": _text(node.get("label"), 80, "항목 이름", required=True),
                   "detail": _text(node.get("detail", ""), 300, "항목 설명"), "status": status,
                   "evidence": _text(node.get("evidence", ""), 300, "근거")}
        if kind == "swimlane":
            lane_id = _identifier(node.get("lane"), "항목의 구역 ID")
            if lane_id not in lane_ids:
                _fail("모든 항목은 지정한 역할 구역에 속해야 합니다.")
            checked["lane"] = lane_id
        elif "lane" in node:
            _fail("항목의 역할 구역은 swimlane 유형에서만 지정해 주세요.")
        normalized_nodes.append(checked)
    normalized_edges, edge_pairs = [], set()
    for edge in edges:
        edge = _object(edge, {"from", "to", "label"}, "연결")
        source, target = _identifier(edge.get("from"), "출발 ID"), _identifier(edge.get("to"), "도착 ID")
        if source not in node_ids or target not in node_ids:
            _fail("연결의 출발과 도착 ID는 그림에 있는 항목이어야 합니다.")
        if (source, target) in edge_pairs:
            _fail("같은 방향의 연결은 한 번만 지정해 주세요. 설명을 하나로 합칠 수 있습니다.")
        edge_pairs.add((source, target))
        normalized_edges.append({"from": source, "to": target, "label": _text(edge.get("label", ""), 80, "연결 설명")})
    motion = raw.get("motion", "none")
    if not isinstance(motion, str) or motion not in ("none", "steps"):
        _fail("재생 방식은 none 또는 steps로 지정해 주세요.")
    steps = raw.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 9:
        _fail("설명 순서는 9개 이하의 항목 ID 목록이어야 합니다.")
    for step in steps:
        _identifier(step, "설명 순서 ID")
        if step not in node_ids:
            _fail("설명 순서는 그림에 있는 항목 ID만 사용할 수 있습니다.")
    if len(set(steps)) != len(steps):
        _fail("설명 순서에 같은 항목을 반복하지 마세요.")
    if (motion == "steps" and not steps) or (motion == "none" and steps):
        _fail("steps 재생에는 명시적인 설명 순서가 필요합니다. none에서는 설명 순서를 비워 주세요.")
    return {"type": kind, "title": title, "summary": summary, "nodes": normalized_nodes,
            "edges": normalized_edges, "lanes": normalized_lanes, "motion": motion, "steps": list(steps)}


def _wrap(value: str, width: int = 12) -> list[str]:
    # Conservative per-character width also fits Korean and wide Latin glyphs.
    return textwrap.wrap(" ".join(value.split()), width=width, break_long_words=True,
                         break_on_hyphens=False) or [""]


def _layers(diagram: dict) -> list[list[dict]]:
    """Shortest root-distance tiers, including deterministic roots for cycles."""
    nodes = diagram["nodes"]
    incoming = {node["id"]: 0 for node in nodes}
    children = {node["id"]: [] for node in nodes}
    for edge in diagram["edges"]:
        if edge["from"] != edge["to"]:
            incoming[edge["to"]] += 1
            children[edge["from"]].append(edge["to"])
    depths = {}
    roots = [node["id"] for node in nodes if not incoming[node["id"]]]
    queue = [(root, 0) for root in roots]
    while len(depths) < len(nodes):
        if not queue:
            queue = [(next(node["id"] for node in nodes if node["id"] not in depths), 0)]
        node_id, depth = queue.pop(0)
        if node_id in depths:
            continue
        depths[node_id] = depth
        queue.extend((child, depth + 1) for child in children[node_id] if child not in depths)
    return [[node for node in nodes if depths[node["id"]] == depth] for depth in range(max(depths.values()) + 1)]


def _layout(diagram: dict) -> dict:
    """Return inspectable, bounded geometry independent of browser measurements."""
    nodes, kind = diagram["nodes"], diagram["type"]
    width = 264
    height = max(136, max(len(_wrap(node["label"])) for node in nodes) * 24 + 72)
    margin, gap = 76, 104
    boxes, lane_boxes = {}, []
    if kind == "structure":
        tiers = _layers(diagram)
        columns = max(len(tier) for tier in tiers)
        total_width = 2 * margin + columns * width + (columns - 1) * gap
        for row, tier in enumerate(tiers):
            left = (total_width - len(tier) * width - (len(tier) - 1) * gap) / 2
            for col, node in enumerate(tier):
                boxes[node["id"]] = (left + col * (width + gap), margin + row * (height + gap), width, height)
        total_height = 2 * margin + len(tiers) * height + (len(tiers) - 1) * gap
    elif kind == "swimlane":
        # Input order is an explicit sequence of columns across role rows.
        lane_header = 202
        total_width = 2 * margin + lane_header + len(nodes) * (width + gap) - gap
        total_height = 2 * margin + len(diagram["lanes"]) * (height + gap) - gap
        for row, lane in enumerate(diagram["lanes"]):
            y = margin + row * (height + gap)
            lane_boxes.append((lane, 20, y - 32, total_width - 40, height + 64))
            for col, node in enumerate(nodes):
                if node["lane"] == lane["id"]:
                    boxes[node["id"]] = (margin + lane_header + col * (width + gap), y, width, height)
    elif kind == "state":
        radius = 0 if len(nodes) == 1 else max(290, (math.hypot(width, height) + gap) / (2 * math.sin(math.pi / len(nodes))))
        total_width, total_height = 2 * (margin + radius) + width, 2 * (margin + radius) + height
        for index, node in enumerate(nodes):
            angle = -math.pi / 2 + 2 * math.pi * index / len(nodes)
            boxes[node["id"]] = (round(margin + radius + radius * math.cos(angle), 2),
                                  round(margin + radius + radius * math.sin(angle), 2), width, height)
    else:
        columns = min(3, len(nodes))
        rows = math.ceil(len(nodes) / columns)
        total_width, total_height = 2 * margin + columns * width + (columns - 1) * gap, 2 * margin + rows * height + (rows - 1) * gap
        for index, node in enumerate(nodes):
            row, col = divmod(index, columns)
            if row % 2:
                col = columns - 1 - col
            boxes[node["id"]] = (margin + col * (width + gap), margin + row * (height + gap), width, height)
    return {"width": math.ceil(total_width), "height": math.ceil(total_height), "boxes": boxes, "lanes": lane_boxes}


def _intersects(a: tuple, b: tuple, box: tuple) -> bool:
    """Whether a horizontal/vertical segment crosses a box's open interior."""
    x, y, width, height = box
    if a[0] == b[0]:
        return x < a[0] < x + width and max(min(a[1], b[1]), y) < min(max(a[1], b[1]), y + height)
    return y < a[1] < y + height and max(min(a[0], b[0]), x) < min(max(a[0], b[0]), x + width)


def _port(box: tuple, side: str, offset: float = 0) -> tuple[tuple, tuple]:
    x, y, width, height = box
    if side == "left":
        return (x, y + height / 2 + offset), (x - 22, y + height / 2 + offset)
    if side == "right":
        return (x + width, y + height / 2 + offset), (x + width + 22, y + height / 2 + offset)
    if side == "top":
        return (x + width / 2 + offset, y), (x + width / 2 + offset, y - 22)
    return (x + width / 2 + offset, y + height), (x + width / 2 + offset, y + height + 22)


def _route(layout: dict, edge: dict, index: int) -> list[tuple]:
    """Route on a rectilinear visibility grid; boxes are hard obstacles."""
    source, target = layout["boxes"][edge["from"]], layout["boxes"][edge["to"]]
    dx, dy = target[0] - source[0], target[1] - source[1]
    if source == target:
        side_a, side_b = "right", "top"
    elif abs(dx) >= abs(dy):
        side_a, side_b = ("right", "left") if dx > 0 else ("left", "right")
    else:
        side_a, side_b = ("bottom", "top") if dy > 0 else ("top", "bottom")
    offset = (index - 5.5) * 5
    port_a, start = _port(source, side_a, offset)
    port_b, finish = _port(target, side_b, -offset)
    obstacles = [(x - 12, y - 12, w + 24, h + 24) for x, y, w, h in layout["boxes"].values()]
    obstacles.extend((x + 8, y + 8, 192, h - 16) for _, x, y, _, h in layout["lanes"])
    xs, ys = {24.0, float(layout["width"] - 24), start[0], finish[0]}, {24.0, float(layout["height"] - 24), start[1], finish[1]}
    for x, y, w, h in obstacles:
        xs.update((x - 10, x + w + 10))
        ys.update((y - 10, y + h + 10))
    xs, ys = sorted(xs), sorted(ys)
    first, last = (xs.index(start[0]), ys.index(start[1])), (xs.index(finish[0]), ys.index(finish[1]))
    def heuristic(position):
        return abs(xs[position[0]] - finish[0]) + abs(ys[position[1]] - finish[1])
    queue = [(heuristic(first), 0.0, first)]
    distances, previous = {first: 0.0}, {}
    while queue:
        _, distance, current = heapq.heappop(queue)
        if distance != distances[current]:
            continue
        if current == last:
            break
        x_idx, y_idx = current
        a = (xs[x_idx], ys[y_idx])
        for neighbor in ((x_idx - 1, y_idx), (x_idx + 1, y_idx), (x_idx, y_idx - 1), (x_idx, y_idx + 1)):
            if not 0 <= neighbor[0] < len(xs) or not 0 <= neighbor[1] < len(ys):
                continue
            b = (xs[neighbor[0]], ys[neighbor[1]])
            if any(_intersects(a, b, box) for box in obstacles):
                continue
            candidate = distance + abs(a[0] - b[0]) + abs(a[1] - b[1])
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor], previous[neighbor] = candidate, current
                heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))
    if last not in distances:
        _fail("연결이 너무 밀집되어 그림을 배치하지 못했습니다. 그림을 나누어 주세요.")
    route, current = [], last
    while current != first:
        route.append((xs[current[0]], ys[current[1]]))
        current = previous[current]
    route.append(start)
    route = [port_a, *reversed(route), port_b]
    simplified = []
    for point in route:
        if simplified and point == simplified[-1]:
            continue
        while len(simplified) > 1 and ((simplified[-2][0] == simplified[-1][0] == point[0]) or
                                       (simplified[-2][1] == simplified[-1][1] == point[1])):
            simplified.pop()
        simplified.append(point)
    return simplified


def _badge_position(points: list[tuple], occupied: list[tuple], layout: dict) -> tuple:
    """Place a relation number on its path, clear of cards and other numbers."""
    boxes = list(layout["boxes"].values())
    boxes += [(x + 8, y + 8, 192, h - 16) for _, x, y, _, h in layout["lanes"]]
    segments = sorted(zip(points, points[1:]), key=lambda pair: -math.dist(*pair))
    for a, b in segments:
        length = math.dist(a, b)
        for offset in [0, *[sign * distance for distance in range(26, math.ceil(length / 2), 26) for sign in (1, -1)]]:
            fraction = .5 + offset / length
            if not 0 < fraction < 1:
                continue
            x, y = a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction
            if not 14 <= x <= layout["width"] - 14 or not 14 <= y <= layout["height"] - 14:
                continue
            if any(bx - 15 < x < bx + bw + 15 and by - 15 < y < by + bh + 15 for bx, by, bw, bh in boxes):
                continue
            if any(math.hypot(x - px, y - py) < 26 for px, py in occupied):
                continue
            return (x, y)
    _fail("연결 번호를 겹치지 않게 배치하지 못했습니다. 그림을 나누어 주세요.")


def _number(number: float) -> str:
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _arrow(points: list[tuple]) -> str:
    x, y = points[-1]
    a, b = points[-2]
    length = math.hypot(x - a, y - b)
    dx, dy = (x - a) / length, (y - b) / length
    return " ".join(f"{_number(px)},{_number(py)}" for px, py in
                    ((x, y), (x - 11 * dx + 5 * dy, y - 11 * dy - 5 * dx), (x - 11 * dx - 5 * dy, y - 11 * dy + 5 * dx)))


def _svg_text(lines: list[str], x: float, y: float, class_name: str, line_height: int = 24) -> str:
    return f'<text class="{class_name}" x="{_number(x)}" y="{_number(y)}">' + "".join(
        f'<tspan x="{_number(x)}" dy="{0 if index == 0 else line_height}">{html.escape(line)}</tspan>'
        for index, line in enumerate(lines)) + '</text>'


def render(diagram: dict, index: int) -> str:
    """Render a safe HTML figure. CSS/JS must each be included only once by host."""
    diagram = normalize(diagram)
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 9999:
        _fail("그림 번호는 0~9999 사이의 정수여야 합니다.")
    esc, layout, figure_id = html.escape, _layout(diagram), f"explanation-{index}"
    labels = {node["id"]: node["label"] for node in diagram["nodes"]}
    result = [f'<figure class="explanation-diagram" id="{figure_id}" data-diagram-type="{diagram["type"]}" data-motion="{diagram["motion"]}" data-steps="{",".join(diagram["steps"])}">',
              f'<figcaption><strong>{esc(diagram["title"])}</strong></figcaption>']
    if diagram["summary"]:
        result.append(f'<p class="diagram-summary">{esc(diagram["summary"])}</p>')
    result += [f'<p class="diagram-notice">{_NOTICE}. 상태와 근거는 제공된 기록을 설명합니다.</p>',
               '<div class="diagram-scroll" tabindex="0" role="region" aria-label="설명 그림: 필요하면 가로로 스크롤하세요">',
               f'<svg class="explanation-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {layout["width"]} {layout["height"]}" width="{layout["width"]}" height="{layout["height"]}" role="img" aria-labelledby="{figure_id}-title {figure_id}-desc">',
               f'<title id="{figure_id}-title">{esc(diagram["title"])}</title>',
               f'<desc id="{figure_id}-desc">{esc(diagram["summary"])} 전체 {len(diagram["nodes"])}개 항목과 {len(diagram["edges"])}개 연결. 항목의 상세 설명·근거와 번호별 연결 설명은 그림 아래에 있습니다.</desc>']
    for lane, x, y, width, height in layout["lanes"]:
        result.append(f'<rect class="diagram-lane" x="{x}" y="{y}" width="{width}" height="{height}" rx="16"/>')
        result.append(_svg_text(_wrap(lane["label"], 9), x + 20, y + 36, "diagram-lane-label", 20))
    badges, badge_markup = [], []
    for number, edge in enumerate(diagram["edges"], 1):
        points = _route(layout, edge, number - 1)
        path = "M " + " L ".join(f"{_number(x)} {_number(y)}" for x, y in points)
        result.append(f'<g class="diagram-edge"><title>연결 {number}: {esc(labels[edge["from"]])} → {esc(labels[edge["to"]])}{": " + esc(edge["label"]) if edge["label"] else ""}</title><path d="{path}"/><polygon points="{_arrow(points)}"/></g>')
        bx, by = _badge_position(points, badges, layout)
        badges.append((bx, by))
        badge_markup.append(f'<g class="diagram-edge-number"><circle cx="{_number(bx)}" cy="{_number(by)}" r="11"/><text x="{_number(bx)}" y="{_number(by + 4)}">{number}</text></g>')
    # Draw every number after every path so later paths cannot strike its text.
    result.extend(badge_markup)
    for number, node in enumerate(diagram["nodes"], 1):
        x, y, width, height = layout["boxes"][node["id"]]
        radius = 28 if diagram["type"] == "state" else 12
        result.append(f'<g class="diagram-node" data-node-id="{node["id"]}" data-label="{esc(node["label"], quote=True)}"><rect x="{_number(x)}" y="{_number(y)}" width="{width}" height="{height}" rx="{radius}"/>')
        result.append(_svg_text([f"{number:02d}"], x + 18, y + 25, "diagram-node-index"))
        result.append(_svg_text(_wrap(node["label"]), x + 18, y + 53, "diagram-node-label"))
        result.append(_svg_text([f"상태: {STATUSES[node['status']]}"] , x + 18, y + height - 18, "diagram-node-status"))
        result.append('</g>')
    result += ['</svg></div>', '<ol class="diagram-details" aria-label="항목별 설명과 근거">']
    for node in diagram["nodes"]:
        result.append(f'<li><strong>{esc(node["label"])}</strong><span class="diagram-record-status">상태: {STATUSES[node["status"]]}</span>')
        if node["detail"]:
            result.append(f'<p>{esc(node["detail"])}</p>')
        result.append(f'<p class="diagram-evidence">근거: {esc(node["evidence"]) if node["evidence"] else "제공된 근거 없음"}</p></li>')
    result.append('</ol>')
    if diagram["edges"]:
        result.append('<ol class="diagram-relations" aria-label="번호별 연결 설명">')
        for edge in diagram["edges"]:
            result.append(f'<li><span>{esc(labels[edge["from"]])} → {esc(labels[edge["to"]])}</span>{": " + esc(edge["label"]) if edge["label"] else ""}</li>')
        result.append('</ol>')
    if diagram["motion"] == "steps":
        result += ['<div class="diagram-motion" hidden>',
                   '<button type="button" data-diagram-action="play">설명 재생</button>',
                   '<button type="button" data-diagram-action="step">한 단계씩 보기</button>',
                   '<button type="button" data-diagram-action="pause" disabled>일시정지</button>',
                   '<button type="button" data-diagram-action="reset">처음 상태로</button></div>',
                   f'<p class="diagram-playback-status" aria-live="polite" aria-atomic="true">{_NOTICE}. 전체 그림을 표시하고 있습니다.</p>']
    result.append('</figure>')
    return "".join(result)


CSS = """
.explanation-diagram{margin:28px 0;padding:22px;border:1px solid #cdd6e3;border-radius:16px;background:#fff;color:#172132;font-family:'Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo','Segoe UI',sans-serif}
.explanation-diagram figcaption{font-size:22px;color:#172132;line-height:1.5;overflow-wrap:anywhere}.diagram-summary,.diagram-notice,.diagram-playback-status{white-space:pre-line;overflow-wrap:anywhere}.diagram-notice,.diagram-playback-status{font-size:14px;color:#475569}
.diagram-scroll{overflow:auto;max-width:100%;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc}.diagram-scroll:focus-visible{outline:3px solid #2563eb}.explanation-svg{display:block;max-width:none;height:auto;font-family:inherit}
.diagram-node rect{fill:#fff;stroke:#64748b;stroke-width:2}.diagram-node.is-highlighted rect{fill:#e0edff;stroke:#1d4ed8;stroke-width:5}.diagram-node-index{fill:#64748b;font-size:13px;font-weight:700}.diagram-node-label{fill:#172132;font-size:18px;font-weight:600}.diagram-node-status{fill:#475569;font-size:14px}.diagram-edge path{fill:none;stroke:#526781;stroke-width:2}.diagram-edge polygon{fill:#526781}.diagram-edge-number circle{fill:#fff;stroke:#8ba0b8;stroke-width:1}.diagram-edge-number text{text-anchor:middle;fill:#334155;font-size:12px;font-weight:700}.diagram-lane{fill:#edf2f8;stroke:#c6d2e2;stroke-width:1}.diagram-lane-label{font-size:16px;font-weight:600;fill:#334155}
.diagram-details{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:14px 30px;margin:20px 0;padding-left:26px}.diagram-details li,.diagram-relations li{overflow-wrap:anywhere;white-space:pre-line}.diagram-details p{margin:5px 0;font-size:14px}.diagram-record-status{display:block;font-size:14px;color:#475569}.diagram-evidence{color:#475569}.diagram-relations{padding-left:28px;font-size:14px}.diagram-relations li{padding:5px 0}.diagram-motion{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.diagram-motion[hidden]{display:none!important}.diagram-motion button{font-size:14px}.diagram-playback-status{min-height:2em}
@media(prefers-reduced-motion:reduce){.explanation-diagram .diagram-motion{display:none!important}.diagram-node.is-highlighted rect{fill:#fff;stroke:#64748b;stroke-width:2}}
@media print{.section.has-diagram{break-inside:auto}.explanation-diagram{padding:12px;break-inside:auto}.diagram-scroll{overflow:visible;border:0}.explanation-diagram .explanation-svg{width:100%!important;min-width:0!important;max-width:100%!important;height:auto;max-height:230mm}.diagram-motion,.diagram-playback-status{display:none!important}.diagram-node.is-highlighted rect{fill:#fff;stroke:#64748b;stroke-width:2}.diagram-details{display:block}.diagram-details li{break-inside:avoid}.diagram-relations{break-inside:avoid}}
"""

JS = """'use strict';(()=>{
const notice='설명용 재생 — 실제 작업을 다시 실행하지 않습니다';
const media=window.matchMedia?window.matchMedia('(prefers-reduced-motion: reduce)'):null;
const controllers=[];let active=null;
document.querySelectorAll('.explanation-diagram[data-motion="steps"]').forEach(figure=>{
 const controls=figure.querySelector('.diagram-motion');const status=figure.querySelector('.diagram-playback-status');
 const nodes=[...figure.querySelectorAll('.diagram-node')];const steps=figure.dataset.steps.split(',').map(id=>nodes.find(node=>node.dataset.nodeId===id));
 if(!controls||!status||!steps.length||steps.some(node=>!node))return;
 const buttons={};controls.querySelectorAll('button[data-diagram-action]').forEach(button=>{buttons[button.dataset.diagramAction]=button});
 let position=-1,timer=null,running=false;
 function clear(){if(timer!==null){window.clearTimeout(timer);timer=null}running=false;if(active===controller)active=null}
 function display(label){nodes.forEach(node=>node.classList.toggle('is-highlighted',node===steps[position]));status.textContent=notice+'. '+(position<0?'전체 그림을 표시하고 있습니다.':(position+1)+' / '+steps.length+': '+steps[position].dataset.label+' — '+label);buttons.pause.disabled=!running;buttons.step.disabled=position===steps.length-1;buttons.play.disabled=running}
 function pause(){clear();display(position===steps.length-1?'설명 완료':'일시정지')}
 function claim(){if(active&&active!==controller)active.pause();clear();active=controller}
 function advance(){if(position<steps.length-1)position++;if(position===steps.length-1){clear();display('설명 완료');return}display(running?'설명 재생 중':'단계 확인');if(running)timer=window.setTimeout(advance,1600)}
 function reset(){clear();position=-1;display('전체 그림')}
 const controller={pause,reset};controllers.push(controller);
 buttons.play.addEventListener('click',()=>{if(media&&media.matches)return;claim();if(position===steps.length-1)position=-1;running=true;advance()});
 buttons.step.addEventListener('click',()=>{if(media&&media.matches)return;claim();advance()});
 buttons.pause.addEventListener('click',pause);buttons.reset.addEventListener('click',reset);
 controls.hidden=!!(media&&media.matches);display('전체 그림');
 controller.reduced=()=>{reset();controls.hidden=!!(media&&media.matches)};
});
if(media){const changed=()=>controllers.forEach(controller=>controller.reduced());if(media.addEventListener)media.addEventListener('change',changed);else if(media.addListener)media.addListener(changed)}
window.addEventListener('beforeprint',()=>controllers.forEach(controller=>controller.reset()));
window.addEventListener('pagehide',()=>controllers.forEach(controller=>controller.pause()));
document.addEventListener('visibilitychange',()=>{if(document.hidden)controllers.forEach(controller=>controller.pause())});
})();"""
