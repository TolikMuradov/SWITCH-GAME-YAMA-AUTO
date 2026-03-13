"""
Pure-Python MSBT (Message Studio Binary Text) reader and writer.

Supports:
  • LBL1 (label table with hash buckets)
  • ATR1 (attribute section, preserved verbatim)
  • TXT2 (UTF-16 text with embedded control codes)

Control codes inside text strings are preserved as raw bytes so they
survive the export → translate → import round-trip unchanged.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MSBT_MAGIC = b"MsgStdBn"
SECTION_ALIGN = 16
BOM_LE = 0xFEFF
BOM_BE = 0xFFFE


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MsbtEntry:
    index: int
    label: str
    text_bytes: bytes          # raw UTF-16 bytes (LE or BE), no BOM, no null terminator
    attributes: bytes = b""    # ATR1 per-entry bytes (if any)

    @property
    def text(self) -> str:
        """Decode raw text bytes, ignoring embedded control codes."""
        try:
            return self.text_bytes.decode("utf-16-le")
        except UnicodeDecodeError:
            return self.text_bytes.decode("utf-16-le", errors="replace")

    @text.setter
    def text(self, value: str) -> None:
        self.text_bytes = value.encode("utf-16-le")


@dataclass
class MsbtFile:
    encoding: int = 1          # 0=UTF-8, 1=UTF-16, 2=UTF-32
    version: int = 3
    endian: str = "<"          # "<" little, ">" big
    entries: List[MsbtEntry] = field(default_factory=list)
    _atr1_data: bytes = field(default=b"", repr=False)
    _raw_sections: Dict[bytes, bytes] = field(default_factory=dict, repr=False)

    def get_entry(self, label: str) -> Optional[MsbtEntry]:
        for e in self.entries:
            if e.label == label:
                return e
        return None

    def to_dict(self) -> Dict[str, str]:
        return {e.label: e.text for e in self.entries}

    def apply_dict(self, translations: Dict[str, str]) -> None:
        for e in self.entries:
            if e.label in translations:
                e.text = translations[e.label]


# ---------------------------------------------------------------------------
# Label hash
# ---------------------------------------------------------------------------

def _label_hash(label: str, bucket_count: int) -> int:
    h = 0
    for c in label:
        h = h * 0x492 + ord(c)
    return (h & 0xFFFFFFFF) % bucket_count


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

def _unpack(fmt: str, data: bytes, offset: int) -> tuple:
    size = struct.calcsize(fmt)
    return struct.unpack_from(fmt, data, offset), offset + size


def read_msbt(path: Path) -> MsbtFile:
    """Parse an MSBT file and return an MsbtFile instance."""
    data = path.read_bytes()
    return parse_msbt(data)


def parse_msbt(data: bytes) -> MsbtFile:
    if data[:8] != MSBT_MAGIC:
        raise ValueError(f"Not an MSBT file (magic mismatch)")

    bom = struct.unpack_from("<H", data, 8)[0]
    endian = "<" if bom == BOM_LE else ">"

    E = endian
    encoding = data[0x0B]
    version = data[0x0C]
    num_sections = struct.unpack_from(f"{E}H", data, 0x0E)[0]
    # file_size = struct.unpack_from(f"{E}I", data, 0x12)[0]

    msbt = MsbtFile(encoding=encoding, version=version, endian=endian)

    # Parse sections
    off = 0x20
    lbl1_data: Optional[bytes] = None
    atr1_data: Optional[bytes] = None
    txt2_data: Optional[bytes] = None

    for _ in range(num_sections):
        if off + 8 > len(data):
            break
        section_magic = data[off:off + 4]
        section_size = struct.unpack_from(f"{E}I", data, off + 4)[0]
        # Skip 8-byte padding in section header
        section_data_start = off + 16
        section_data = data[section_data_start:section_data_start + section_size]

        msbt._raw_sections[section_magic] = section_data

        if section_magic == b"LBL1":
            lbl1_data = section_data
        elif section_magic == b"ATR1":
            atr1_data = section_data
            msbt._atr1_data = section_data
        elif section_magic == b"TXT2":
            txt2_data = section_data

        # Advance: section header (16) + data + alignment padding
        total = 16 + section_size
        remainder = total % SECTION_ALIGN
        if remainder:
            total += SECTION_ALIGN - remainder
        off += total

    # Build entries from TXT2
    entries_by_index: Dict[int, MsbtEntry] = {}
    if txt2_data:
        string_count = struct.unpack_from(f"{E}I", txt2_data, 0)[0]
        offsets = [
            struct.unpack_from(f"{E}I", txt2_data, 4 + i * 4)[0]
            for i in range(string_count)
        ]
        for idx, str_off in enumerate(offsets):
            # Find null terminator (2-byte null for UTF-16)
            abs_off = str_off
            end = abs_off
            while end + 1 < len(txt2_data):
                if txt2_data[end] == 0 and txt2_data[end + 1] == 0:
                    break
                end += 2
            text_bytes = txt2_data[abs_off:end]
            entries_by_index[idx] = MsbtEntry(index=idx, label=str(idx), text_bytes=text_bytes)

    # Apply labels from LBL1
    if lbl1_data:
        bucket_count = struct.unpack_from(f"{E}I", lbl1_data, 0)[0]
        for b in range(bucket_count):
            bucket_off = 4 + b * 8
            label_count = struct.unpack_from(f"{E}I", lbl1_data, bucket_off)[0]
            labels_offset = struct.unpack_from(f"{E}I", lbl1_data, bucket_off + 4)[0]
            cur = labels_offset
            for _ in range(label_count):
                if cur >= len(lbl1_data):
                    break
                name_len = lbl1_data[cur]
                cur += 1
                if cur + name_len + 4 > len(lbl1_data):
                    break  # malformed: not enough data for name + index
                label_name = lbl1_data[cur:cur + name_len].decode("utf-8", errors="replace")
                cur += name_len
                item_index = struct.unpack_from(f"{E}I", lbl1_data, cur)[0]
                cur += 4
                if item_index in entries_by_index:
                    entries_by_index[item_index].label = label_name

    # Sort entries by index
    msbt.entries = [entries_by_index[i] for i in sorted(entries_by_index)]
    return msbt


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_msbt(msbt: MsbtFile, path: Path) -> None:
    """Serialize *msbt* back to binary and write to *path*."""
    data = build_msbt(msbt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_msbt(msbt: MsbtFile) -> bytes:
    E = msbt.endian
    bom = BOM_LE if E == "<" else BOM_BE

    sections_data = b""
    section_magic_list = []

    # Build LBL1
    lbl1 = _build_lbl1(msbt)
    sections_data += _wrap_section(b"LBL1", lbl1, E)
    section_magic_list.append(b"LBL1")

    # ATR1: preserve original or write minimal
    if msbt._atr1_data:
        sections_data += _wrap_section(b"ATR1", msbt._atr1_data, E)
    else:
        # Minimal ATR1: entry_count=0, entry_size=0
        minimal = struct.pack(f"{E}II", len(msbt.entries), 0)
        sections_data += _wrap_section(b"ATR1", minimal, E)
    section_magic_list.append(b"ATR1")

    # Build TXT2
    txt2 = _build_txt2(msbt)
    sections_data += _wrap_section(b"TXT2", txt2, E)
    section_magic_list.append(b"TXT2")

    num_sections = len(section_magic_list)
    file_size = 0x20 + len(sections_data)

    header = (
        MSBT_MAGIC
        + struct.pack(f"{E}H", bom)
        + bytes([0x00, msbt.encoding, msbt.version])
        + struct.pack(f"{E}H", num_sections)
        + struct.pack(f"{E}H", 0x0000)
        + struct.pack(f"{E}I", file_size)
        + b"\x00" * 10  # padding to 0x20
    )
    return header + sections_data


def _wrap_section(magic: bytes, data: bytes, endian: str) -> bytes:
    """Wrap section data with a 16-byte section header and alignment padding."""
    header = magic + struct.pack(f"{endian}I", len(data)) + b"\x00" * 8
    raw = header + data
    remainder = len(raw) % SECTION_ALIGN
    if remainder:
        raw += b"\xAB" * (SECTION_ALIGN - remainder)
    return raw


def _build_lbl1(msbt: MsbtFile) -> bytes:
    E = msbt.endian
    BUCKET_COUNT = 101  # prime number commonly used by Nintendo

    # Assign entries to buckets
    buckets: List[List[MsbtEntry]] = [[] for _ in range(BUCKET_COUNT)]
    for entry in msbt.entries:
        bucket_idx = _label_hash(entry.label, BUCKET_COUNT)
        buckets[bucket_idx].append(entry)

    # Build string data region and bucket headers
    bucket_headers = b""
    string_data = b""
    # offset starts after bucket table (BUCKET_COUNT * 8 bytes + 4 for count)
    base_offset = 4 + BUCKET_COUNT * 8

    for bucket in buckets:
        offset = base_offset + len(string_data)
        bucket_headers += struct.pack(f"{E}II", len(bucket), offset)
        for entry in bucket:
            name_bytes = entry.label.encode("utf-8")
            string_data += bytes([len(name_bytes)]) + name_bytes + struct.pack(f"{E}I", entry.index)

    count_header = struct.pack(f"{E}I", BUCKET_COUNT)
    return count_header + bucket_headers + string_data


def _build_txt2(msbt: MsbtFile) -> bytes:
    E = msbt.endian
    count = len(msbt.entries)
    null_term = b"\x00\x00"

    # Offsets are from start of TXT2 data (not including section header)
    # First 4 bytes = count, then count * 4 bytes for offsets
    data_start = 4 + count * 4
    offsets = []
    strings = b""
    for entry in sorted(msbt.entries, key=lambda e: e.index):
        offsets.append(data_start + len(strings))
        strings += entry.text_bytes + null_term

    header = struct.pack(f"{E}I", count)
    for o in offsets:
        header += struct.pack(f"{E}I", o)
    return header + strings
