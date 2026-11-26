"""Build one deterministic JSON artifact; bindings and state remain external."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import (
    LabError, RUNTIMES, canonical, component, fields, fingerprint, identifier,
    parse_json, policy, portable, read_json, require, sha256, text,
)


def safe_path(name: Any) -> str:
    text(name, "asset path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name and
            all(part not in ("", ".", "..") for part in name.split("/")) and
            re.fullmatch(r"[A-Za-z0-9_./-]+", name) is not None,
            "Unsafe asset path")
    require(all(part.split(".")[0].upper() not in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    } and not part.endswith(".") for part in path.parts), "Unsafe Windows asset path")
    return name


def validate_manifest(manifest: Any, assets: dict[str, str]) -> None:
    fields(manifest, {
        "schema_version", "agent", "runtime", "version", "source_revision",
        "infrastructure_revision", "model", "definition", "components", "evaluation",
    }, {"hosted_image"})
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "Unsupported release schema")
    identifier(manifest["agent"], "agent")
    require(manifest["runtime"] in RUNTIMES, "Unsupported runtime")
    text(manifest["version"], "release version")
    require(isinstance(manifest["source_revision"], str) and
            re.fullmatch(r"[0-9a-f]{40}", manifest["source_revision"]) is not None,
            "Full source commit required")
    text(manifest["infrastructure_revision"], "infrastructure revision")
    fields(manifest["model"], {"name", "version"})
    for key in ("name", "version"):
        text(manifest["model"][key], "model " + key)
    fields(manifest["evaluation"], {"dataset", "policy", "baseline"})
    require(isinstance(manifest["components"], list), "Components must be a list")
    paths = [manifest["definition"], *manifest["components"], *manifest["evaluation"].values()]
    for name in paths:
        require(safe_path(name) in assets, "Missing referenced release asset")
    require(len(paths) == len(set(paths)), "Duplicate release asset reference")
    require(set(paths) == assets.keys(), "Unreferenced release asset")
    require(len({path.casefold() for path in paths}) == len(paths), "Case-colliding asset paths")
    definitions = [parse_json(assets[name]) for name in manifest["components"]]
    for definition in definitions:
        component(definition)
    names = [definition["name"] for definition in definitions]
    require(len(names) == len(set(names)), "Duplicate component name")
    kinds = {definition["kind"] for definition in definitions}
    require({"toolbox", "knowledge"} <= kinds, "Toolbox and knowledge contracts required")
    agent = parse_json(assets[manifest["definition"]])
    fields(agent, {"instructions", "tool", "knowledge", "memory", "harness"})
    text(agent["instructions"], "instructions")
    for key, kind in (("tool", "toolbox"), ("knowledge", "knowledge")):
        require(any(item["name"] == agent[key] and item["kind"] == kind for item in definitions),
                "Agent dependency does not match component contract")
    if manifest["runtime"] == "harness":
        require(agent["harness"] == "microsoft_copilot_preview", "Harness discriminator required")
        require(agent["memory"] is None and "memory-policy" not in kinds,
                "Harness memory is unsupported; no substitute is permitted")
    else:
        require(agent["harness"] is None, "Harness selection does not match runtime")
        require(any(item["name"] == agent["memory"] and item["kind"] == "memory-policy"
                    for item in definitions), "Memory policy contract required")
    if manifest["runtime"] == "hosted":
        require(isinstance(manifest.get("hosted_image"), str) and
                re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", manifest["hosted_image"]) is not None,
                "Hosted artifact must pin an OCI image digest")
    else:
        require("hosted_image" not in manifest, "Image only applies to hosted runtime")
    policy(parse_json(assets[manifest["evaluation"]["policy"]]))
    dataset = parse_json(assets[manifest["evaluation"]["dataset"]])
    baseline = parse_json(assets[manifest["evaluation"]["baseline"]])
    require(isinstance(dataset, list) and bool(dataset), "Nonempty evaluation dataset required")
    require(isinstance(baseline, dict) and baseline.get("evidence_type") == "simulated",
            "Explicit simulated baseline required")
    portable(manifest)
    for name, content in assets.items():
        safe_path(name)
        portable(parse_json(content))


def build(source: Path, output: Path) -> tuple[Path, str]:
    manifest = read_json(source / "release.json")
    fields(manifest, {
        "schema_version", "agent", "runtime", "version", "source_revision",
        "infrastructure_revision", "model", "definition", "components", "evaluation",
    }, {"hosted_image"})
    require(isinstance(manifest["components"], list), "Components must be a list")
    fields(manifest["evaluation"], {"dataset", "policy", "baseline"})
    paths = [manifest["definition"], *manifest["components"], *manifest["evaluation"].values()]
    assets: dict[str, str] = {}
    for name in paths:
        relative = PurePosixPath(safe_path(name))
        target = source.joinpath(*relative.parts)
        require(target.resolve().is_relative_to(source.resolve()), "Asset escapes source directory")
        require(not any(parent.is_symlink() for parent in (target, *target.parents)
                        if parent != source.parent), "Symlink assets are not supported")
        assets[name] = canonical(read_json(target)).decode("utf-8")
    validate_manifest(manifest, assets)
    data = canonical({"manifest": manifest, "files": assets})
    digest = sha256(data)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{digest}.json"
    try:
        with destination.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        require(destination.read_bytes() == data, "Existing artifact has different bytes")
    return destination, digest


def load(path: Path, expected_digest: str) -> dict[str, Any]:
    data = path.read_bytes()
    require(sha256(data) == expected_digest, "Bundle digest mismatch")
    bundle = parse_json(data)
    fields(bundle, {"manifest", "files"})
    require(isinstance(bundle["files"], dict) and
            all(isinstance(value, str) for value in bundle["files"].values()), "Invalid bundle assets")
    validate_manifest(bundle["manifest"], bundle["files"])
    require(data == canonical(bundle), "Noncanonical bundle bytes")
    return bundle


def references(bundle: dict[str, Any]) -> dict[str, Any]:
    manifest, assets = bundle["manifest"], bundle["files"]
    contracts = {}
    for path in manifest["components"]:
        value = parse_json(assets[path])
        contracts[value["name"]] = {
            "kind": value["kind"], "digest": sha256(assets[path].encode("utf-8")),
            "version": value["version"],
        }
    return {
        "components": contracts,
        "evaluation": {key + "_digest": fingerprint(parse_json(assets[path]))
                       for key, path in manifest["evaluation"].items()},
        "policy": parse_json(assets[manifest["evaluation"]["policy"]]),
    }
