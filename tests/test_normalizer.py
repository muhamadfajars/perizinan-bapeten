from src.matching.normalizer import (
    normalize,
    normalize_serial,
    normalize_date,
    normalize_person_name,
    normalize_address,
    normalize_brand,
    normalize_facility_name,
)


def test_normalize():
    assert normalize("E7894/ 0F1376") == "E78940F1376"


def test_normalize_serial():
    assert normalize_serial("E7894/OI37") == "E78940137"


def test_normalize_date():
    assert normalize_date("3 Agustus 2026") == "03/08/2026"


def test_normalize_person_name():
    assert normalize_person_name("Dr. Andi Wijaya, Sp.Rad") == "ANDI WIJAYA"
    assert normalize_person_name("dr. Budi Santoso, M.Kes, Sp.Rad(K)") == "BUDI SANTOSO"
    assert normalize_person_name("Siti Rahma, A.Md.Rad.") == "SITI RAHMA"


def test_normalize_address():
    assert normalize_address("Jalan Gatot Subroto Nomor 12") == "JL GATOT SUBROTO NO 12"
    assert normalize_address("Jl. Kramat Raya No. 45, Kelurahan Kwitang") == "JL KRAMAT RAYA NO 45 KEL KWITANG"
    assert normalize_address("Jl.Kesehatanno2PekanbaruRiau") == "JL KESEHATAN NO 2 PEKANBARU RIAU"
    assert normalize_address("Jl.Kesehatanno.02") == "JL KESEHATAN NO 2"
    assert normalize_address("Rumkit Tentara Tk IV 01.07.04 Pekanbaru, Jl. Kesehatan No. 2 Kampung") == "JL KESEHATAN NO 2 KP"
    # Strips CAF/Uji Fungsi mechanical test checklist artifacts
    assert normalize_address("Jl. Kesehatan No.2, Kp. Bandar, Kec. Senapelan, Kota Pekanbaru, Riau Collimator Rotation PASS") == "JL KESEHATAN NO 2 KP BANDAR KEC SENAPELAN PEKANBARU RIAU"
    # OCR typo ungluing
    assert normalize_address("JL. Kesehatann0.02") == "JL KESEHATAN NO 2"


def test_normalize_facility_name():
    assert normalize_facility_name("Rumkit Tentara Tk IV 01.07.04 Pekanbaru") == "RS TK IV PEKANBARU"
    assert normalize_facility_name("Rumkit Tk. IV Pekanbaru Tube tilt PASS") == "RS TK IV PEKANBARU"


def test_normalize_brand():
    assert normalize_brand("SHIMADZU CORPORATION") == "SHIMADZU"
    assert normalize_brand("GE HEALTHCARE") == "GE"
    assert normalize_brand("CANON ELECTRON TUBES & DEVICES CO., LTD.") == "CANON"

