def sort_by_y(ocr_lines):
    return sorted(ocr_lines, key=lambda l: l["y"])


def join_ocr_text(ocr_lines):
    return "\n".join(l["text"] for l in sort_by_y(ocr_lines))
