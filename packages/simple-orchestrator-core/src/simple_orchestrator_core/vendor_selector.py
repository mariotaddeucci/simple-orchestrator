from __future__ import annotations

from dataclasses import dataclass

_VENDOR_ALIASES: dict[str, str] = {
    "claude-code": "claude_code",
    "claude_code": "claude_code",
    "opencode": "opencode",
    "github-copilot": "github_copilot",
    "github_copilot": "github_copilot",
    "jules": "jules",
}

_VENDOR_DISPLAY: dict[str, str] = {
    "claude_code": "claude-code",
    "opencode": "opencode",
    "github_copilot": "github-copilot",
    "jules": "jules",
}


@dataclass(frozen=True)
class VendorModelSelection:
    vendor: str
    model: str | None = None

    def display(self) -> str:
        vendor = _VENDOR_DISPLAY.get(self.vendor, self.vendor)
        if self.model:
            return f"{vendor}/{self.model}"
        return vendor


def normalize_vendor_id(vendor: str) -> str:
    normalized = _VENDOR_ALIASES.get(vendor.strip())
    return normalized or vendor.strip()


def parse_vendor_model_selection(raw: str) -> VendorModelSelection:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty selection")

    if "/" in raw:
        vendor_raw, model_raw = raw.split("/", 1)
        vendor = normalize_vendor_id(vendor_raw)
        model = model_raw.strip() or None
        if not vendor:
            raise ValueError(f"invalid vendor in {raw!r}")
        return VendorModelSelection(vendor=vendor, model=model)

    vendor = normalize_vendor_id(raw)
    if not vendor:
        raise ValueError(f"invalid vendor in {raw!r}")
    return VendorModelSelection(vendor=vendor, model=None)


def format_vendor_model_selection(vendor: str, model: str | None) -> str:
    return VendorModelSelection(vendor=normalize_vendor_id(vendor), model=model).display()
