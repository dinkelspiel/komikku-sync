# SPDX-FileCopyrightText: 2026 Willem Dinkelspiel <mail@keii.dev>
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
import base64
from datetime import UTC
import zlib


@dataclass(frozen=True, slots=True)
class SyncedChapter:
    slug: str | None
    num: str | None
    read: bool
    last_read: int | None = None
    last_page_read_index: int | None = None


@dataclass(frozen=True, slots=True)
class SyncedManga:
    slug: str
    server_id: str
    chapters: tuple[SyncedChapter, ...]
    name: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class SyncedState:
    CONTENT_TYPE = 'application/vnd.komikku.sync-state'
    MAGIC = b'KSYN\x02'
    LEGACY_MAGIC = b'KSYN\x01'
    MAX_DECODED_SIZE = 128 * 1024 * 1024
    TEXT_PREFIX = 'ksync:'

    mangas: tuple[SyncedManga, ...]

    @classmethod
    def from_mangas(cls, mangas):
        synced_mangas = []
        for manga in mangas:
            chapters = tuple(
                SyncedChapter(
                    slug=None if chapter.slug is None else str(chapter.slug),
                    num=None if chapter.num is None else str(chapter.num),
                    read=bool(chapter.read),
                    last_read=_datetime_to_milliseconds(getattr(chapter, 'last_read', None)),
                    last_page_read_index=getattr(chapter, 'last_page_read_index', None),
                )
                for chapter in manga.chapters
            )
            synced_mangas.append(SyncedManga(
                slug=str(manga.slug),
                server_id=str(manga.server_id),
                chapters=chapters,
                name=None if manga.name is None else str(manga.name),
                url=None if manga.url is None else str(manga.url),
            ))

        return cls(tuple(synced_mangas))

    def encode(self):
        writer = _Writer()
        writer.write_varint(len(self.mangas))
        for manga in self.mangas:
            writer.write_string(manga.slug)
            writer.write_string(manga.server_id)
            writer.write_optional_string(manga.name)
            writer.write_optional_string(manga.url)
            writer.write_varint(len(manga.chapters))
            for chapter in manga.chapters:
                flags = int(chapter.read)
                if chapter.slug is not None:
                    flags |= 2
                if chapter.num is not None:
                    flags |= 4
                if chapter.last_read is not None:
                    flags |= 8
                if chapter.last_page_read_index is not None:
                    flags |= 16
                writer.data.append(flags)
                if chapter.slug is not None:
                    writer.write_string(chapter.slug)
                if chapter.num is not None:
                    writer.write_string(chapter.num)
                if chapter.last_read is not None:
                    writer.write_varint(chapter.last_read)
                if chapter.last_page_read_index is not None:
                    writer.write_varint(chapter.last_page_read_index)

        return self.MAGIC + zlib.compress(writer.data, level=9)

    @classmethod
    def decode(cls, data):
        if not isinstance(data, bytes):
            raise TypeError('Sync state must be bytes')
        if data.startswith(cls.MAGIC):
            version = 2
        elif data.startswith(cls.LEGACY_MAGIC):
            version = 1
        else:
            raise ValueError('Invalid sync state header')

        payload = _decompress(data[len(cls.MAGIC):], cls.MAX_DECODED_SIZE)
        reader = _Reader(payload)
        mangas = []
        for _ in range(reader.read_count('manga')):
            slug = reader.read_string()
            server_id = reader.read_string()
            name = reader.read_optional_string()
            url = reader.read_optional_string()
            chapters = []
            for _ in range(reader.read_count('chapter')):
                flags = reader.read_byte()
                if flags & ~(31 if version == 2 else 7):
                    raise ValueError('Invalid chapter flags')
                chapter_slug = reader.read_string() if flags & 2 else None
                num = reader.read_string() if flags & 4 else None
                last_read = reader.read_varint() if flags & 8 else None
                last_page_read_index = reader.read_varint() if flags & 16 else None
                chapters.append(SyncedChapter(
                    chapter_slug,
                    num,
                    bool(flags & 1),
                    last_read,
                    last_page_read_index,
                ))
            mangas.append(SyncedManga(slug, server_id, tuple(chapters), name, url))

        if not reader.finished:
            raise ValueError('Unexpected data after sync state')
        return cls(tuple(mangas))

    def to_text(self):
        encoded = base64.urlsafe_b64encode(self.encode()).rstrip(b'=')
        return self.TEXT_PREFIX + encoded.decode('ascii')

    @classmethod
    def from_text(cls, text):
        if not isinstance(text, str) or not text.startswith(cls.TEXT_PREFIX):
            raise ValueError('Invalid sync state text')
        encoded = text[len(cls.TEXT_PREFIX):].strip()
        try:
            data = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError('Invalid sync state text') from error
        return cls.decode(data)


class _Writer:
    def __init__(self):
        self.data = bytearray()

    def write_varint(self, value):
        while value >= 128:
            self.data.append((value & 127) | 128)
            value >>= 7
        self.data.append(value)

    def write_string(self, value):
        encoded = value.encode('utf-8')
        self.write_varint(len(encoded))
        self.data.extend(encoded)

    def write_optional_string(self, value):
        if value is None:
            self.write_varint(0)
            return
        encoded = value.encode('utf-8')
        self.write_varint(len(encoded) + 1)
        self.data.extend(encoded)


class _Reader:
    MAX_ITEMS = 10_000_000
    MAX_STRING_SIZE = 16 * 1024 * 1024

    def __init__(self, data):
        self.data = data
        self.offset = 0

    @property
    def finished(self):
        return self.offset == len(self.data)

    def read_byte(self):
        if self.offset >= len(self.data):
            raise ValueError('Truncated sync state')
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_varint(self):
        value = 0
        for shift in range(0, 64, 7):
            byte = self.read_byte()
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('Invalid integer in sync state')

    def read_count(self, name):
        value = self.read_varint()
        if value > self.MAX_ITEMS:
            raise ValueError(f'Too many {name} records')
        return value

    def read_string_bytes(self, size):
        if size > self.MAX_STRING_SIZE or self.offset + size > len(self.data):
            raise ValueError('Invalid string size in sync state')
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        try:
            return value.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('Invalid text in sync state') from error

    def read_string(self):
        return self.read_string_bytes(self.read_varint())

    def read_optional_string(self):
        size = self.read_varint()
        return None if size == 0 else self.read_string_bytes(size - 1)


def _decompress(data, max_size):
    decompressor = zlib.decompressobj()
    try:
        payload = decompressor.decompress(data, max_size + 1)
    except zlib.error as error:
        raise ValueError('Invalid compressed sync state') from error
    if len(payload) > max_size or decompressor.unconsumed_tail:
        raise ValueError('Sync state is too large')
    try:
        payload += decompressor.flush(max_size + 1 - len(payload))
    except zlib.error as error:
        raise ValueError('Invalid compressed sync state') from error
    if len(payload) > max_size:
        raise ValueError('Sync state is too large')
    if not decompressor.eof or decompressor.unused_data:
        raise ValueError('Invalid compressed sync state')
    return payload


def _datetime_to_milliseconds(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, int(value.timestamp() * 1000))
