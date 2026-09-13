"""Explicit bounded Open Images V5 acquisition with reproducibly ordered candidates."""

import argparse
import base64
import binascii
import csv
import io
import re
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from memotrace_ml.acquire import download, receipt_json
from memotrace_ml.artifacts import ensure_directory, entries, reader
from memotrace_ml.common import (
    JSON,
    external_root,
    file_digest,
    fingerprint,
    object_value,
    read_json,
    string_value,
    write_json,
)
from memotrace_ml.dataset import Item, load_items
from memotrace_ml.images import MAX_IMAGE_BYTES, decode_jpeg, validate_box

SOURCE = "https://storage.googleapis.com/openimages/web/download_v5.html"
BUCKET = "https://storage.googleapis.com/openimages/"
IMAGE_BUCKET = "https://open-images-dataset.s3.amazonaws.com/validation/"
LICENSE = "https://creativecommons.org/licenses/by/2.0/"
CLASS_PROFILE = (
    ("Screwdriver", "/m/01bms0"),
    ("Scissors", "/m/01lsmm"),
    ("Hammer", "/m/03l9g"),
    ("Knife", "/m/04ctx"),
    ("Pen", "/m/0k1tl"),
    ("Bottle", "/m/04dr76w"),
    ("Mug", "/m/02jvh9"),
    ("Mobile phone", "/m/050k8"),
)
CLASSES = dict(CLASS_PROFILE)
CLASS_PROFILE_ID = "openimages-everyday-object-pilot"
CLASS_PROFILE_VERSION = "v3"
SELECTION_VERSION = CLASS_PROFILE_ID + "-" + CLASS_PROFILE_VERSION
DATASET_NAME = "openimages-everyday-object-validation"
DATASET_VERSION_PREFIX = "v5-everyday-object-pilot-v3-"
METADATA = {
    "classes.csv": "v5/class-descriptions-boxable.csv",
    "boxes.csv": "v5/validation-annotations-bbox.csv",
    "labels.csv": "v5/validation-annotations-human-imagelabels-boxable.csv",
    "images.csv": "2018_04/validation/validation-images-with-rotation.csv",
}
METADATA_SHA256 = {
    "classes.csv": "2fa47fb1b87e71c90b9fbee2dc1184eb8c59601bb811ea4424b200653cedff8e",
    "boxes.csv": "d8bbd59410af14835d7733165a7bb8a3f0213981b22dd5077b0b9f7878991ff2",
    "labels.csv": "d5ff236d3cdbba36dac1ee6f7fdf9a26934205cbec5b933b0872722e2b6d3417",
    "images.csv": "ed93a0e121fe345effdfc7359b848dbc64a1ff6778c8c73563157cb500b33a17",
}


def class_profile() -> dict[str, JSON]:
    return {
        "id": CLASS_PROFILE_ID,
        "version": CLASS_PROFILE_VERSION,
        "classes": [{"name": name, "mid": mid} for name, mid in CLASS_PROFILE],
    }


def validate_acquisition_profile(
    selection: dict[str, JSON],
    ground_truth: dict[str, JSON],
    dataset: dict[str, JSON],
) -> None:
    selection_classes = object_value(selection.get("classes"))
    ground_truth_classes = object_value(ground_truth.get("classes"))
    names = [name for name, _ in CLASS_PROFILE]
    mids = [mid for _, mid in CLASS_PROFILE]
    if (
        selection.get("version") != SELECTION_VERSION
        or selection.get("class_profile") != class_profile()
        or set(selection_classes) != set(names)
        or ground_truth.get("version") != "1"
        or set(ground_truth_classes) != set(mids)
        or any(
            object_value(ground_truth_classes[mid]).get("name") != name
            for name, mid in CLASS_PROFILE
        )
        or dataset.get("name") != DATASET_NAME
        or dataset.get("version") != DATASET_VERSION_PREFIX + fingerprint(selection)[:16]
        or dataset.get("source") != SOURCE
        or dataset.get("license") != LICENSE
    ):
        raise ValueError("Open Images acquisition profile mismatch")


