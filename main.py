import argparse
import json
from pathlib import Path

from src.pipeline import execute_run


def main():
    parser = argparse.ArgumentParser(description="BAPETEN document extraction and cross-check pipeline")
    parser.add_argument("--input", action="append", help="doc_type=path, repeatable. Example: --input formulir=data/formulir.pdf")
    args = parser.parse_args()

    if not args.input:
        parser.error("Provide at least one --input doc_type=path argument.")

    document_inputs = {}
    for item in args.input:
        if "=" not in item:
            parser.error(f"Invalid --input: {item}. Use doc_type=path")
        doc_type, path = item.split("=", 1)
        document_inputs.setdefault(doc_type, []).append(Path(path))

    result = execute_run(document_inputs)
    print(json.dumps({
        "run_id": result["run_id"],
        "summary": result["summary"],
        "documents": result["documents"],
        "result_json": result["artifacts"]["result_json"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
