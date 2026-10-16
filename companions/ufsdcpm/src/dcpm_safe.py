"""Bounded readers for legacy DCPM formats. No executable pickle globals."""
import ast
import io
import pickle
import pickletools
import re
import zlib
from collections import namedtuple
from pathlib import PurePosixPath

MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 65536
FileChecksum = namedtuple('FileChecksum', 'md5 sha1 sha256 crc32')


def bounded_value(value):
    pending = [(value, 0)]; count = 0
    while pending:
        item, depth = pending.pop(); count += 1
        if count > MAX_ITEMS or depth > 32:
            raise ValueError('DCPM_STRUCTURE_LIMIT')
        if type(item) in (str, bytes):
            if len(item) > MAX_BYTES: raise ValueError('DCPM_VALUE_LIMIT')
        elif type(item) in (int, float, bool, type(None)):
            if type(item) is int and item.bit_length() > 4096: raise ValueError('DCPM_INTEGER_LIMIT')
        elif type(item) in (list, tuple, dict, FileChecksum):
            children = list(item.items()) if type(item) is dict else item
            pending.extend((child, depth + 1) for child in children)
        else:
            raise ValueError('DCPM_UNSUPPORTED_VALUE')
    return value


class _Reader(pickle.Unpickler):
    def find_class(self, module, name):
        if module in {'dcpm_core', 'dcpm_safe'} and name == 'FileChecksum':
            return FileChecksum
        raise ValueError('DCPM_EXECUTABLE_PICKLE_REJECTED')

    def persistent_load(self, pid):
        raise ValueError('DCPM_PERSISTENT_PICKLE_REJECTED')


def safe_pickle(data):
    if type(data) is not bytes or len(data) > MAX_BYTES: raise ValueError('DCPM_SERIALIZED_LIMIT')
    if sum(1 for _ in pickletools.genops(data)) > MAX_ITEMS: raise ValueError('DCPM_OPCODE_LIMIT')
    stream = io.BytesIO(data); result = _Reader(stream).load()
    if stream.read(): raise ValueError('DCPM_TRAILING_DATA')
    return bounded_value(result)


def decompress_pickle(data):
    if type(data) is not bytes or len(data) > MAX_BYTES: raise ValueError('DCPM_COMPRESSED_LIMIT')
    decoder = zlib.decompressobj(); plain = decoder.decompress(data, MAX_BYTES + 1)
    if len(plain) > MAX_BYTES or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise ValueError('DCPM_DECOMPRESSION_LIMIT_OR_INVALID_STREAM')
    return safe_pickle(plain)


def parse_metadata(data):
    if not isinstance(data, str) or len(data.encode()) > 1024 * 1024: raise ValueError('DCPM_METADATA_LIMIT')
    tree = ast.parse(data, mode='eval')
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_ITEMS: raise ValueError('DCPM_METADATA_STRUCTURE_LIMIT')
    # Legacy repr uses a namedtuple call. Accept precisely its four string fields,
    # convert to an inert tuple AST, and let literal_eval reject every other call.
    class LegacyChecksum(ast.NodeTransformer):
        def visit_Call(self, node):
            if not isinstance(node.func, ast.Name) or node.func.id != 'FileChecksum' or node.args or [k.arg for k in node.keywords] != ['md5','sha1','sha256','crc32']:
                raise ValueError('DCPM_METADATA_CALL_REJECTED')
            values = [k.value for k in node.keywords]
            if any(not isinstance(v, ast.Constant) or not isinstance(v.value, str) for v in values):
                raise ValueError('DCPM_METADATA_CHECKSUM_REJECTED')
            return ast.copy_location(ast.Tuple(elts=values, ctx=ast.Load()), node)
    result = ast.literal_eval(LegacyChecksum().visit(tree))
    if type(result) is not dict: raise ValueError('DCPM_METADATA_OBJECT_REQUIRED')
    return bounded_value(result)


def package_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise ValueError('DCPM_UNSAFE_PATH')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {'', '.', '..'} for p in value.split('/')) or len(value) > 1024:
        raise ValueError('DCPM_UNSAFE_PATH')
    return path


def package_label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:-]{0,127}', value):
        raise ValueError('DCPM_UNSAFE_PACKAGE_NAME')
    return value


async def read_blocks(provider, hashes, cache):
    """Fetch and validate blocks in manifest order; cache bytes, never progress lengths."""
    import asyncio
    import hashlib
    if type(hashes) is not list or len(hashes) > 128 or any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes):
        raise ValueError('DCPM_BLOCK_MANIFEST_LIMIT')
    parts = []; total = 0
    for digest in hashes:
        data = cache.get(digest)
        if type(data) is not bytes:
            data = await asyncio.wait_for(provider.get_block(digest), 10)
        if type(data) is not bytes:
            raise LookupError('DCPM_BLOCK_UNAVAILABLE')
        if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
            cache.pop(digest, None)
            raise ValueError('DCPM_BLOCK_INTEGRITY')
        total += len(data)
        if total > MAX_BYTES: raise ValueError('DCPM_CONTENT_LIMIT')
        cache[digest] = data; parts.append(data)
    return b''.join(parts)
