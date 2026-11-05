#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#ifndef WINVER
#define WINVER _WIN32_WINNT
#endif
// Windows types must precede the Shell and Toolhelp headers.
// clang-format off
#include <windows.h>
// clang-format on
#include <shellapi.h>
#include <tlhelp32.h>
#include <wchar.h>

static BOOL CALLBACK close_bridge(HWND window, LPARAM pid) {
    DWORD owner = 0;
    GetWindowThreadProcessId(window, &owner);
    if (owner == (DWORD)pid) {
        DWORD_PTR result;
        SendMessageTimeoutW(window, WM_CLOSE, 0, 0,
                            SMTO_ABORTIFHUNG | SMTO_BLOCK | SMTO_ERRORONEXIT, 300, &result);
    }
    return TRUE;
}

static HANDLE owned_process(DWORD pid, const wchar_t *image) {
    HANDLE process = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE, FALSE, pid);
    if (!process)
        return NULL;
    wchar_t actual[32768];
    DWORD length = 32768, session = 0, current_session = 0;
    if (!QueryFullProcessImageNameW(process, 0, actual, &length) || _wcsicmp(actual, image) != 0 ||
        !ProcessIdToSessionId(pid, &session) ||
        !ProcessIdToSessionId(GetCurrentProcessId(), &current_session) ||
        session != current_session) {
        CloseHandle(process);
        return NULL;
    }
    return process;
}

static int shutdown_installation(const wchar_t *directory) {
    wchar_t root[32768], bridge[32768], python[32768];
    DWORD length = GetFullPathNameW(directory, 32768, root, NULL);
    if (!length || length >= 32768 ||
        swprintf(bridge, 32768, L"%ls\\native\\OpenASRInputBridge.exe", root) < 0 ||
        swprintf(python, 32768, L"%ls\\python\\pythonw.exe", root) < 0)
        return 1;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
        return 1;
    HANDLE processes[128];
    size_t count = 0;
    PROCESSENTRY32W entry = {0};
    entry.dwSize = sizeof(entry);
    BOOL next = Process32FirstW(snapshot, &entry);
    while (next) {
        if (_wcsicmp(entry.szExeFile, L"OpenASRInputBridge.exe") == 0) {
            HANDLE child = owned_process(entry.th32ProcessID, bridge);
            if (child) {
                if (count + 2 > sizeof(processes) / sizeof(processes[0])) {
                    CloseHandle(child);
                    CloseHandle(snapshot);
                    for (size_t i = 0; i < count; ++i)
                        CloseHandle(processes[i]);
                    return 1;
                }
                processes[count++] = child;
                // Only the private pythonw parent of our exact bridge image is
                // owned by this installation. Other Python/IME processes stay.
                HANDLE parent = owned_process(entry.th32ParentProcessID, python);
                BOOL signalled = FALSE;
                if (parent) {
                    processes[count++] = parent;
                    wchar_t name[80];
                    swprintf(name, 80, L"Local\\OpenASRInput-Stop-%lu", entry.th32ParentProcessID);
                    HANDLE event = OpenEventW(EVENT_MODIFY_STATE, FALSE, name);
                    if (event) {
                        signalled = SetEvent(event);
                        CloseHandle(event);
                    }
                }
                // Named IPC also works from Installer's separate desktop.
                if (!signalled)
                    EnumWindows(close_bridge, (LPARAM)entry.th32ProcessID);
            }
        }
        next = Process32NextW(snapshot, &entry);
    }
    CloseHandle(snapshot);
    ULONGLONG deadline = GetTickCount64() + 8000;
    while (GetTickCount64() < deadline) {
        BOOL alive = FALSE;
        for (size_t i = 0; i < count; ++i)
            alive |= WaitForSingleObject(processes[i], 0) == WAIT_TIMEOUT;
        if (!alive)
            break;
        Sleep(50);
    }
    int status = 0;
    for (size_t i = 0; i < count; ++i) {
        if (WaitForSingleObject(processes[i], 0) == WAIT_TIMEOUT) {
            // A hung owned process must not leave installed files locked.
            if (!TerminateProcess(processes[i], 0) ||
                WaitForSingleObject(processes[i], 2000) != WAIT_OBJECT_0)
                status = 1;
        }
        CloseHandle(processes[i]);
    }
    return status;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance;
    (void)previous;
    (void)show;
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv)
        return 1;
    if (argc > 1 && wcscmp(argv[1], L"--shutdown") == 0) {
        int status = argc == 3 ? shutdown_installation(argv[2]) : 1;
        LocalFree(argv);
        return status;
    }
    LocalFree(argv);
    wchar_t root[32768], python[32768], command[65536];
    DWORD size = GetModuleFileNameW(NULL, root, 32768);
    if (!size || size >= 32768)
        return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash)
        return 1;
    *slash = 0;
    if (swprintf(python, 32768, L"%ls\\python\\pythonw.exe", root) < 0 ||
        swprintf(command, 65536, L"\"%ls\" \"%ls\\app\\launch.py\" %ls", python, root, arguments) <
            0)
        return 1;
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, root, &startup,
                        &process)) {
        MessageBoxW(NULL, L"无法启动 OpenASRInput，请重新安装完整应用。", L"OpenASRInput",
                    MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
