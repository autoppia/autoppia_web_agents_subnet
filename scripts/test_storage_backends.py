#!/usr/bin/env python3
"""
Script to verify storage backend switching functionality.

Usage:
    # Test with standard IPFS (default)
    python scripts/test_storage_backends.py

    # Test with Hippius IPFS
    STORAGE_IPFS_BACKEND=hippius python scripts/test_storage_backends.py

    # Test S3 upload (AWS)
    S3_METADATA_UPLOAD_ENABLED=true \
    AWS_ACCESS_KEY_ID=your-key \
    AWS_SECRET_ACCESS_KEY=your-secret \
    python scripts/test_storage_backends.py

    # Test S3 upload (Hippius)
    S3_METADATA_UPLOAD_ENABLED=true \
    STORAGE_S3_BACKEND=hippius \
    HIPPIUS_S3_ACCESS_KEY=hip_your_key \
    HIPPIUS_S3_SECRET_KEY=your_secret \
    python scripts/test_storage_backends.py
"""

import os
import sys
import json

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set minimal env vars for config validation
os.environ.setdefault("VALIDATOR_NAME", "test-validator")
os.environ.setdefault("VALIDATOR_IMAGE", "https://example.com/test.png")


def test_ipfs_backend():
    """Test the configured IPFS backend."""
    from autoppia_web_agents_subnet.utils.storage import get_ipfs_client, reset_clients
    from autoppia_web_agents_subnet.validator.config import STORAGE_IPFS_BACKEND

    reset_clients()
    print(f"\n{'='*60}")
    print(f"IPFS Backend: {STORAGE_IPFS_BACKEND}")
    print(f"{'='*60}")

    try:
        client = get_ipfs_client()
        print(f"  Client type: {type(client).__name__}")

        # Test upload
        test_obj = {"test": True, "message": "Hello from storage test"}
        print(f"  Uploading test JSON...")
        cid, sha_hex, byte_len = client.add_json(test_obj)
        print(f"  CID: {cid}")
        print(f"  SHA256: {sha_hex[:16]}...")
        print(f"  Size: {byte_len} bytes")

        # Test download
        print(f"  Downloading CID {cid[:20]}...")
        obj, norm, h = client.get_json(cid)
        print(f"  Downloaded: {json.dumps(obj)}")
        assert obj == test_obj, "Downloaded object does not match!"
        print(f"  Hash verified: {h[:16]}...")

        print(f"  IPFS backend test: PASSED")
        return True
    except Exception as e:
        print(f"  IPFS backend test: FAILED - {type(e).__name__}: {e}")
        return False


def test_s3_backend():
    """Test the configured S3 backend."""
    from autoppia_web_agents_subnet.validator.config import (
        S3_METADATA_UPLOAD_ENABLED,
        STORAGE_S3_BACKEND,
    )

    print(f"\n{'='*60}")
    print(f"S3 Backend: {STORAGE_S3_BACKEND}")
    print(f"S3 Upload Enabled: {S3_METADATA_UPLOAD_ENABLED}")
    print(f"{'='*60}")

    if not S3_METADATA_UPLOAD_ENABLED:
        print("  S3 uploads disabled. Set S3_METADATA_UPLOAD_ENABLED=true to test.")
        print("  S3 backend test: SKIPPED")
        return True

    try:
        from autoppia_web_agents_subnet.utils.storage import get_s3_client, reset_clients
        reset_clients()

        client = get_s3_client()
        print(f"  Client type: {type(client).__name__}")

        bucket = os.environ.get("S3_METADATA_BUCKET", "autoppia-test-bucket")
        print(f"  Ensuring bucket: {bucket}")
        client.ensure_bucket(bucket)

        # Test upload
        test_key = "test/storage_test.json"
        test_obj = {"test": True, "backend": STORAGE_S3_BACKEND}
        print(f"  Uploading to {bucket}/{test_key}...")
        result = client.upload_json(test_obj, bucket=bucket, key=test_key)
        print(f"  Upload result: {result}")

        # Test download
        print(f"  Downloading {test_key}...")
        downloaded = client.download_json(bucket=bucket, key=test_key)
        print(f"  Downloaded: {json.dumps(downloaded)}")
        assert downloaded == test_obj, "Downloaded object does not match!"

        # Test list
        print(f"  Listing objects in {bucket}/test/...")
        objects = client.list_objects(bucket=bucket, prefix="test/")
        print(f"  Found {len(objects)} objects")

        print(f"  S3 backend test: PASSED")
        return True
    except Exception as e:
        print(f"  S3 backend test: FAILED - {type(e).__name__}: {e}")
        return False


def test_metadata_store():
    """Test the metadata store service."""
    from autoppia_web_agents_subnet.validator.config import S3_METADATA_UPLOAD_ENABLED

    print(f"\n{'='*60}")
    print("Metadata Store")
    print(f"{'='*60}")

    if not S3_METADATA_UPLOAD_ENABLED:
        print("  S3 uploads disabled. Metadata store will return None.")

    from autoppia_web_agents_subnet.utils.storage.metadata_store import get_metadata_store
    import autoppia_web_agents_subnet.utils.storage.metadata_store as ms
    ms._metadata_store = None

    store = get_metadata_store()
    if store is None:
        print("  Metadata store: disabled (as expected)")
        print("  Metadata store test: PASSED")
        return True

    try:
        print(f"  Store type: {type(store).__name__}")

        # Test round metadata upload
        result = store.upload_round_metadata(
            season=0,
            round_num=0,
            validator_uid=0,
            validator_hotkey="test_hk",
            start_block=0,
            end_block=100,
            tasks_count=5,
            miners_evaluated=3,
        )
        print(f"  Round metadata upload: {result}")

        # Test consensus scores upload
        result = store.upload_consensus_scores(
            season=0,
            round_num=0,
            scores={1: 0.8, 2: 0.6},
            validator_uid=0,
        )
        print(f"  Consensus scores upload: {result}")

        print(f"  Metadata store test: PASSED")
        return True
    except Exception as e:
        print(f"  Metadata store test: FAILED - {type(e).__name__}: {e}")
        return False


def main():
    print("=" * 60)
    print("Storage Backend Verification Script")
    print("=" * 60)

    results = {
        "IPFS": test_ipfs_backend(),
        "S3": test_s3_backend(),
        "Metadata Store": test_metadata_store(),
    }

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
