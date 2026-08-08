#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


# (removed Colab magic: reportlab is a declared dependency)


import csv
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth


# -----------------------------
# Helpers: choose best fields
# -----------------------------
def _first_nonempty(row: dict, keys: List[str]) -> str:
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def _safe_person_name(name: str) -> str:
    return (name or "").replace("/", "").strip()


@dataclass
class VisualPerson:
    id: str
    name: str
    birt_place: str
    deat_place: str
    birt_date: str
    deat_date: str
    marr_date: str
    father_id: str
    mother_id: str

    @classmethod
    def from_row(cls, row: dict) -> "VisualPerson":
        pid = (row.get("ID") or row.get("Id") or "").strip()
        name = _safe_person_name(row.get("Name") or "")

        birt_place = _first_nonempty(
            row,
            ["birthplace_clean", "BirthPlace_Clean", "BirtPlace_Clean", "BirtPlace", "BirthPlace"],
        )
        deat_place = _first_nonempty(
            row,
            ["deathplace_clean", "DeathPlace_Clean", "DeatPlace_Clean", "DeatPlace", "DeathPlace"],
        )

        birt_date = _first_nonempty(
            row,
            ["birthdate_clean", "BirthDate_Clean", "BirtDate_Clean", "BirtDate_Orig", "BirthDate", "BirtDate"],
        )
        deat_date = _first_nonempty(
            row,
            ["deathdate_clean", "DeathDate_Clean", "DeatDate_Clean", "DeatDate_Orig", "DeathDate", "DeatDate"],
        )

        marr_date = _first_nonempty(
            row,
            ["marrdate_clean", "MarrDate_Clean", "MarrDate", "MarrDate_Orig", "MarrDate_Original"],
        )

        return cls(
            id=pid,
            name=name,
            birt_place=birt_place,
            deat_place=deat_place,
            birt_date=birt_date,
            deat_date=deat_date,
            marr_date=marr_date,
            father_id=(row.get("FatherID") or "").strip(),
            mother_id=(row.get("MotherID") or "").strip(),
        )


def _has_parents(person: Optional[VisualPerson]) -> bool:
    return bool(person and (person.father_id or person.mother_id))


def load_person_map(csv_path: str) -> Dict[str, VisualPerson]:
    person_map: Dict[str, VisualPerson] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vp = VisualPerson.from_row(row)
            if vp.id:
                person_map[vp.id] = vp
    return person_map


def build_page_plan(
    person_map: Dict[str, VisualPerson],
    root_id: str,
    max_gens: int,
) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    if root_id not in person_map:
        raise ValueError(f"Root ID not found in CSV: {root_id}")

    page_map: Dict[str, int] = {}
    breadcrumb_map: Dict[str, List[str]] = {}

    queue: List[Tuple[str, List[str], int]] = [(root_id, [], 0)]
    processed = set()
    next_page_num = 1

    while queue:
        page_root_id, crumb_path, page_root_abs_gen = queue.pop(0)

        if not page_root_id:
            continue
        if page_root_abs_gen > max_gens:
            continue
        if page_root_id in processed:
            continue

        person = person_map.get(page_root_id)
        if not person:
            continue

        processed.add(page_root_id)
        page_map[page_root_id] = next_page_num

        short_name = (person.name.split("  ")[0].strip() if person.name else page_root_id)
        new_entry = f"{short_name} (P.{next_page_num})"
        full_trace = crumb_path + [new_entry]
        breadcrumb_map[page_root_id] = full_trace

        next_page_num += 1

        slots: Dict[int, List[Optional[str]]] = {
            0: [page_root_id],
            1: [None] * 2,
            2: [None] * 4,
            3: [None] * 8,
        }

        for gen in range(3):
            for i, pid in enumerate(slots[gen]):
                if not pid:
                    continue
                p = person_map.get(pid)
                if not p:
                    continue
                slots[gen + 1][2 * i] = p.father_id or None
                slots[gen + 1][2 * i + 1] = p.mother_id or None

        leaf_abs_gen = page_root_abs_gen + 3
        parents_abs_gen = leaf_abs_gen + 1
        parents_allowed = parents_abs_gen <= max_gens

        if parents_allowed:
            for leaf_id in slots[3]:
                if not leaf_id:
                    continue
                leaf_person = person_map.get(leaf_id)
                if not _has_parents(leaf_person):
                    continue
                queue.append((leaf_id, full_trace, leaf_abs_gen))

    return page_map, breadcrumb_map


