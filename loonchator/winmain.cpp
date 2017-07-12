#pragma comment(lib, "user32")
#pragma comment(lib, "shell32")
#pragma comment(lib, "ole32")

#define UNICODE
#include <Shlobj.h>
#include <windows.h>

#include <algorithm>
#include <sstream>
#include <string>
#include <vector>

#include "packages.h"
#include "util.h"

#ifdef PROD
const char* own_package_name = "loonchator";
const char* url_schema = "ersatzplut";
const char* api_prefix = "http://db.mooskagh.com/api/v0/";
#else
const char* own_package_name = "loonchator-debug";
const char* url_schema = "ersatzplut-debug";
const char* api_prefix = "http://localhost:8000/api/v0/";
#endif

const char* os_package = "os-win-0.0.0";

std::wstring GetOwnVersion() {
  static const char* own_version =
#include "../version.txt"
      ;
  const char* v = own_version;
  ++v;
  return Conv(v);
}

std::wstring GetExecutableFilename() {
  std::vector<wchar_t> buffer(1024);

  for (;;) {
    DWORD res = GetModuleFileName(0, &buffer[0], buffer.size());
    if (res < buffer.size()) {
      return {buffer.begin(), buffer.begin() + res};
    }
    if (GetLastError() == ERROR_INSUFFICIENT_BUFFER) {
      buffer.resize(buffer.size() * 2);
      continue;
    }
    throw WinException();
  }
}

void MsgBox(const std::wstring& message) {
  MessageBox(0, message.c_str(), nullptr, MB_OK);
}

bool IsInstalled() {
  try {
    auto path = StringSplit(GetExecutableFilename(), L'\\');
    auto own_package = VersionedPackage(path[path.size() - 2]);
    if (own_package.Package() != own_package_name) return false;
  } catch (...) {
    return false;
  }
  return true;
}

std::wstring GetRepositoryPath() {
  auto path = StringSplit(GetExecutableFilename(), L'\\');
  path.resize(path.size() - 2);
  return StringJoin(path, L'\\');
}

void RegisterURIScheme(std::wstring executable) {
  // HKEY_CURRENT_USER\Software\Classes
  std::wstring key = L"Software\\Classes\\" + Conv(url_schema);

  HKEY hkey;
  CHECK(RegCreateKeyEx(HKEY_CURRENT_USER, key.c_str(), 0, nullptr, 0,
                       KEY_READ | KEY_WRITE, nullptr, &hkey, nullptr));
  Finally f([&]() { RegCloseKey(hkey); });

  std::wstring key_default = L"Ersatzplut:Лунчатор!";
  CHECK(RegSetValueEx(hkey, nullptr, 0, REG_SZ,
                      (const BYTE*)key_default.c_str(),
                      (key_default.size() + 1) * sizeof(wchar_t)));
  CHECK(RegSetValueEx(hkey, L"URL Protocol", 0, REG_SZ, (const BYTE*)"", 1));

  HKEY shell_hkey;
  CHECK(RegCreateKeyEx(hkey, L"shell\\open\\command", 0, nullptr, 0,
                       KEY_READ | KEY_WRITE, nullptr, &shell_hkey, nullptr));
  Finally f2([&]() { RegCloseKey(shell_hkey); });

  executable = L"\"" + executable + L"\"";
  executable.append(L" \"%1\"");
  CHECK(RegSetValueEx(shell_hkey, nullptr, 0, REG_SZ,
                      (const BYTE*)executable.c_str(),
                      (executable.size() + 1) * sizeof(wchar_t)));
}

void InstallationFlow() {
  std::wstring caption(L"Лунчатор v" + GetOwnVersion());

  int res = MessageBox(0, L"Хотите установить лунчатор?", caption.c_str(),
                       MB_YESNO | MB_ICONQUESTION);

  if (res != IDYES) return;

  std::vector<wchar_t> buf(MAX_PATH);

  BROWSEINFO info;
  info.hwndOwner = 0;
  info.pidlRoot = nullptr;
  info.pszDisplayName = &buf[0];
  info.lpszTitle = L"Куда устанавливаем?";
  info.ulFlags = BIF_RETURNONLYFSDIRS | BIF_USENEWUI;
  info.lpfn = nullptr;
  info.iImage = -1;

  ITEMIDLIST* item = SHBrowseForFolder(&info);
  if (!item) return;
  if (!SHGetPathFromIDList(item, &buf[0])) throw WinException();

  std::wstring destination(&buf[0]);
  destination += L"\\";
  destination += Conv(own_package_name);
  destination += L"~";
  destination += GetOwnVersion();

  if (!CreateDirectory(destination.c_str(), 0)) {
    if (GetLastError() != ERROR_ALREADY_EXISTS) throw WinException();
  }

  destination += L"\\";
  destination += Conv(own_package_name);
  destination += L".exe";

  if (!(CopyFile(GetExecutableFilename().c_str(), destination.c_str(), false)))
    throw WinException();

  RegisterURIScheme(destination);

  MessageBox(0,
             L"Вроде бы установилось. Теперь должны работать лунчаторовские "
             L"кнопки на сайте db.mooskagh.com. Попробуйте.",
             L"Установилось", MB_ICONINFORMATION);
}

int CALLBACK WinMain(_In_ HINSTANCE hInstance, _In_ HINSTANCE hPrevInstance,
                     _In_ LPSTR lpCmdLine, _In_ int nCmdShow) {
  try {
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    Finally f([]() { CoUninitialize(); });

    if (!IsInstalled()) {
      InstallationFlow();
      return 0;
    }

    MsgBox(L"Нормально!");

  } catch (const Exception& e) {
    MsgBox(e.message());
  }

  return 0;
}