def rows(path: Path) -> Iterator[dict[str, str]]:
    with (
        reader(path, 128 * 1024 * 1024) as raw,
        io.TextIOWrapper(raw, newline="", encoding="utf-8") as source,
    ):
        yield from csv.DictReader(source)


def labels_from(path: Path) -> dict[str, dict[str, bool]]:
    labels: dict[str, dict[str, bool]] = {mid: {} for mid in CLASSES.values()}
    for row in rows(path):
        mid = row["LabelName"]
        if mid not in labels or row["Source"] not in {"verification", "crowdsource-verification"}:
            continue
        if row["Confidence"] not in {"0", "1"}:
            raise ValueError("invalid human label confidence")
        image_id, positive = row["ImageID"], row["Confidence"] == "1"
        if image_id in labels[mid] and labels[mid][image_id] != positive:
            raise ValueError("contradictory human labels")
        labels[mid][image_id] = positive
    return labels


def original_properties(row: dict[str, str]) -> tuple[int, str]:
    try:
        size_text = row["OriginalSize"]
        size = int(size_text)
        encoded_md5 = row["OriginalMD5"]
        raw_md5 = base64.b64decode(encoded_md5, validate=True)
        title = row["Title"]
    except (KeyError, ValueError, binascii.Error):
        raise ValueError("invalid official image content metadata") from None
    if (
        str(size) != size_text
        or not 0 < size <= 2**63 - 1
        or len(raw_md5) != 16
        or base64.b64encode(raw_md5).decode("ascii") != encoded_md5
        or not isinstance(title, str)
    ):
        raise ValueError("invalid official image content metadata")
    return size, raw_md5.hex()


