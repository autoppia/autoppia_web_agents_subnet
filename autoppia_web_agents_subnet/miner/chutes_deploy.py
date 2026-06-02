from __future__ import annotations

import contextlib
import io
import logging
import sys
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from .ui import console, print_banner, print_error, print_success

DEFAULT_IMAGE = "chutes/sglang:nightly-2026031000"
CHUTES_CONFIG = Path.home() / ".chutes" / "config.ini"


class ChutesCliError(Exception):
    """Raised for user-facing chutes CLI errors."""


def _confirm(label: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"{label} {suffix}: ").strip().lower()
    if not raw:
        return default_yes
    return raw.startswith("y")


def _prompt(value: str | None, label: str, *, default: str | None = None, required: bool = False) -> str:
    current = (value or "").strip()
    if current:
        return current
    prompt = label
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    entered = input(prompt).strip()
    if entered:
        return entered
    if default is not None:
        return default
    if required:
        raise ChutesCliError(f"Missing required value: {label}")
    return ""


def _get_username() -> str:
    try:
        for line in CHUTES_CONFIG.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("username"):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""


@contextlib.contextmanager
def _quiet():
    try:
        from loguru import logger as loguru_logger

        loguru_logger.disable("chutes")
        loguru_logger.disable("huggingface_hub")
    except Exception:
        loguru_logger = None

    old_level = logging.root.level
    logging.root.setLevel(logging.CRITICAL)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old_stdout
        logging.root.setLevel(old_level)
        if loguru_logger is not None:
            loguru_logger.enable("chutes")
            loguru_logger.enable("huggingface_hub")


def _resolve_revision(model: str, revision: str) -> str:
    if revision:
        return revision
    try:
        from huggingface_hub import model_info
    except Exception as exc:
        raise ChutesCliError("huggingface_hub is required for automatic revision lookup") from exc
    return model_info(model).sha


def _build_chute(
    username: str,
    model: str,
    revision: str,
    image: str,
    gpu_count: int,
    min_vram: int,
    include_gpus: str,
    exclude_gpus: str,
    concurrency: int,
    engine_args: str,
):
    try:
        from chutes.chute import NodeSelector
        from chutes.chute.template.sglang import build_sglang_chute
    except Exception as exc:
        raise ChutesCliError("Chutes SDK is required. Run: pip install chutes") from exc

    include_list = [g.strip() for g in include_gpus.split(",") if g.strip()] or None
    exclude_list = [g.strip() for g in exclude_gpus.split(",") if g.strip()] or None
    node_selector = NodeSelector(
        gpu_count=gpu_count,
        min_vram_gb_per_gpu=min_vram,
        include=include_list,
        exclude=exclude_list,
    )
    kwargs = dict(
        username=username,
        model_name=model,
        revision=revision,
        image=image,
        node_selector=node_selector,
        concurrency=concurrency,
        readme=f"## {model}\nDeployed via autoppia-miner-cli.",
    )
    if engine_args:
        kwargs["engine_args"] = engine_args
    return build_sglang_chute(**kwargs)


