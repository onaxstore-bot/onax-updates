"""Per-user Windows DPAPI protection for local monitoring credentials."""
import json
import os
from pathlib import Path


class VaultError(ValueError):
    pass


def _dpapi(payload, *, decrypt=False):
    if os.name != 'nt':
        raise VaultError('Proteção de credenciais disponível somente no Windows.')
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]

    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 65536:
        raise VaultError('Dados de credencial inválidos.')
    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source, result = Blob(len(payload), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    protect, unprotect = crypt.CryptProtectData, crypt.CryptUnprotectData
    protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    protect.restype = unprotect.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # CRYPTPROTECT_UI_FORBIDDEN; no machine-wide flag.
    ok = (unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)) if decrypt else
          protect(ctypes.byref(source), 'TechMiner ONAX', None, None, None, 1, ctypes.byref(result)))
    if not ok:
        raise VaultError('Windows não conseguiu proteger ou acessar as credenciais.')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def save(path, shopify_token, cj_key, *, protect=None):
    if any(not isinstance(x, str) or not x or any(c.isspace() or ord(c) < 32 for c in x)
           for x in (shopify_token, cj_key)):
        raise VaultError('Credenciais ausentes ou inválidas.')
    protect = protect or _dpapi
    plaintext = json.dumps({'shopify': shopify_token, 'cj': cj_key}, separators=(',', ':')).encode('utf-8')
    encrypted = protect(plaintext)
    if not isinstance(encrypted, bytes) or not encrypted or plaintext in encrypted:
        raise VaultError('Proteção de credenciais falhou.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = path.open('xb')
    except FileExistsError:
        raise VaultError('Cofre existente preservado.') from None
    try:
        with stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        raise VaultError('Não foi possível guardar as credenciais.') from None


def load(path, *, unprotect=None):
    unprotect = unprotect or (lambda data: _dpapi(data, decrypt=True))
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise VaultError('Cofre indisponível.')
        data = json.loads(unprotect(path.read_bytes()).decode('utf-8'))
        if not isinstance(data, dict) or set(data) != {'shopify', 'cj'}:
            raise VaultError('Cofre inválido.')
        if any(not isinstance(v, str) or not v or any(c.isspace() or ord(c) < 32 for c in v) for v in data.values()):
            raise VaultError('Cofre inválido.')
        return data
    except (OSError, ValueError, UnicodeError):
        raise VaultError('Cofre indisponível ou não autorizado para este usuário Windows.') from None