def attribution_url(value: JSON) -> str:
    url = string_value(value)
    parsed = urlsplit(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError("invalid attribution URL")
    return url


def validate_attribution(attribution: dict[str, JSON], items: list[Item]) -> None:
    if set(attribution) != {item.id for item in items}:
        raise ValueError("attribution image set mismatch")
    for item in items:
        entry = object_value(attribution[item.id])
        if set(entry) != {
            "download",
            "license",
            "author",
            "title",
            "author_profile_url",
            "original_url",
            "landing_url",
            "rotation",
            "original_size",
            "original_md5",
        }:
            raise ValueError("invalid attribution entry")
        download = object_value(entry["download"])
        if download != {
            "source": IMAGE_BUCKET + item.id + ".jpg",
            "sha256": item.sha256,
            "byte_length": item.byte_length,
        }:
            raise ValueError("attribution download mismatch")
        size = entry["original_size"]
        md5 = entry["original_md5"]
        if (
            entry["license"] != LICENSE
            or not string_value(entry["author"])
            or not string_value(entry["title"])
            or entry["rotation"] not in {"0", "0.0"}
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= 2**63 - 1
            or not isinstance(md5, str)
            or re.fullmatch(r"[0-9a-f]{32}", md5) is None
        ):
            raise ValueError("invalid attribution content")
        for name in ("license", "author_profile_url", "original_url", "landing_url"):
            attribution_url(entry[name])


def verified_acquisition(root: Path) -> tuple[dict[str, JSON], dict[str, JSON], list[Item]]:
    """Verify a previously completed durable receipt before reusing any JPEG.

    The receipt is a trusted local acquisition record, not a digital signature.
    An operator controlling both receipt and files remains inside the trust boundary.
    """
    receipt = read_json(root / "acquisition.json")
    for field, name in (
        ("manifest_sha256", "manifest.json"),
        ("ground_truth_sha256", "ground-truth.json"),
        ("selection_sha256", "selection.json"),
    ):
        if receipt.get(field) != file_digest(root / name):
            raise ValueError("acquisition provenance mismatch")
    if receipt.get("attribution_sha256") != file_digest(root / "attribution.json"):
        raise ValueError("attribution provenance mismatch")
    selection = read_json(root / "selection.json")
    ground_truth = read_json(root / "ground-truth.json")
    manifest = read_json(root / "manifest.json")
    validate_acquisition_profile(selection, ground_truth, object_value(manifest.get("dataset")))
    dataset, items = load_items(root / "manifest.json")
    attribution = read_json(root / "attribution.json")
    validate_attribution(attribution, items)
    selected_content = [
        {
            "id": item.id,
            "sha256": item.sha256,
            "byte_length": item.byte_length,
            "original_size": object_value(attribution[item.id])["original_size"],
            "original_md5": object_value(attribution[item.id])["original_md5"],
        }
        for item in items
    ]
    if (
        not 48 <= len(items) <= 100
        or receipt.get("count") != len(items)
        or selection.get("actual_count") != len(items)
        or selection.get("missing_count") != 0
        or selection.get("requested_count") != len(items)
        or selection.get("selected_ids") != [item.id for item in items]
        or selection.get("selected_content") != selected_content
    ):
        raise ValueError("incomplete or inconsistent acquisition")
    for name, expected in METADATA_SHA256.items():
        meta = object_value(object_value(selection["metadata"])[name])
        if (
            meta.get("sha256") != expected
            or meta.get("source") != BUCKET + METADATA[name]
            or file_digest(root / "metadata" / name) != expected
        ):
            raise ValueError("metadata provenance mismatch")
    expected_images = {Path(item.path).name for item in items}
    if set(entries(root / "images")) != expected_images:
        raise ValueError("unverified image in acquisition directory")
    return receipt, dataset, items


def validate_cvdf_jpeg(raw: bytes) -> None:
    decode_jpeg(raw).close()
    with Image.open(io.BytesIO(raw), formats=["JPEG"]) as image:
        if image.getexif().get(274, 1) != 1:
            raise ValueError("unexpected EXIF rotation in CVDF JPEG")


def round_robin_candidates(labels: dict[str, dict[str, bool]], eligible: set[str]) -> list[str]:
    # Class order, then positive/negative polarity, is part of the profile identity.
    buckets = [
        sorted(
            image_id
            for image_id, value in labels[mid].items()
            if value == positive and image_id in eligible
        )
        for mid in CLASSES.values()
        for positive in (True, False)
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for index in range(max(map(len, buckets), default=0)):
        for bucket in buckets:
            if index < len(bucket) and bucket[index] not in seen:
                seen.add(bucket[index])
                candidates.append(bucket[index])
    return candidates


def prepare(root: Path, count: int) -> dict[str, JSON]:
    if not 48 <= count <= 100:
        raise ValueError("pilot count must be 48..100")
    started = time.monotonic()
    root = external_root(root)
    existing = entries(root)
    if "acquisition.json" in existing:
        receipt, _, previous = verified_acquisition(root)
        if len(previous) != count:
            raise ValueError("existing dataset count differs; use a new artifact root")
        print(f"verified completed acquisition: {len(previous)} JPEGs; provenance unchanged")
        return receipt
    if any(
        name in existing
        for name in (
            "manifest.json",
            "ground-truth.json",
            "selection.json",
            "attribution.json",
        )
    ):
        raise ValueError("existing dataset has no completed acquisition receipt")
    metadata = root / "metadata"
    image_root = root / "images"
    # Preflight both directories before any metadata download/publication.
    for path in (metadata, image_root):
        if path.name in existing:
            entries(path)  # Reject symlink directories, even if their targets are writable.
    if image_root.name in existing and entries(image_root):
        raise ValueError("unverified existing JPEGs; acquisition will not bless cached bytes")
    ensure_directory(metadata)
    ensure_directory(image_root)
    sources: dict[str, JSON] = {}
    for name, suffix in METADATA.items():
        sources[name] = receipt_json(
            download(BUCKET + suffix, metadata / name, 128 * 1024 * 1024, METADATA_SHA256[name])
        )
        print(f"metadata verified: {name}", flush=True)
    with (
        reader(metadata / "classes.csv") as raw_classes,
        io.TextIOWrapper(raw_classes, newline="", encoding="utf-8") as source,
    ):
        classes = dict(csv.reader(source))
    for name, mid in CLASSES.items():
        if classes.get(mid) != name:
            raise ValueError("class metadata mismatch")
    labels = labels_from(metadata / "labels.csv")
    boxes: dict[str, dict[str, list[JSON]]] = {mid: {} for mid in CLASSES.values()}
    for row in rows(metadata / "boxes.csv"):
        mid, image_id = row["LabelName"], row["ImageID"]
        if mid not in boxes:
            continue
        if labels[mid].get(image_id) is False:
            raise ValueError("box contradicts human negative")
        box = validate_box([float(row[c]) for c in ("XMin", "YMin", "XMax", "YMax")])
        boxes[mid].setdefault(image_id, []).append(
            {
                "box": [*box],
                "occluded": row["IsOccluded"],
                "truncated": row["IsTruncated"],
                "group_of": row["IsGroupOf"],
                "depiction": row["IsDepiction"],
            }
        )
    info: dict[str, dict[str, str]] = {}
    for row in rows(metadata / "images.csv"):
        image_id = row["ImageID"]
        if image_id in info:
            raise ValueError("duplicate official image metadata")
        info[image_id] = row
    rejected: dict[str, int] = {
        "missing_metadata": 0,
        "license": 0,
        "rotation": 0,
        "attribution": 0,
    }
    eligible: set[str] = set()
    official_content: dict[str, tuple[int, str]] = {}
    for image_id in sorted(set().union(*(set(values) for values in labels.values()))):
        if not re.fullmatch(r"[0-9a-f]{16}", image_id):
            raise ValueError("invalid public ID")
        image_info = info.get(image_id)
        if image_info is None:
            rejected["missing_metadata"] += 1
            continue
        original_size, original_md5 = original_properties(image_info)
        if image_info["License"].replace("http://", "https://") != LICENSE:
            rejected["license"] += 1
        elif image_info["Rotation"] not in {"0", "0.0"}:
            rejected["rotation"] += 1
        elif not image_info["Author"] or not image_info["Title"]:
            rejected["attribution"] += 1
        else:
            try:
                for name in ("AuthorProfileURL", "OriginalURL", "OriginalLandingURL"):
                    attribution_url(image_info[name])
            except (KeyError, ValueError):
                rejected["attribution"] += 1
            else:
                official_content[image_id] = original_size, original_md5
                eligible.add(image_id)
    # Identity sorting and cross-bucket deduplication are independent of model scores.
    candidates = round_robin_candidates(labels, eligible)
    items: list[Item] = []
    attribution: dict[str, JSON] = {}
    selected_content: list[JSON] = []
    failures: list[JSON] = []
    for image_id in candidates[: count * 2]:
        if len(items) == count:
            break
        target = image_root / f"{image_id}.jpg"
        try:
            original_size, original_md5 = official_content[image_id]
            # OriginalSize/OriginalMD5 identify the Flickr source, not this resized derivative.
            downloaded = download(
                IMAGE_BUCKET + image_id + ".jpg",
                target,
                MAX_IMAGE_BYTES,
                seconds=90,
                validate=validate_cvdf_jpeg,
            )
            item = Item(
                image_id, f"images/{image_id}.jpg", downloaded["sha256"], downloaded["byte_length"]
            )
            items.append(item)
            selected_content.append(
                {
                    "id": item.id,
                    "sha256": item.sha256,
                    "byte_length": item.byte_length,
                    "original_size": original_size,
                    "original_md5": original_md5,
                }
            )
            row = info[image_id]
            attribution[image_id] = {
                "download": receipt_json(downloaded),
                "license": LICENSE,
                "author": row["Author"],
                "title": row["Title"],
                "author_profile_url": row["AuthorProfileURL"],
                "original_url": row["OriginalURL"],
                "landing_url": row["OriginalLandingURL"],
                "rotation": row["Rotation"],
                "original_size": original_size,
                "original_md5": original_md5,
            }
            print(f"image {len(items)}/{count}: {image_id}", flush=True)
        except (OSError, ValueError):
            failures.append({"id": image_id, "reason": "download_decode_or_orientation_failed"})
    ground_truth: dict[str, JSON] = {}
    counts: dict[str, JSON] = {}
    for name, mid in CLASSES.items():
        judgments: dict[str, JSON] = {item.id: labels[mid].get(item.id) for item in items}
        ground_truth[mid] = {
            "name": name,
            "judgments": judgments,
            "boxes": {item.id: boxes[mid].get(item.id, []) for item in items},
        }
        counts[name] = {
            "source_positive": sum(labels[mid].values()),
            "source_negative": sum(not value for value in labels[mid].values()),
            "source_box_images": len(boxes[mid]),
            "eligible_positive": sum(i in eligible and v for i, v in labels[mid].items()),
            "eligible_negative": sum(i in eligible and not v for i, v in labels[mid].items()),
            "selected_positive": sum(v is True for v in judgments.values()),
            "selected_negative": sum(v is False for v in judgments.values()),
            "selected_unknown": sum(v is None for v in judgments.values()),
            "selected_positive_without_box": sum(
                value is True and not boxes[mid].get(image_id)
                for image_id, value in judgments.items()
            ),
        }
    selection: dict[str, JSON] = {
        "version": SELECTION_VERSION,
        "class_profile": class_profile(),
        "requested_count": count,
        "actual_count": len(items),
        "missing_count": count - len(items),
        "policy": (
            "ordered-id-round-robin-class-positive-negative;first-successful-downloads;"
            "subset-may-vary-with-transient-acquisition-failures;known-zero-rotation;CC-BY-2"
        ),
        "metadata": sources,
        "classes": counts,
        "rejected_metadata": {key: value for key, value in rejected.items()},
        "download_failures": failures,
        "selected_ids": [item.id for item in items],
        "selected_content": selected_content,
        "class_profile_reason": "eight everyday objects for bilingual checkpoint evaluation",
        "annotations_license": "https://creativecommons.org/licenses/by/4.0/",
        "orientation": "unchanged CVDF JPEG;metadata rotation0;EXIF1;boxes unchanged",
    }
    dataset: dict[str, JSON] = {
        "name": DATASET_NAME,
        "version": DATASET_VERSION_PREFIX + fingerprint(selection)[:16],
        "source": SOURCE,
        "license": LICENSE,
    }
    write_json(
        root / "manifest.json",
        {
            "version": "1",
            "dataset": dataset,
            "items": [item.json() for item in items],
        },
    )
    write_json(root / "ground-truth.json", {"version": "1", "classes": ground_truth})
    write_json(root / "attribution.json", attribution)
    write_json(root / "selection.json", selection)
    receipt = {
        "count": len(items),
        "duration_seconds": time.monotonic() - started,
        "manifest_sha256": file_digest(root / "manifest.json"),
        "ground_truth_sha256": file_digest(root / "ground-truth.json"),
        "selection_sha256": file_digest(root / "selection.json"),
        "attribution_sha256": file_digest(root / "attribution.json"),
    }
    write_json(root / "acquisition.json", receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--count", type=int, default=48)
    args = parser.parse_args(argv)
    receipt = prepare(args.data_dir, args.count)
    print(receipt)
    if receipt["count"] != args.count:
        raise SystemExit("requested subset incomplete; see acquisition.json and selection.json")
    verified_acquisition(args.data_dir)


if __name__ == "__main__":
    main()