# ============================================================
# Renderer with auto box height per generation (no overlap)
# ============================================================
class AncestryChartRenderer:
    def __init__(
        self,
        output_pdf: str,
        person_map: Dict[str, VisualPerson],
        page_map: Dict[str, int],
        breadcrumb_map: Dict[str, List[str]],
    ):
        self.person_map = person_map
        self.page_map = page_map
        self.breadcrumb_map = breadcrumb_map

        # 11x17 landscape in points
        self.W, self.H = (17 * inch, 11 * inch)
        self.c = Canvas(output_pdf, pagesize=(self.W, self.H))

        # Margins/header
        self.margin_left = 36
        self.margin_right = 36
        self.margin_top = 30
        self.margin_bottom = 30

        self.title_y = self.H - self.margin_top
        self.breadcrumb_y = self.title_y - 18

        # Chart area
        self.chart_top = self.breadcrumb_y - 24
        self.chart_bottom = self.margin_bottom + 24
        self.chart_h = self.chart_top - self.chart_bottom

        # Right gutter for To P.#
        self.to_marker_gutter = 90
        chart_w = self.W - self.margin_left - self.margin_right - self.to_marker_gutter

        self.col_w = chart_w / 4.0
        self.box_w = self.col_w * 0.96

        # Fonts
        self.font_title = ("Helvetica-Bold", 16)
        self.font_breadcrumb = ("Helvetica", 8)
        self.font_page = ("Helvetica", 10)

        self.font_name = ("Helvetica-Bold", 9)
        self.font_body = ("Helvetica", 7.5)

        # Layout knobs
        self.pad_x = 10
        self.pad_top = 10
        self.pad_bottom = 6
        self.name_gap = 2         # space from name line to first body line
        self.line_gap = 11         # body line spacing

        # Colors
        self.border_gray = (0.55, 0.55, 0.55)
        self.text_black = (0.0, 0.0, 0.0)
        self.link_blue = (0.05, 0.25, 0.85)

        self.line_w_border = 0.7
        self.line_w_conn = 1.0

        # Computed per page: box height for each generation (0..3)
        self._box_h_by_gen: Dict[int, float] = {}

    def _wrap_text(self, text: str, max_width: float, font_name: str, font_size: float) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []
        words = re.split(r"\s+", text)
        lines: List[str] = []
        cur: List[str] = []
        for w in words:
            trial = (" ".join(cur + [w])).strip()
            if stringWidth(trial, font_name, font_size) <= max_width:
                cur.append(w)
            else:
                if cur:
                    lines.append(" ".join(cur))
                    cur = [w]
                else:
                    lines.append(w)
                    cur = []
        if cur:
            lines.append(" ".join(cur))
        return lines

    def _col_x(self, gen: int) -> float:
        col_left = self.margin_left + gen * self.col_w
        return col_left + (self.col_w - self.box_w) / 2.0

    def _slot_center_y(self, gen: int, slot_index: int) -> float:
        total_slots = 2 ** gen
        slot_h = self.chart_h / total_slots
        return self.chart_top - (slot_index + 0.5) * slot_h

    def _slot_h(self, gen: int) -> float:
        return self.chart_h / (2 ** gen)

    # ---- compute "render plan" for a person (lines to draw) ----
    def _person_lines(self, p: VisualPerson) -> Tuple[str, List[str]]:
        """
        Returns:
          name_line, body_lines
        """
        max_text_w = self.box_w - 2 * self.pad_x

        name_line = (p.name or p.id).strip()

        body_lines: List[str] = []
        if p.birt_date:
            body_lines.append(f"B: {p.birt_date}")
        if p.birt_place:
            body_lines.extend(self._wrap_text(p.birt_place, max_text_w, self.font_body[0], self.font_body[1]))

        if p.marr_date:
            body_lines.append(f"M: {p.marr_date}")

        if p.deat_date:
            body_lines.append(f"D: {p.deat_date}")
        if p.deat_place:
            body_lines.extend(self._wrap_text(p.deat_place, max_text_w, self.font_body[0], self.font_body[1]))

        return name_line, body_lines

    def _required_box_height(self, p: Optional[VisualPerson]) -> float:
        """
        Compute the minimum box height needed to render all lines for this person,
        based on current font sizes/spacing.
        """
        if not p:
            # empty box: minimal height (still reasonable)
            return 24.0

        _, body = self._person_lines(p)

        # name consumes 1 line of name font
        # then we step down name_gap and render body lines at line_gap
        needed = (
            self.pad_top
            + self.font_name[1]
            + self.name_gap
            + (len(body) * self.line_gap)
            + self.pad_bottom
        )
        # keep a minimum so box looks like the reference even for tiny entries
        return max(48.0, float(needed))

    def _plan_box_heights_for_page(self, slots: Dict[int, List[Optional[str]]]) -> None:
        """
        For each generation (0..3), compute a single box height to use for all boxes
        in that generation on THIS page, so boxes can touch but never overlap.
        """
        self._box_h_by_gen = {}

        for gen in range(4):
            slot_h = self._slot_h(gen)
            # allow boxes to touch: max height is exactly slot_h
            # but keep a tiny epsilon to avoid rounding overlap
            max_allowed = max(10.0, slot_h - 1.0)

            # compute max required among people in that gen
            req = 0.0
            for pid in slots[gen]:
                p = self.person_map.get(pid) if pid else None
                req = max(req, self._required_box_height(p))

            self._box_h_by_gen[gen] = min(req, max_allowed)

    # ---- drawing ----
    def draw_header(self, page_root_id: str, page_num: int):
        root = self.person_map.get(page_root_id)
        root_name = root.name if root else page_root_id

        self.c.setFont(*self.font_title)
        self.c.setFillColorRGB(*self.text_black)
        self.c.drawString(self.margin_left, self.title_y, f"Ancestry Chart — {root_name}")

        self.c.setFont(*self.font_page)
        page_label = f"Page {page_num}"
        pw = stringWidth(page_label, self.font_page[0], self.font_page[1])
        self.c.drawString(self.W - self.margin_right - pw, self.title_y, page_label)

        crumbs = self.breadcrumb_map.get(page_root_id, [])
        crumb_text = " > ".join(crumbs)
        self.c.setFont(*self.font_breadcrumb)
        self.c.drawString(self.margin_left, self.breadcrumb_y, crumb_text[:220])

    def _draw_box_rect(self, x: float, y_center: float, box_h: float):
        y = y_center - box_h / 2.0
        self.c.setLineWidth(self.line_w_border)
        self.c.setStrokeColorRGB(*self.border_gray)
        self.c.setFillColorRGB(1, 1, 1)
        self.c.rect(x, y, self.box_w, box_h, fill=1, stroke=1)
        return y

    def draw_box(self, gen: int, person: Optional[VisualPerson], x: float, y_center: float):
        box_h = self._box_h_by_gen.get(gen, self._slot_h(gen) - 1.0)
        by = self._draw_box_rect(x, y_center, box_h)

        if not person:
            return

        # set visible text
        self.c.setFillColorRGB(*self.text_black)

        name_line, body_lines = self._person_lines(person)

        # coordinates
        text_x = x + self.pad_x
        y = by + box_h - self.pad_top

        # name
        self.c.setFont(*self.font_name)
        self.c.drawString(text_x, y, name_line[:120])
        y -= self.name_gap

        # body lines with truncation if needed
        self.c.setFont(*self.font_body)
        bottom_limit = by + self.pad_bottom

        truncated = False
        for line in body_lines:
            y -= self.line_gap
            if y < bottom_limit:
                truncated = True
                break
            self.c.drawString(text_x, y, line[:200])

        if truncated:
            # draw ellipsis at the bottom if we ran out of space
            ell = "…"
            self.c.drawString(text_x, bottom_limit, ell)

    def draw_connector(self, child_gen: int, child_slot: int, parent_gen: int, parent_slot: int):
        # right-angle connector
        cx = self._col_x(child_gen)
        cy = self._slot_center_y(child_gen, child_slot)
        px = self._col_x(parent_gen)
        py = self._slot_center_y(parent_gen, parent_slot)

        child_right_x = cx + self.box_w
        parent_left_x = px

        trunk_x = (child_right_x + parent_left_x) / 2.0

        self.c.setLineWidth(self.line_w_conn)
        self.c.setStrokeColorRGB(0, 0, 0)
        self.c.line(child_right_x, cy, trunk_x, cy)
        self.c.line(trunk_x, cy, trunk_x, py)
        self.c.line(trunk_x, py, parent_left_x, py)

    def draw_to_page_marker(self, y_center: float, target_page: int):
        label = f"To P.{target_page}"
        self.c.setFont("Helvetica-Oblique", 8)
        self.c.setFillColorRGB(*self.link_blue)

        marker_x = self.W - self.margin_right - self.to_marker_gutter + 10
        self.c.drawString(marker_x, y_center - 3, label)

        sq = 7
        sq_x = self.W - self.margin_right - 12
        sq_y = y_center - sq / 2
        self.c.setFillColorRGB(*self.link_blue)
        self.c.setStrokeColorRGB(*self.link_blue)
        self.c.rect(sq_x, sq_y, sq, sq, fill=1, stroke=0)

        self.c.setFillColorRGB(*self.text_black)

    def draw_page(self, page_root_id: str, page_num: int):
        if page_num > 1:
            self.c.showPage()

        self.draw_header(page_root_id, page_num)

        slots: Dict[int, List[Optional[str]]] = {
            0: [page_root_id],
            1: [None] * 2,
            2: [None] * 4,
            3: [None] * 8,
        }

        for gen in range(3):
            for i, pid in enumerate(slots[gen]):
                if not pid:
                    continue
                p = self.person_map.get(pid)
                if not p:
                    continue
                slots[gen + 1][2 * i] = p.father_id or None
                slots[gen + 1][2 * i + 1] = p.mother_id or None

        # NEW: compute per-gen box heights so boxes can expand but never overlap
        self._plan_box_heights_for_page(slots)

        # connectors
        for gen in range(3):
            for i, pid in enumerate(slots[gen]):
                if not pid:
                    continue
                father_id = slots[gen + 1][2 * i]
                mother_id = slots[gen + 1][2 * i + 1]
                if father_id:
                    self.draw_connector(gen, i, gen + 1, 2 * i)
                if mother_id:
                    self.draw_connector(gen, i, gen + 1, 2 * i + 1)

        # boxes
        for gen in range(4):
            x = self._col_x(gen)
            for i in range(2 ** gen):
                pid = slots[gen][i]
                person = self.person_map.get(pid) if pid else None
                y = self._slot_center_y(gen, i)
                self.draw_box(gen, person, x, y)

        # To P.# markers for gen=3
        for i, pid in enumerate(slots[3]):
            if not pid:
                continue
            if pid not in self.page_map:
                continue
            y = self._slot_center_y(3, i)
            self.draw_to_page_marker(y, self.page_map[pid])

    def save(self):
        self.c.save()


def render_chart(
    output_pdf: str,
    person_map: Dict[str, VisualPerson],
    page_map: Dict[str, int],
    breadcrumb_map: Dict[str, List[str]],
):
    engine = AncestryChartRenderer(output_pdf, person_map, page_map, breadcrumb_map)
    for pid, pnum in sorted(page_map.items(), key=lambda t: t[1]):
        engine.draw_page(pid, pnum)
    engine.save()


def create_visual_tree(csv_path: str, output_pdf: str, root_id: str, max_gens: int):
    person_map = load_person_map(csv_path)
    page_map, breadcrumb_map = build_page_plan(person_map, root_id, max_gens)
    render_chart(output_pdf, person_map, page_map, breadcrumb_map)
