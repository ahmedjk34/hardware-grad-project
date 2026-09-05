#!/usr/bin/env python3
"""Assemble the graduation project report as a .docx."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.section import WD_SECTION

from docbuild import Report, new_document, page_numbers, running_header, start_numbering_at
from part_front import chapter_1, front_matter, title_page
from part_ch2 import chapter_2
from part_ch3 import chapter_3
from part_ch4 import chapter_4
from part_ch5 import chapter_5
from part_ch6 import appendices, chapter_6, references

OUT = sys.argv[1] if len(sys.argv) > 1 else "Graduation_Project_Report.docx"

doc = new_document()

# --- section 1: title page, no header/footer ---
sec = doc.sections[0]
sec.different_first_page_header_footer = True
title_page(doc)

# --- section 2: front matter, roman numerals ---
front = doc.add_section(WD_SECTION.NEW_PAGE)
front.footer.is_linked_to_previous = False
front.header.is_linked_to_previous = False
running_header(front, "Vision-Assisted Cartesian Robotic System for 3D Block Construction")
page_numbers(front, label="")
start_numbering_at(front, 1, "lowerRoman")

rep = Report(doc)
front_matter(rep)

# --- section 3: the body, arabic numerals from 1 ---
body = doc.add_section(WD_SECTION.NEW_PAGE)
body.footer.is_linked_to_previous = False
body.header.is_linked_to_previous = False
running_header(body, "Vision-Assisted Cartesian Robotic System for 3D Block Construction")
page_numbers(body, label="")
start_numbering_at(body, 1, "decimal")

chapter_1(rep)
chapter_2(rep)
chapter_3(rep)
chapter_4(rep)
chapter_5(rep)
chapter_6(rep)
references(rep)
appendices(rep)

doc.save(OUT)
print("wrote %s" % OUT)
print("  figures: %d" % len(rep.figures))
print("  tables:  %d" % len(rep.tables))
