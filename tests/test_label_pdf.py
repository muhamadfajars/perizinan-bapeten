from pathlib import Path
import pypdfium2 as pdfium
import tempfile
from PIL import Image, ImageDraw

from src.services.run_service import _convert_label_to_image
from src.ocr.preprocess import preprocess_image


def test_pdf_label_handling():
    # Create a temporary PDF file simulating a scanned label PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = Path(tmp_pdf.name)

    try:
        # Create a simple image and save it as PDF
        img = Image.new("RGB", (400, 200), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 50), "MODEL: CIRCLEX", fill="black")
        draw.text((20, 80), "SER. NO: TB-123456", fill="black")
        img.save(str(pdf_path), "PDF")

        # 1. Test _convert_label_to_image converts PDF to temporary PNG
        converted_path, is_temp = _convert_label_to_image(pdf_path)
        assert is_temp is True
        assert converted_path.exists()
        assert converted_path.suffix.lower() == ".png"
        converted_path.unlink()

        # 2. Test preprocess_image handles PDF without FileNotFoundError
        thresh = preprocess_image(str(pdf_path))
        assert thresh is not None
        assert thresh.shape[0] > 0
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


def test_combined_pdf_page_selection(monkeypatch):
    from src.services.run_service import _get_label_page_ocr

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = Path(tmp_pdf.name)

    try:
        # Create 2-page PDF: Page 1 Unit, Page 2 Tube
        img1 = Image.new("RGB", (300, 200), color="white")
        img2 = Image.new("RGB", (300, 200), color="white")
        img1.save(str(pdf_path), "PDF", save_all=True, append_images=[img2])

        # Mock OCR responses for page 0 and page 1
        page0_lines = [
            {"text": "SHANGHAI UNITED IMAGING", "conf": 0.99, "x": 10, "y": 20},
            {"text": "MODEL: uDR 566i-A", "conf": 0.99, "x": 10, "y": 50},
            {"text": "S/N: 0123", "conf": 0.99, "x": 10, "y": 80},
        ]
        page1_lines = [
            {"text": "CANON ELECTRON TUBES & DEVICES", "conf": 0.99, "x": 10, "y": 20},
            {"text": "HOUSING MODEL: E7876X", "conf": 0.99, "x": 10, "y": 50},
            {"text": "SER. NO: 25D1063", "conf": 0.99, "x": 10, "y": 80},
        ]

        def fake_run_ocr(img_p, cache_key=""):
            if "p0" in cache_key:
                return page0_lines
            return page1_lines

        from src.services import run_service
        monkeypatch.setattr(run_service, "run_ocr", fake_run_ocr)

        # 1. label_unit selects Page 1
        u_lines, u_page, u_img, u_temp = _get_label_page_ocr(pdf_path, "label_unit", "run1")
        assert u_page == 1
        assert any("UNITED IMAGING" in l["text"] for l in u_lines)
        if u_temp and u_img.exists():
            u_img.unlink()

        # 2. label_tabung selects Page 2
        t_lines, t_page, t_img, t_temp = _get_label_page_ocr(pdf_path, "label_tabung", "run1")
        assert t_page == 2
        assert any("CANON ELECTRON TUBES" in l["text"] for l in t_lines)
        if t_temp and t_img.exists():
            t_img.unlink()
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


def test_execute_run_with_combined_label_pdf(monkeypatch):
    from src.services.run_service import execute_run

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = Path(tmp_pdf.name)

    try:
        # Create 2-page PDF
        img1 = Image.new("RGB", (300, 200), color="white")
        img2 = Image.new("RGB", (300, 200), color="white")
        img1.save(str(pdf_path), "PDF", save_all=True, append_images=[img2])

        page0_lines = [
            {"text": "SHANGHAI UNITED IMAGING", "conf": 0.99, "x": 10, "y": 20},
            {"text": "MODEL: uDR 566i-A", "conf": 0.99, "x": 10, "y": 50},
            {"text": "S/N: SN-UNIT-001", "conf": 0.99, "x": 10, "y": 80},
        ]
        page1_lines = [
            {"text": "CANON ELECTRON TUBES & DEVICES", "conf": 0.99, "x": 10, "y": 20},
            {"text": "HOUSING MODEL: E7876X", "conf": 0.99, "x": 10, "y": 50},
            {"text": "SER. NO: TB-TUBE-999", "conf": 0.99, "x": 10, "y": 80},
        ]

        def fake_run_ocr(img_p, cache_key=""):
            if "p0" in cache_key:
                return page0_lines
            return page1_lines

        from src.services import run_service
        monkeypatch.setattr(run_service, "run_ocr", fake_run_ocr)

        # Upload only to 'label_unit'
        result = execute_run({"label_unit": [pdf_path]})

        # Both unit and tube entities must be extracted from the single combined PDF!
        eq = result["application"]["xray_equipment"][0]
        assert eq["unit_serial_number"]["value"] == "SN-UNIT-001"
        assert eq["tube"]["tube_serial_number"]["value"] == "TB-TUBE-999"

        # Both documents must be recognized as present
        assert "label_unit" in result["documents"]
        assert "label_tabung" in result["documents"]

        presence_map = {p["document_type"]: p["uploaded"] for p in result["presence"]}
        assert presence_map["label_unit"] is True
        assert presence_map["label_tabung"] is True
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
