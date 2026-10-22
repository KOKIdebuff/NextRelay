"""Explicit local selections and generated targets; no filename-derived paths.

Windows pins every existing directory against rename/delete and opens final
files with OPEN_REPARSE_POINT. POSIX uses O_NOFOLLOW plus inode checks; caller
must keep the storage root private from hostile same-user writers.
"""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import stat

from .formats import ImportFailure, MAX_FILE, digest


def absolute(path):
    if not isinstance(path, (str,Path)):
        raise ImportFailure('invalid_local_path','selection')
    p=Path(path)
    raw=str(p)
    if (not p.is_absolute() or '..' in p.parts or raw.startswith(('\\\\','//')) or
        '\x00' in raw or (os.name=='nt' and (':' in raw[2:] or len(p.drive)!=2))):
        raise ImportFailure('invalid_local_path','selection')
    return p


def _regular(info, directory=False):
    if (stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ImportFailure('unsafe_local_path','path')


@contextmanager
def _windows_handle(path, *, directory=False, create=False):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    open_file=kernel.CreateFileW
    open_file.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    open_file.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
    class Info(ctypes.Structure):
        _fields_=[('attributes',wintypes.DWORD),('created',wintypes.FILETIME),('accessed',wintypes.FILETIME),
                  ('written',wintypes.FILETIME),('volume',wintypes.DWORD),('high',wintypes.DWORD),
                  ('low',wintypes.DWORD),('links',wintypes.DWORD),('index_high',wintypes.DWORD),('index_low',wintypes.DWORD)]
    # Share READ only: prevents a competing handle writing/replacing selected
    # files or renaming any pinned parent during the operation.
    access=0x40000000 if create else (0x80 if directory else 0x80000000)
    handle=open_file(str(path),access,1,None,1 if create else 3,0x00200000|(0x02000000 if directory else 0),None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError('local_open_failed')
    try:
        info=Info()
        if not kernel.GetFileInformationByHandle(handle,ctypes.byref(info)) or info.attributes&0x400:
            raise ImportFailure('unsafe_local_path','path')
        if directory != bool(info.attributes&0x10):
            raise ImportFailure('unsafe_local_path','path')
        yield handle
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def parents(path):
    p=absolute(path)
    with ExitStack() as stack:
        for part in reversed(p.parent.parents):
            if os.name=='nt':
                stack.enter_context(_windows_handle(part,directory=True))
            else:
                _regular(part.lstat(),True)
        if os.name=='nt':
            stack.enter_context(_windows_handle(p.parent,directory=True))
        else:
            _regular(p.parent.lstat(),True)
        yield p


@contextmanager
def opened(path, *, create=False):
    with parents(path) as p:
        if os.name=='nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            with _windows_handle(p,create=create) as handle:
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                duplicate=wintypes.HANDLE()
                kernel.GetCurrentProcess.restype=wintypes.HANDLE
                kernel.DuplicateHandle.argtypes=[wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
                process=kernel.GetCurrentProcess()
                if not kernel.DuplicateHandle(process,handle,process,ctypes.byref(duplicate),0,False,2):
                    raise OSError('local_open_failed')
                fd=msvcrt.open_osfhandle(duplicate.value,os.O_BINARY|(os.O_WRONLY if create else os.O_RDONLY))
                with os.fdopen(fd,'wb' if create else 'rb') as stream:
                    _regular(os.fstat(stream.fileno()))
                    yield stream
        else:
            flags=(os.O_WRONLY|os.O_CREAT|os.O_EXCL if create else os.O_RDONLY)|getattr(os,'O_NOFOLLOW',0)
            fd=os.open(p,flags,0o600)
            with os.fdopen(fd,'wb' if create else 'rb') as stream:
                _regular(os.fstat(stream.fileno()))
                if p.lstat().st_ino != os.fstat(stream.fileno()).st_ino:
                    raise ImportFailure('unsafe_local_path','path')
                yield stream


def inspect(path, *, limit=MAX_FILE):
    """No body read for an oversized file; never read a directory/device/link."""
    try:
        with opened(path) as stream:
            size=os.fstat(stream.fileno()).st_size
            if size>limit:
                raise ImportFailure('file_size_limit','read')
            data=stream.read(limit+1)
            if len(data)>limit:
                raise ImportFailure('file_size_limit','read')
            if len(data)!=size:
                raise ImportFailure('input_changed','read')
            return data
    except ImportFailure:
        raise
    except OSError:
        raise ImportFailure('local_file_unavailable','read') from None


def persist(path, data):
    """Exclusive stage + flush/fsync + atomic rename, never overwrite a target."""
    path=absolute(path)
    stage=path.with_suffix(path.suffix+'.stage')
    try:
        with parents(path):
            with opened(stage,create=True) as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            # Windows rename is atomic and fails if the destination exists.
            # POSIX link is atomic no-clobber then removes the stage.
            if os.name=='nt':
                os.rename(stage,path)
            else:
                os.link(stage,path,follow_symlinks=False);os.unlink(stage)
    except OSError:
        raise ImportFailure('local_save_failed','save') from None


def remove_owned(path):
    """Only called for exact DB-registered generated paths, never scans a root."""
    try:
        with parents(path) as p:
            info=p.lstat()
            _regular(info)
            p.unlink()
        return True
    except FileNotFoundError:
        return True
    except (OSError,ImportFailure):
        return False
