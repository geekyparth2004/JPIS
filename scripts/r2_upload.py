import argparse
import datetime as dt
import hashlib
import hmac
import mimetypes
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


SERVICE = "s3"
REGION = "auto"
ALGORITHM = "AWS4-HMAC-SHA256"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region_name.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service_name.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
            continue
        if path.is_dir():
            for file_path in sorted(path.rglob("*")):
                if file_path.is_file():
                    yield file_path


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"


def build_key(file_path: Path, source_root: Path, prefix: str) -> str:
    relative = file_path.relative_to(source_root).as_posix()
    prefix = prefix.strip("/")
    if prefix:
        return f"{prefix}/{relative}"
    return relative


def put_object(endpoint: str, bucket: str, key: str, access_key: str, secret_key: str, content_type: str, payload: bytes) -> None:
    parsed = urlparse(endpoint)
    host = parsed.netloc
    canonical_uri = f"/{bucket}/{quote(key, safe='/')}"
    now = dt.datetime.now(dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [
            "PUT",
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = get_signature_key(secret_key, date_stamp, REGION, SERVICE)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{ALGORITHM} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    request = Request(
        f"{parsed.scheme}://{host}{canonical_uri}",
        data=payload,
        method="PUT",
        headers={
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        },
    )
    with urlopen(request) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Upload failed for {key}: HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload files or directories to Cloudflare R2.")
    parser.add_argument("paths", nargs="+", help="Files or directories to upload.")
    parser.add_argument("--bucket", default=env("R2_BUCKET_NAME"), help="R2 bucket name.")
    parser.add_argument("--endpoint", default=env("R2_ENDPOINT_URL"), help="R2 endpoint URL.")
    parser.add_argument("--prefix", default="", help="Optional object key prefix.")
    parser.add_argument("--public-base-url", default=env("R2_PUBLIC_BASE_URL"), help="Optional public base URL for printing.")
    args = parser.parse_args()

    access_key = env("R2_ACCESS_KEY_ID")
    secret_key = env("R2_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise SystemExit("Missing R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY environment variables.")
    if not args.bucket or not args.endpoint:
        raise SystemExit("Missing --bucket/--endpoint or R2_BUCKET_NAME/R2_ENDPOINT_URL environment variables.")

    path_objects = [Path(raw).resolve() for raw in args.paths]
    upload_roots = []
    for path_obj in path_objects:
        if not path_obj.exists():
            raise SystemExit(f"Path not found: {path_obj}")
        source_root = path_obj.parent if path_obj.is_file() else path_obj.parent
        upload_roots.append((path_obj, source_root))

    total = 0
    for original_path, source_root in upload_roots:
        files = list(iter_files([original_path]))
        for file_path in files:
            key = build_key(file_path, source_root, args.prefix)
            content_type = guess_content_type(file_path)
            payload = file_path.read_bytes()
            put_object(args.endpoint, args.bucket, key, access_key, secret_key, content_type, payload)
            total += 1
            public_url = ""
            if args.public_base_url:
                public_url = f" -> {args.public_base_url.rstrip('/')}/{quote(key, safe='/')}"
            print(f"Uploaded {file_path} as {key}{public_url}")

    print(f"Uploaded {total} file(s) to bucket '{args.bucket}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
