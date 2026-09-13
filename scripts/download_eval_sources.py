#!/usr/bin/env python3
"""Download the pinned public inputs used by commerce_bench_zh.

Downloads are kept outside the repository by default.  The builder only
commits the small adapted evaluation artifacts, not the full upstream data.
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path


SOURCES = [
    (
        "bitext-retail.csv",
        "https://huggingface.co/datasets/bitext/Bitext-retail-ecommerce-llm-chatbot-training-dataset/resolve/main/bitext-retail-ecommerce-llm-chatbot-training-dataset.csv",
        "13a988266fed4e2b2c1ff947a89ef220ce09b5b13ac83c4a1496c0d7b81e8127",
    ),
    (
        "chinese-ambiguous-reference.json",
        "https://raw.githubusercontent.com/ygan/Chinese-Ambiguous-Reference/3fe3a42233571914ee4a5ccaec3f3af97966d9c9/All%20Conversation.json",
        "36631734421c1b892b30e9f7298ab1f29bfc1de5ccc59fe14bbc91a1256377fe",
    ),
    (
        "product_infomation.zip",
        "https://huggingface.co/datasets/InfiniFlow/Ecommerce-Customer-Service-Workflow/resolve/main/product_infomation.zip",
        "4cf8edc73a6e6e5633251db7ef6855cd118428067b61fd1ff488567878b936be",
    ),
    (
        "user_guide.zip",
        "https://huggingface.co/datasets/InfiniFlow/Ecommerce-Customer-Service-Workflow/resolve/main/user_guide.zip",
        "722d3942e663c7096b6803a7b87e060f3efedc3e5897a99712ef5037440d56ef",
    ),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/commerce-agent-eval-sources"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, url, expected_hash in SOURCES:
        target = args.output_dir / filename
        if not target.exists() or sha256(target) != expected_hash:
            print(f"downloading {filename} ...")
            urllib.request.urlretrieve(url, target)
        actual_hash = sha256(target)
        if actual_hash != expected_hash:
            raise RuntimeError(f"sha256 mismatch for {filename}: {actual_hash}")
        print(f"verified {filename} {actual_hash}")


if __name__ == "__main__":
    main()
