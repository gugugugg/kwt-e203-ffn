"""Read the command line and parent of a known local study process."""
import ctypes
from ctypes import wintypes
import json
import sys

kernel=ctypes.WinDLL('kernel32',use_last_error=True)
nt=ctypes.WinDLL('ntdll')
kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
kernel.OpenProcess.restype=wintypes.HANDLE
nt.NtQueryInformationProcess.argtypes=[wintypes.HANDLE,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG)]
class Unicode(ctypes.Structure):
    _fields_=[('length',wintypes.USHORT),('capacity',wintypes.USHORT),('buffer',ctypes.c_void_p)]

def describe(pid):
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return dict(pid=pid,exited=True)
    try:
        needed=wintypes.ULONG()
        nt.NtQueryInformationProcess(handle,60,None,0,ctypes.byref(needed))
        buf=ctypes.create_string_buffer(needed.value)
        status=nt.NtQueryInformationProcess(handle,60,buf,len(buf),ctypes.byref(needed))
        if status:return dict(pid=pid,query_status=status)
        u=Unicode.from_buffer(buf);command=ctypes.wstring_at(u.buffer,u.length//2)
        basic=(ctypes.c_void_p*6)()
        status=nt.NtQueryInformationProcess(handle,0,basic,ctypes.sizeof(basic),ctypes.byref(needed))
        return dict(pid=pid,command=command,ppid=int(basic[5] or 0) if not status else None)
    finally:kernel.CloseHandle(handle)

if __name__=='__main__':
    print(json.dumps([describe(int(pid)) for pid in sys.argv[1:]],indent=2))
