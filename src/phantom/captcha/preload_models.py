"""Preload EasyOCR model files into the user's normal EasyOCR cache."""
from .solver import (
    _configure_certifi_for_urllib,
    _easyocr_models_ready,
    _missing_easyocr_models,
    _patch_easyocr_urlretrieve,
)


def main():
    import easyocr

    model_dir, missing = _missing_easyocr_models()
    if not missing:
        print(f"EasyOCR model cache hazir: {model_dir}")
        return 0

    print(f"EasyOCR model cache eksik: {', '.join(missing)}")
    print(f"EasyOCR model cache hedefi: {model_dir}")

    cafile, cert_error = _configure_certifi_for_urllib()
    if cafile:
        ok, patch_error = _patch_easyocr_urlretrieve(cafile=cafile)
        if ok:
            print(f"EasyOCR indirme certifi ile deneniyor: {cafile}")
        elif patch_error:
            print(f"EasyOCR certifi indirme ayari yapilamadi: {patch_error}")
    elif cert_error:
        print(f"EasyOCR certifi hazir degil: {cert_error}")

    try:
        easyocr.Reader(["tr", "en"], gpu=False, verbose=False)
    except Exception as exc:
        if not _easyocr_models_ready():
            ok, patch_error = _patch_easyocr_urlretrieve(insecure=True)
            if ok:
                print("EasyOCR indirme MD5 kontrollu yedek modda deneniyor")
                easyocr.Reader(["tr", "en"], gpu=False, verbose=False)
            elif patch_error:
                print(f"EasyOCR yedek indirme ayari yapilamadi: {patch_error}")
                raise exc
        else:
            raise

    if not _easyocr_models_ready():
        _, still_missing = _missing_easyocr_models()
        raise RuntimeError(f"EasyOCR model dosyalari hala eksik: {', '.join(still_missing)}")

    print(f"EasyOCR model cache hazir: {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
