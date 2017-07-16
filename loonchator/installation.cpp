#define UNICODE
#include <Shlobj.h>
#include <windows.h>

#include "installation.h"
#include "packages.h"
#include "util.h"

bool IsInstalled() {
  try {
    auto path = StringSplit(GetExecutableFilename(), L'\\');
    auto own_package = VersionedPackage(path[path.size() - 2]);
    if (own_package.Package() != GetOwnPackageName()) return false;
  } catch (...) {
    return false;
  }
  return true;
}

void RegisterURIScheme(std::wstring executable) {
  std::wstring key = L"Software\\Classes\\" + Conv(GetUrlSchema());

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
  std::wstring caption(L"Лунчатор v" + Conv(GetOwnVersion()));

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
  destination += Conv(GetOwnPackageName());
  destination += L"~";
  destination += Conv(GetOwnVersion());

  if (!CreateDirectory(destination.c_str(), 0)) {
    if (GetLastError() != ERROR_ALREADY_EXISTS) throw WinException();
  }

  destination += L"\\";
  destination += Conv(GetOwnPackageName());
  destination += L".exe";

  if (!(CopyFile(GetExecutableFilename().c_str(), destination.c_str(), false)))
    throw WinException();

  RegisterURIScheme(destination);

  MessageBox(0,
             L"Вроде бы установилось. Теперь должны работать лунчаторовские "
             L"кнопки на сайте db.mooskagh.com. Попробуйте.",
             L"Установилось", MB_ICONINFORMATION);
}
