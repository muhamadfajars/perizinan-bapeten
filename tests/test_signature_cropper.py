import base64
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from src.extraction.signature_cropper import (
    crop_sprint_signature_stamp,
    crop_and_save_sprint_signature,
    get_sprint_signature_preview,
    pil_to_base64,
)


def _create_mock_document_image(width=1000, height=1400) -> Image.Image:
    """Creates a mock document image with header and signature area."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Header
    draw.text((200, 100), "SURAT PERINTAH", fill=(0, 0, 0))
    draw.text((100, 300), "DIPERINTAHKAN: Kepada ...", fill=(0, 0, 0))
    # Signature quadrant (bottom right)
    draw.text((600, 900), "Pekanbaru, 19 Agustus 2026", fill=(0, 0, 0))
    draw.text((600, 940), "Kepala Rumah Sakit TK IV", fill=(0, 0, 0))
    # Stamp (blue ellipse)
    draw.ellipse([(550, 970), (750, 1100)], outline=(30, 60, 180), width=3)
    # Signature (black line)
    draw.line([(620, 1030), (720, 1050), (660, 1080)], fill=(0, 0, 0), width=2)
    # Signer name
    draw.text((600, 1120), "dr. Adimas Okto Nugroho, Sp.Rad", fill=(0, 0, 0))
    draw.text((600, 1160), "Mayor Ckm 11100002031082", fill=(0, 0, 0))
    return img


def test_crop_sprint_signature_stamp_from_image():
    mock_img = _create_mock_document_image()
    cropped = crop_sprint_signature_stamp(mock_img)
    assert cropped is not None
    assert isinstance(cropped, Image.Image)
    assert cropped.width > 100
    assert cropped.height > 100
    # Expected bottom-right aspect ratio
    assert cropped.width < mock_img.width
    assert cropped.height < mock_img.height


def test_pil_to_base64_conversion():
    img = Image.new("RGB", (50, 50), color=(255, 0, 0))
    b64 = pil_to_base64(img)
    assert isinstance(b64, str)
    assert len(b64) > 0
    # Decode and check
    raw = base64.b64decode(b64)
    reloaded = Image.open(BytesIO(raw))
    assert reloaded.size == (50, 50)


def test_crop_and_save_sprint_signature(tmp_path):
    mock_img = _create_mock_document_image()
    img_file = tmp_path / "mock_sprint.png"
    mock_img.save(img_file)

    res = crop_and_save_sprint_signature(img_file, output_dir=tmp_path)
    assert res is not None
    assert "crop_path" in res
    assert "crop_base64" in res
    assert Path(res["crop_path"]).exists()
    assert res["width"] > 0
    assert res["height"] > 0


def test_get_sprint_signature_preview_variations(tmp_path):
    # 1. None or empty doc
    assert get_sprint_signature_preview(None) is None
    assert get_sprint_signature_preview({}) is None

    # 2. Direct base64 on document
    doc_with_b64 = {"signature_crop_base64": "MOCK_BASE64_DATA"}
    assert get_sprint_signature_preview(doc_with_b64) == "data:image/png;base64,MOCK_BASE64_DATA"

    # 3. Direct path on document
    sample_file = tmp_path / "sample_crop.png"
    sample_file.write_bytes(b"PNG_DATA")
    doc_with_path = {"signature_crop_path": str(sample_file)}
    assert get_sprint_signature_preview(doc_with_path) == str(sample_file)

    # 4. From fields.pengesahan
    doc_with_field = {
        "fields": {
            "pengesahan": {
                "crop_base64": "FIELD_B64_DATA"
            }
        }
    }
    assert get_sprint_signature_preview(doc_with_field) == "data:image/png;base64,FIELD_B64_DATA"


def test_crop_real_sprint_pdf_if_available():
    uploaded_pdf = Path(r"C:\Users\muham\.gemini\antigravity-ide\brain\26693447-e9a6-4fc6-91c3-bb5a45dd71b4\.user_uploaded\media_1791186900108.pdf")
    if not uploaded_pdf.exists():
        pytest.skip("User uploaded sprint PDF not present in environment")

    cropped = crop_sprint_signature_stamp(uploaded_pdf)
    assert cropped is not None
    assert cropped.width > 200
    assert cropped.height > 100