async def _check_image(image_id: str) -> bool:
    try:
        import aiohttp
        from chutes.util.auth import sign_request
    except Exception as exc:
        raise ChutesCliError("Chutes deploy requires aiohttp and chutes SDK") from exc

    headers, _ = sign_request(purpose="images")
    async with aiohttp.ClientSession(base_url="https://api.chutes.ai") as session:
        async with session.get(f"/images/{image_id}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("status") == "built and pushed"
    return False


async def _deploy_chute(chute, accept_fee: bool) -> str | None:
    try:
        import aiohttp
        from chutes._version import version as current_version
        from chutes.chute import ChutePack
        from chutes.util.auth import sign_request
    except Exception as exc:
        raise ChutesCliError("Chutes deploy requires the chutes SDK and aiohttp") from exc

    chute_obj = chute.chute if ChutePack and isinstance(chute, ChutePack) else chute
    image_id = chute_obj.image if isinstance(chute_obj.image, str) else chute_obj.image.uid
    if not await _check_image(image_id):
        raise ChutesCliError(
            f"Image '{image_id}' is not available. List with: chutes images list --include-public --name sglang"
        )

    request_body = {
        "name": chute_obj.name,
        "tagline": chute_obj.tagline,
        "readme": chute_obj.readme,
        "logo_id": None,
        "image": image_id,
        "public": False,
        "standard_template": chute_obj.standard_template,
        "node_selector": chute_obj.node_selector.model_dump(),
        "filename": "chutes_deploy.py",
        "ref_str": "chutes_deploy:chute",
        "code": "",
        "concurrency": chute_obj.concurrency,
        "max_instances": chute_obj.max_instances,
        "scaling_threshold": chute_obj.scaling_threshold,
        "shutdown_after_seconds": chute_obj.shutdown_after_seconds,
        "allow_external_egress": chute_obj.allow_external_egress,
        "encrypted_fs": chute_obj.encrypted_fs,
        "tee": chute_obj.tee,
        "lock_modules": chute_obj.lock_modules,
        "revision": chute_obj.revision,
        "cords": [
            {
                "method": cord._method,
                "path": cord.path,
                "public_api_path": cord.public_api_path,
                "public_api_method": cord._public_api_method,
                "stream": cord._stream,
                "function": cord._func.__name__,
                "input_schema": cord.input_schema,
                "output_schema": cord.output_schema,
                "output_content_type": cord.output_content_type,
                "minimal_input_schema": cord.minimal_input_schema,
                "passthrough": cord._passthrough,
            }
            for cord in chute_obj._cords
        ],
        "jobs": [
            {
                "ports": [{"name": port.name, "port": port.port, "proto": port.proto} for port in job.ports],
                "timeout": job.timeout,
                "name": job._name,
                "upload": job.upload,
            }
            for job in chute_obj._jobs
        ],
    }

    headers, request_string = sign_request(request_body)
    headers["X-Chutes-Version"] = current_version
    async with aiohttp.ClientSession(base_url="https://api.chutes.ai") as session:
        async with session.post(
            "/chutes/",
            data=request_string,
            headers=headers,
            params={"accept_fee": str(accept_fee).lower()},
            timeout=aiohttp.ClientTimeout(total=None),
        ) as resp:
            data = await resp.json()
            if resp.status == 200:
                return data["chute_id"]
            if resp.status == 402:
                raise ChutesCliError(f"Deployment fee required: {data['detail']}\nRe-run with --accept-fee to accept.")
            raise ChutesCliError(f"Deploy failed: {data.get('detail', data)}")


async def run_deploy(
    *,
    username: str | None,
    model: str | None,
    revision: str | None,
    image: str | None,
    gpu_count: str | None,
    min_vram: str | None,
    include_gpus: str | None,
    exclude_gpus: str | None,
    concurrency: str | None,
    engine_args: str | None,
    accept_fee: bool | None,
    dry_run: bool,
) -> None:
    print_banner()
    console.print("[bold cyan]-- Chutes Deploy --[/bold cyan]\n")

    if not CHUTES_CONFIG.exists():
        raise ChutesCliError("Chutes not configured. Run: chutes login")

    args_username = _prompt(username, "Chutes username", default=_get_username() or None, required=True)
    args_model = _prompt(model, "HuggingFace model (e.g. unsloth/Llama-3.2-1B-Instruct)", required=True)
    revision_input = _prompt(revision, "Revision (40-char hash)", default="auto")
    revision_value = revision_input if revision_input != "auto" else ""
    args_image = _prompt(image, "Chutes image", default=DEFAULT_IMAGE)
    args_gpu_count = int(_prompt(gpu_count, "Number of GPUs", default="1"))
    args_min_vram = int(_prompt(min_vram, "Minimum VRAM per GPU in GB", default="24"))
    args_include_gpus = _prompt(include_gpus, "Include GPUs (comma-separated)", default="")
    args_exclude_gpus = _prompt(exclude_gpus, "Exclude GPUs (comma-separated)", default="")
    args_concurrency = int(_prompt(concurrency, "Max concurrent requests", default="32"))
    args_engine_args = _prompt(engine_args, "Engine args", default="")
    if accept_fee is None:
        accept_fee = _confirm("Accept deployment fee automatically?", default_yes=True)

    summary = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
    summary.add_column("Field", style="bold")
    summary.add_column("Value")
    summary.add_row("Username", args_username)
    summary.add_row("Model", args_model)
    summary.add_row("Revision", revision_value or "auto-resolve")
    summary.add_row("Image", args_image)
    summary.add_row("GPUs", f"{args_gpu_count} x {args_min_vram} GB VRAM")
    if args_include_gpus:
        summary.add_row("Include GPUs", args_include_gpus)
    if args_exclude_gpus:
        summary.add_row("Exclude GPUs", args_exclude_gpus)
    summary.add_row("Concurrency", str(args_concurrency))
    if args_engine_args:
        summary.add_row("Engine Args", args_engine_args)
    summary.add_row("Accept Fee", str(bool(accept_fee)))
    console.print(Panel(summary, title="Deployment Summary", border_style="blue"))

    if not dry_run and not _confirm("Deploy now?", default_yes=True):
        print_error("Cancelled.")
        return

    with _quiet():
        resolved_revision = _resolve_revision(args_model, revision_value)
        chute = _build_chute(
            args_username,
            args_model,
            resolved_revision,
            args_image,
            args_gpu_count,
            args_min_vram,
            args_include_gpus,
            args_exclude_gpus,
            args_concurrency,
            args_engine_args,
        )

    if dry_run:
        print_success(f"Dry run OK. Resolved revision: {resolved_revision}")
        return

    chute_id = await _deploy_chute(chute, bool(accept_fee))
    if not chute_id:
        raise ChutesCliError("Deploy failed")
    print_success(f"Deployed chute successfully. chute_id={chute_id}")
